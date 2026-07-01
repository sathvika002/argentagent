import streamlit as st
from utils.auth import login_user, signup_user, get_google_auth_url, exchange_code_for_user, login_or_create_sso_user, reset_password
from utils.db import init_db, connect
from utils.transactions import (
    add_transaction, generate_transfer_credit, get_all_transactions,
    update_transaction_status, reverse_transaction,
    get_user_balance, get_pending_transaction, generate_salary_credit, generate_refund_credit
)
from pipeline.run_pipeline import run_pipeline
from agents.agent import fraud_agent_reply
import random
import secrets
import pandas as pd
from datetime import datetime, timedelta

# Initialize database (creates tables and runs migrations)
init_db()

def generate_otp():
    return str(random.randint(100000, 999999))

st.set_page_config(page_title="argentagent", layout="wide")
st.title("argentagent")

# ---------------- SESSION STATE ----------------
if "logged_in" not in st.session_state:
    st.session_state.logged_in = False
    st.session_state.username = None

if "role" not in st.session_state:
    st.session_state.role = "customer"

if "show_agent" not in st.session_state:
    st.session_state.show_agent = False

if "chat_history" not in st.session_state:
    st.session_state.chat_history = []

if "awaiting_otp" not in st.session_state:
    st.session_state.awaiting_otp = False

if "generated_otp" not in st.session_state:
    st.session_state.generated_otp = None

if "intent" not in st.session_state:
    st.session_state.intent = None

if "last_result" not in st.session_state:
    st.session_state.last_result = None

if "pending_tx" not in st.session_state:
    st.session_state.pending_tx = None

if "pending_tx_meta" not in st.session_state:
    st.session_state.pending_tx_meta = {}

if "active_tab" not in st.session_state:
    st.session_state.active_tab = "Transaction"

if "awaiting_otp" not in st.session_state:
    st.session_state.awaiting_otp = False

if "generated_otp" not in st.session_state:
    st.session_state.generated_otp = None

if "otp_attempts" not in st.session_state:
    st.session_state.otp_attempts = 0

# NEW — oauth_state holds the random nonce we sent to Google
# so we can verify the redirect wasn't forged
if "oauth_state" not in st.session_state:
    st.session_state.oauth_state = None

# Password reset flow state
if "reset_flow" not in st.session_state:
    st.session_state.reset_flow = None  # None, "enter_username", "verify_otp", "set_password"

if "reset_username" not in st.session_state:
    st.session_state.reset_username = None

if "reset_otp" not in st.session_state:
    st.session_state.reset_otp = None

if "reset_otp_attempts" not in st.session_state:
    st.session_state.reset_otp_attempts = 0


# ---------------- GOOGLE OAUTH CALLBACK HANDLER ---------------

def handle_oauth_callback():
    params = st.query_params
    code = params.get("code")

    if not code or st.session_state.logged_in:
        return

    # Clear FIRST — so if Streamlit reruns, the code isn't there anymore
    st.query_params.clear()

    with st.spinner("Signing you in with Google..."):
        user_info = exchange_code_for_user(code)

    if not user_info:
        st.error("Could not retrieve your Google profile. Please try again.")
        return

    username = login_or_create_sso_user(
        google_id = user_info.get("sub", ""),
        email     = user_info.get("email", ""),
        name      = user_info.get("name", ""),
    )

    st.session_state.logged_in = True
    st.session_state.username  = username
    
    # Fetch role from DB after SSO login
    conn = connect()
    cur = conn.cursor()
    cur.execute("SELECT role FROM users WHERE username = %s", (username,))
    role_row = cur.fetchone()
    conn.close()
    st.session_state.role = role_row[0] if role_row else "customer"
    
    st.rerun()

handle_oauth_callback()


# ---------------- RESTORE PENDING STATE ----------------
def restore_pending_state(username: str):
    if st.session_state.pending_tx is not None:
        return

    row = get_pending_transaction(username)
    if not row:
        return

    _, amount, time, location, risk_level, report = row

    st.session_state.pending_tx_meta = {
        "amount":     amount,
        "time":       time,
        "location":   location,
        "risk_level": risk_level,
    }
    st.session_state.pending_tx = {
        "transaction": {"amount": amount, "location": location, "username": username},
        "risk_score":  50,
        "anomalies":   [],
        "report":      report or "",
    }
    st.session_state.show_agent = True  # ← is this line there?
    if not st.session_state.chat_history:
        st.session_state.chat_history = [
            {"role": "assistant", "content": "This transaction looks unusual. Was this you?"}
        ]


# --------- PASSWORD RESET FLOW ---------
def password_reset_page():
    st.subheader("Forgot Password?")
    
    # Step 1: Enter Username
    if st.session_state.reset_flow is None or st.session_state.reset_flow == "enter_username":
        st.write("Enter your username to reset your password.")
        reset_user = st.text_input("Username", key="reset_username_input", value=st.session_state.reset_username or "")
        
        col1, col2 = st.columns([2, 1])
        with col1:
            if st.button("Send OTP", key="send_otp_btn", use_container_width=True):
                if not reset_user:
                    st.error("Please enter your username")
                else:
                    conn = connect()
                    cur = conn.cursor()
                    cur.execute("SELECT username FROM users WHERE username = %s", (reset_user,))
                    if cur.fetchone():
                        st.session_state.reset_username = reset_user
                        st.session_state.reset_otp = generate_otp()
                        st.session_state.reset_flow = "verify_otp"
                        st.session_state.reset_otp_attempts = 0
                        conn.close()
                        st.success(f"OTP sent to {reset_user}")
                        st.info(f"**Your OTP:** `{st.session_state.reset_otp}`")  # Show for testing
                        st.rerun()
                    else:
                        st.error("Username not found")
                        conn.close()
        
        with col2:
            if st.button("Back", key="back_to_login"):
                st.session_state.reset_flow = None
                st.session_state.reset_username = None
                st.session_state.reset_otp = None
                st.rerun()
    
    # Step 2: Verify OTP
    elif st.session_state.reset_flow == "verify_otp":
        st.write(f"Enter the OTP sent to **{st.session_state.reset_username}**")
        st.info("Check your email or SMS for the OTP. (For testing, the OTP is shown below)")
        st.code(f"{st.session_state.reset_otp}", language=None)
        
        entered_otp = st.text_input("Enter 6-digit OTP", key="otp_input", max_chars=6)
        
        col1, col2 = st.columns([2, 1])
        with col1:
            if st.button("Verify OTP", key="verify_otp_btn", use_container_width=True):
                if not entered_otp:
                    st.error("Please enter OTP")
                elif entered_otp == st.session_state.reset_otp:
                    st.session_state.reset_flow = "set_password"
                    st.success("✓ OTP verified!")
                    st.rerun()
                else:
                    st.session_state.reset_otp_attempts += 1
                    remaining = 3 - st.session_state.reset_otp_attempts
                    st.error(f"Invalid OTP. {remaining} attempts remaining.")
                    
                    if st.session_state.reset_otp_attempts >= 3:
                        st.session_state.reset_flow = None
                        st.session_state.reset_username = None
                        st.session_state.reset_otp = None
                        st.error("Too many failed attempts. Please start over.")
                        st.rerun()
        
        with col2:
            if st.button("Back", key="back_otp"):
                st.session_state.reset_flow = "enter_username"
                st.rerun()
    
    # Step 3: Set New Password
    elif st.session_state.reset_flow == "set_password":
        st.write(f"Set a new password for **{st.session_state.reset_username}**")
        
        new_password = st.text_input("New Password", type="password", key="new_pwd")
        confirm_password = st.text_input("Confirm Password", type="password", key="confirm_pwd")
        
        if st.button("Reset Password", use_container_width=True, key="reset_pwd_btn"):
            if not new_password or not confirm_password:
                st.error("Please fill in all fields")
            elif len(new_password) < 6:
                st.error("Password must be at least 6 characters")
            elif new_password != confirm_password:
                st.error("Passwords don't match")
            else:
                # Reset password in database
                if reset_password(st.session_state.reset_username, new_password):
                    st.success("Password reset successful!")
                    st.toast("Your password has been reset. Please log in with your new password.")
                    st.info("You can now log in with your new password.")
                    
                    # Clear reset state
                    st.session_state.reset_flow = None
                    st.session_state.reset_username = None
                    st.session_state.reset_otp = None
                    st.session_state.reset_otp_attempts = 0
                    
                    if st.button("Back to Login"):
                        st.rerun()
                else:
                    st.error("Failed to reset password. Please try again.")

# --------- AUTH PAGE ---------
def auth_page():
    # Show password reset page if user clicked "Forgot Password"
    if st.session_state.reset_flow is not None:
        password_reset_page()
        return
    
    tab1, tab2 = st.tabs(["Login", "Sign Up"])

    with tab1:
        username = st.text_input("Username", key="login_username")
        password = st.text_input("Password", type="password", key="login_password")

        col1, col2 = st.columns([1, 1])
        with col1:
            if st.button("Login", use_container_width=True):
                result = login_user(username, password)
                if result is True:
                    st.session_state.logged_in = True
                    st.session_state.username = username
                    
                    # Fetch role from DB after login
                    conn = connect()
                    cur = conn.cursor()
                    cur.execute("SELECT role FROM users WHERE username = %s", (username,))
                    role_row = cur.fetchone()
                    conn.close()
                    st.session_state.role = role_row[0] if role_row else "customer"
                    
                    st.rerun()
                elif result == "LOCKED":
                    st.error("Account locked. Try again in 15 minutes.")
                else:
                    st.error("Invalid credentials")
        
        with col2:
            if st.button("Forgot Password?", use_container_width=True, key="forgot_pwd_btn"):
                st.session_state.reset_flow = "enter_username"
                st.rerun()

        st.divider()
        st.caption("or continue with")

        if st.button("Sign in with Google", use_container_width=True, key="google_login"):
            auth_url = get_google_auth_url("unused")
            st.markdown(
                f'<meta http-equiv="refresh" content="0; url={auth_url}">',
                unsafe_allow_html=True,
            )

    with tab2:
        new_user  = st.text_input("Username", key="signup_username")
        new_email = st.text_input("Email", key="signup_email")
        new_pass  = st.text_input("Password", type="password", key="signup_password")

        if st.button("Sign Up"):
            if not new_user or not new_email or not new_pass:
                st.error("Please fill in all fields.")
            else:
                success = signup_user(new_user, new_pass, email=new_email)
                if success:
                    st.success("Account created! You can now log in.")
                else:
                    st.error("Username already taken, try another.")

        st.divider()
        st.caption("or continue with")

        if st.button("Sign up with Google", use_container_width=True, key="google_signup"):
            auth_url = get_google_auth_url("unused")
            st.markdown(
                f'<meta http-equiv="refresh" content="0; url={auth_url}">',
                unsafe_allow_html=True,
            )


# ---------------- MAIN APP ----------------
def main_app():
    # Session expiry — 15 minutes of inactivity
    SESSION_TIMEOUT_MINUTES = 15
    if "login_time" in st.session_state:
        elapsed = (datetime.now() - st.session_state.login_time).seconds / 60
        if elapsed > SESSION_TIMEOUT_MINUTES:
            st.session_state.clear()
            st.warning("Session expired. Please log in again.")
            st.rerun()
    else:
        st.session_state.login_time = datetime.now()

    # Update last activity time on every interaction
    st.session_state.login_time = datetime.now()
    restore_pending_state(st.session_state.username)

    st.write(f"welcome {st.session_state.username}")

    # Logout button in sidebar
    if st.button("Logout"):
        st.session_state.clear()
        st.rerun()

    # Build tabs list — only add Admin Tools if user role is admin
    tabs = ["Transaction", "Monitoring", "Balance"]
    if st.session_state.role == "admin":
        tabs.append("Admin Tools")
    
    # Create tab objects
    tab_objects = st.tabs(tabs)
    tab1, tab2, tab3 = tab_objects[:3]
    tab4 = tab_objects[3] if len(tab_objects) > 3 else None

    # ======================================================
    # TRANSACTION TAB
    # ======================================================
    with tab1:
        st.subheader("make your transaction")

        if st.session_state.pending_tx is not None:
            st.warning(
                "⚠️ A suspicious transaction is pending your review. "
                "Head to the **Monitoring** tab to verify it."
            )

        if st.session_state.get("_tx_clear"):
            del st.session_state["tx_amount"]
            st.session_state._tx_clear = False

        amount = st.number_input("enter amount", min_value=0, key="tx_amount")
        if st.button("save transaction"):
            # Pass only username + amount — pipeline generates everything else
            result = run_pipeline({
                "username": st.session_state.username,
                "amount":   amount,
            })

            risk_level = result.get("risk_level", "LOW")
            action     = result.get("action", "ALLOW")
            decline_reason = result.get("decline_reason", None)

            scored_tx   = result.get("transaction", {})
            tx_time     = scored_tx.get("timestamp", "")
            tx_location = scored_tx.get("location", "")

            st.session_state.last_result = result
            st.session_state._tx_clear = True  # clears the input on next render

            # ── DECLINED → insufficient funds ─────────────
            if decline_reason == "INSUFFICIENT_FUNDS":
                add_transaction(
                    st.session_state.username,
                    amount, tx_time, tx_location,
                    "LOW", "declined", result["report"], transaction_type="DEBIT"
                )
                current_balance = get_user_balance(st.session_state.username)
                st.error(
                    f" **Transaction Declined**\n\n"
                    f"Amount: ₹{amount:,.2f}\n\n"
                    f"**Reason**: Insufficient funds\n\n"
                    f"Your current balance: ₹{current_balance:,.2f}\n\n"
                    f"To complete this transaction, you need ₹{amount - current_balance:,.2f} more.\n\n"
                    f"💡 **Tip**: Simulate a salary deposit or transfer to add funds to your account."
                )

            # ── HIGH → auto-block, no balance deduction ─────────────
            elif action == "BLOCK":
                add_transaction(
                    st.session_state.username,
                    amount, tx_time, tx_location,
                    risk_level, "reversed", result["report"], transaction_type="DEBIT"
                )
                st.error(
                    f"Transaction of ₹{amount:,.2f} was **blocked** due to high fraud risk. "
                    "Your balance was not charged."
                )

            # ── MEDIUM → pending, needs verification ─────────────────
            elif action == "VERIFY":
                add_transaction(
                    st.session_state.username,
                    amount, tx_time, tx_location,
                    risk_level, "pending", result["report"], transaction_type="DEBIT"
                )
                st.session_state.pending_tx = result
                st.session_state.pending_tx_meta = {
                    "amount":     amount,
                    "time":       tx_time,
                    "location":   tx_location,
                    "risk_level": risk_level,
                }
                st.session_state.show_agent      = True
                st.session_state.awaiting_otp    = False
                st.session_state.generated_otp   = None
                st.session_state.chat_history    = [
                    {"role": "assistant",
                     "content": "This transaction looks unusual. Was this you?"}
                ]
                st.warning(
                    "Suspicious transaction detected. "
                    "Go to the **Monitoring** tab to verify it."
                )

            # ── LOW → approve normally ───────────────────────────────
            elif action == "ALLOW":
                add_transaction(
                    st.session_state.username,
                    amount, tx_time, tx_location,
                    risk_level, "approved", result["report"], transaction_type="DEBIT"
                )
                st.success("transaction approved.")

        # -------- TRANSACTION HISTORY --------
        if st.button("transaction history"):
            st.session_state.show_transactions = not st.session_state.get("show_transactions", False)

        if st.session_state.get("show_transactions", False):
            data = get_all_transactions(st.session_state.username)

            if data:
                table_data = []
                for row in data:
                    table_data.append({
                        "#":        row[0],  # Transaction ID
                        "Amount":   f"₹{row[1]:,.2f}",
                        "Time":     row[2],
                        "Location": row[3],
                        "Risk":     row[4],
                        "Status":   row[5]
                    })

                df = pd.DataFrame(table_data, columns=["#", "Amount", "Time", "Location", "Risk", "Status"])
                df["Time"] = pd.to_datetime(df["Time"], errors="coerce")
                df["Time"] = df["Time"].dt.strftime("%A, %d %B %Y, %I:%M %p")

                st.write("### transaction actions")

                for i, row in enumerate(data):
                    col1, col2, col3, col4, col5, col6, col7 = st.columns(7)

                    tx_id      = f"#{row[0]}"
                    amount_d   = f"₹{row[1]:,.2f}"
                    time_d     = row[2]
                    location_d = row[3]
                    risk_d     = row[4]
                    status_d   = row[5]

                    style = "color:red" if risk_d in ["HIGH", "MEDIUM"] else ""

                    col1.markdown(f"<span style='{style}'>{tx_id}</span>",     unsafe_allow_html=True)
                    col2.markdown(f"<span style='{style}'>{amount_d}</span>",   unsafe_allow_html=True)
                    col3.markdown(f"<span style='{style}'>{time_d}</span>",     unsafe_allow_html=True)
                    col4.markdown(f"<span style='{style}'>{location_d}</span>", unsafe_allow_html=True)
                    col5.markdown(f"<span style='{style}'>{risk_d}</span>",     unsafe_allow_html=True)
                    col6.markdown(f"<span style='{style}'>{status_d}</span>",   unsafe_allow_html=True)

                    if col7.button("View", key=f"view_{i}"):
                        st.session_state.selected_tx  = row
                        st.session_state.active_tab   = "Monitoring"
                        st.rerun()

                def highlight(row):
                    if row["Risk"] in ["HIGH", "MEDIUM"]:
                        return ['color: red'] * len(row)
                    return [''] * len(row)

                styled_df = df.style.apply(highlight, axis=1)
                st.dataframe(styled_df, use_container_width=True)

    # ======================================================
    # MONITORING TAB
    # ======================================================
    with tab2:
        st.subheader("Monitoring System")

        if st.session_state.pending_tx is not None:
            result = st.session_state.pending_tx
            meta   = st.session_state.pending_tx_meta

            st.write("### suspicious transaction")
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("Amount",     f"₹{meta.get('amount', 0):,.2f}")
            c2.metric("Risk Level", meta.get("risk_level", ""))
            c3.metric("Location",   meta.get("location", ""))
            c4.metric("Status",     "Pending")
            st.divider()

            if st.session_state.awaiting_otp:
                st.info("OTP sent to your registered device. Enter it below to approve.")

                with st.expander("Demo — view OTP (prototype only)"):
                    st.code(st.session_state.generated_otp)

                otp_input = st.text_input("Enter OTP", max_chars=6, key="otp_input_field")
                btn_col1, btn_col2 = st.columns(2)

                with btn_col1:
                    if st.button("Confirm OTP"):
                        if otp_input == st.session_state.generated_otp:
                            conn = connect()
                            cur  = conn.cursor()
                            cur.execute("""
                                UPDATE transactions SET status = 'approved'
                                WHERE id = (
                                    SELECT id FROM transactions
                                    WHERE username = %s AND status = 'pending'
                                    ORDER BY id DESC LIMIT 1
                                )
                            """, (st.session_state.username,))
                            conn.commit()
                            conn.close()

                            st.success("OTP verified. Transaction approved!")
                            st.session_state.pending_tx      = None
                            st.session_state.pending_tx_meta = {}
                            st.session_state.awaiting_otp    = False
                            st.session_state.generated_otp   = None
                            st.session_state.show_agent      = False
                            st.session_state.chat_history    = []
                            st.session_state.otp_attempts    = 0
                            st.rerun()
                        else:
                            st.session_state.otp_attempts += 1
                            if st.session_state.otp_attempts >= 3:
                                st.error("Too many wrong attempts. Transaction has been blocked.")
                                reverse_transaction(
                                    st.session_state.username,
                                    meta.get("amount", 0)
                                )
                                st.session_state.pending_tx      = None
                                st.session_state.pending_tx_meta = {}
                                st.session_state.awaiting_otp    = False
                                st.session_state.generated_otp   = None
                                st.session_state.show_agent      = False
                                st.session_state.chat_history    = []
                                st.session_state.otp_attempts    = 0
                                st.rerun()
                            else:
                                remaining = 3 - st.session_state.otp_attempts
                                st.error(f"Wrong OTP. {remaining} attempt(s) remaining.")

            elif st.session_state.show_agent:
                st.write("### Verification Agent")

                for msg in st.session_state.chat_history:
                    with st.chat_message(msg["role"]):
                        st.write(msg["content"])

                user_input = st.chat_input("Type your response...")

                if user_input:
                    st.session_state.chat_history.append({
                        "role": "user", "content": user_input
                    })

                    agent_resp = fraud_agent_reply(
                        risk_result=result,
                        user_message=user_input,
                        history=st.session_state.chat_history
                    )

                    reply  = agent_resp.get("reply", "Could you clarify?")
                    intent = agent_resp.get("intent", "UNCLEAR")

                    st.session_state.chat_history.append({
                        "role": "assistant", "content": reply
                    })

                    if intent == "YES":
                        st.session_state.generated_otp = generate_otp()
                        st.session_state.awaiting_otp  = True
                        st.rerun()

                    elif intent == "NO":
                        reverse_transaction(st.session_state.username, meta.get("amount", 0))
                        st.session_state.pending_tx      = None
                        st.session_state.pending_tx_meta = {}
                        st.session_state.show_agent      = False
                        st.session_state.chat_history    = []
                        st.error("Got it. Transaction blocked and amount refunded.")
                        st.rerun()

                    else:
                        st.rerun()

        elif "selected_tx" in st.session_state:
            tx = st.session_state.selected_tx

            st.write("### Selected Transaction")
            st.write(f"Amount: ₹{tx[0]:,.2f}")
            st.write(f"Time: {tx[1]}")
            st.write(f"Location: {tx[2]}")
            st.write(f"Risk: {tx[3]}")
            st.write(f"Status: {tx[4]}")

            st.write("### Risk Analysis")
            if tx[3] in ["HIGH", "MEDIUM"]:
                st.error("This transaction was flagged as risky.")
            else:
                st.success("This transaction was normal.")

        else:
            st.info("No active alerts. Make a transaction or click View on a past one.")

    # ======================================================
    # BALANCE TAB
    # ======================================================
    with tab3:
        balance = get_user_balance(st.session_state.username)
        st.metric("Current Balance", f"₹{balance:,.2f}")
        
        st.divider()
        st.subheader("simulate credits to your account")
        st.write("In real banking, accounts receive salary, refunds, and transfers. Let's add some!")
        
        st.write("### salary ")
        col1, col2 = st.columns([3, 1])
        with col1:
            salary_amount = st.number_input("salary amount", min_value=0, value=80000, step=10000, key="salary_input")
        with col2:
            if st.button("deposit salary"):
                from utils.time_utils import get_current_time
                current_time = get_current_time(inject_fraud=False)
                generate_salary_credit(st.session_state.username, current_time, salary_amount)
                st.success(f"Salary of ₹{salary_amount:,.2f} added!")
                st.rerun()
        
        st.write("### refund from merchant")
        col1, col2 = st.columns([3, 1])
        with col1:
            refund_amount = st.number_input("Refund amount", min_value=0, value=5000, step=1000, key="refund_input")
        with col2:
            if st.button("refund"):
                from utils.time_utils import get_current_time
                current_time = get_current_time(inject_fraud=False)
                generate_refund_credit(st.session_state.username, current_time, refund_amount)
                st.success(f"Refund of ₹{refund_amount:,.2f} added!")
                st.rerun()
        
        st.write("### bank transfer / UPI receive")
        col1, col2, col3 = st.columns([2, 2, 1])
        with col1:
            transfer_amount = st.number_input("Transfer amount", min_value=0, value=10000, step=5000, key="transfer_input")
        with col2:
            source = st.text_input("From (e.g., Friend, Family, Business)", value="Friend", key="transfer_source")
        with col3:
            if st.button("receive"):
                from utils.time_utils import get_current_time
                current_time = get_current_time(inject_fraud=False)
                generate_transfer_credit(st.session_state.username, current_time, transfer_amount, source)
                st.success(f"Transfer of ₹{transfer_amount:,.2f} from {source} added!")
                st.rerun()
        
        st.divider()

    # ======================================================
    # ADMIN TOOLS TAB — Watermark Decoder (admin only)
    # ======================================================
    if tab4 is not None:
        with tab4:
            st.subheader("Watermark Decoder")
            st.write("Paste a report to extract the hidden user watermark.")
            
            from utils.watermark import extract_watermark, _username_to_code
            
            # Fetch all known users from DB
            conn = connect()
            cur = conn.cursor()
            cur.execute("SELECT username FROM users")
            known_users = [row[0] for row in cur.fetchall()]
            conn.close()
            
            report_paste = st.text_area(
                "Paste leaked/suspicious report text:",
                height=200,
                key="watermark_paste"
            )
            
            if st.button("Decode Watermark", key="decode_btn"):
                if not report_paste.strip():
                    st.warning("Please paste a report first.")
                else:
                    extracted_bits = extract_watermark(report_paste)
                    
                    if not extracted_bits:
                        st.error("No watermark found in this text.")
                        st.info("This report was either not generated by ArgentAgent, or has been stripped of its watermark.")
                    else:
                        st.success(f"✓ Watermark found: `{extracted_bits}`")
                        
                        # Brute-force match against known users
                        found = False
                        for user in known_users:
                            if _username_to_code(user) == extracted_bits:
                                st.success(f" **User identified: `{user}`**")
                                found = True
                                break
                        
                        if not found:
                            st.warning("⚠️ Watermark extracted but no matching user found in database.")

# ---------------- ROUTER ----------------
if st.session_state.logged_in:
    main_app()
else:
    auth_page()