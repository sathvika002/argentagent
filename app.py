import streamlit as st
from utils.auth import login_user, signup_user, get_google_auth_url, exchange_code_for_user, login_or_create_sso_user
from utils.db import init_db, connect
from utils.transactions import (
    add_transaction, get_all_transactions,
    update_transaction_status, reverse_transaction,
    get_user_balance, get_pending_transaction
)
from pipeline.run_pipeline import run_pipeline
from agents.agent import fraud_agent_reply
import random
import secrets
import pandas as pd

init_db()

def generate_otp():
    return str(random.randint(100000, 999999))

st.set_page_config(page_title="argentagent", layout="wide")
st.title("argentagent")

# ---------------- SESSION STATE ----------------
if "logged_in" not in st.session_state:
    st.session_state.logged_in = False
    st.session_state.username = None

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

# NEW — oauth_state holds the random nonce we sent to Google
# so we can verify the redirect wasn't forged
if "oauth_state" not in st.session_state:
    st.session_state.oauth_state = None


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
    st.session_state.show_agent = True
    if not st.session_state.chat_history:
        st.session_state.chat_history = [
            {"role": "assistant", "content": "This transaction looks unusual. Was this you?"}
        ]


# ---------------- AUTH ----------------
def auth_page(): 
    tab1, tab2 = st.tabs(["Login", "Sign Up"])

    with tab1:
        username = st.text_input("Username")
        password = st.text_input("Password", type="password")

        if st.button("Login"):
            if login_user(username, password):
                st.session_state.logged_in = True
                st.session_state.username = username
                st.rerun()
            else:
                st.error("Invalid credentials")

        st.divider()
        st.caption("or continue with")

        if st.button("Sign in with Google", use_container_width=True):
            auth_url = get_google_auth_url("unused")
            st.markdown(
                f'<meta http-equiv="refresh" content="0; url={auth_url}">',
                unsafe_allow_html=True,
            )

    with tab2:
        new_user = st.text_input("New Username")
        new_pass = st.text_input("New Password", type="password")

        if st.button("Sign Up"):
            signup_user(new_user, new_pass)
            st.success("User created")


# ---------------- MAIN APP ----------------
def main_app():
    restore_pending_state(st.session_state.username)

    st.write(f"welcome {st.session_state.username}")

    tabs = ["Transaction", "Monitoring", "Balance"]
    tab1, tab2, tab3 = st.tabs(tabs)

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

        with st.form("transaction_form", clear_on_submit=True):
            amount = st.number_input("enter amount", min_value=0)
            submitted = st.form_submit_button("save transaction")

            if submitted:
                # Pass only username + amount — pipeline generates everything else
                result = run_pipeline({
                    "username": st.session_state.username,
                    "amount":   amount,
                })

                risk_level = result.get("risk_level", "LOW")
                action     = result.get("action", "ALLOW")

                # FIX: use the time and location the pipeline actually scored against,
                # not a separately generated pair that may differ (especially under fraud injection)
                scored_tx  = result.get("transaction", {})
                tx_time    = scored_tx.get("timestamp", "")
                tx_location = scored_tx.get("location", "")

                st.session_state.last_result = result

                # ── HIGH → auto-block, no balance deduction ─────────────
                if action == "BLOCK":
                    add_transaction(
                        st.session_state.username,
                        amount, tx_time, tx_location,
                        risk_level, "reversed", result["report"]
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
                        risk_level, "pending", result["report"]
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
                        risk_level, "approved", result["report"]
                    )
                    st.success("transaction approved.")

        # -------- TRANSACTION HISTORY --------
        if st.button("transaction history"):
            st.session_state.show_transactions = not st.session_state.get("show_transactions", False)

        if st.session_state.get("show_transactions", False):
            data = get_all_transactions(st.session_state.username)

            if data:
                table_data = []
                for row in reversed(data):
                    table_data.append({
                        "Amount":   f"₹{row[0]:,.2f}",
                        "Time":     row[1],
                        "Location": row[2],
                        "Risk":     row[3],
                        "Status":   row[4]
                    })

                df = pd.DataFrame(table_data, columns=["Amount", "Time", "Location", "Risk", "Status"])
                df["Time"] = pd.to_datetime(df["Time"], errors="coerce")
                df = df.sort_values(by="Time", ascending=False)
                df["Time"] = df["Time"].dt.strftime("%A, %d %B %Y, %I:%M %p")

                st.write("### transaction actions")

                for i, row in enumerate(data[::-1]):
                    col1, col2, col3, col4, col5, col6 = st.columns(6)

                    amount_d   = f"₹{row[0]:,.2f}"
                    time_d     = row[1]
                    location_d = row[2]
                    risk_d     = row[3]
                    status_d   = row[4]

                    style = "color:red" if risk_d in ["HIGH", "MEDIUM"] else ""

                    col1.markdown(f"<span style='{style}'>{amount_d}</span>",   unsafe_allow_html=True)
                    col2.markdown(f"<span style='{style}'>{time_d}</span>",     unsafe_allow_html=True)
                    col3.markdown(f"<span style='{style}'>{location_d}</span>", unsafe_allow_html=True)
                    col4.markdown(f"<span style='{style}'>{risk_d}</span>",     unsafe_allow_html=True)
                    col5.markdown(f"<span style='{style}'>{status_d}</span>",   unsafe_allow_html=True)

                    if col6.button("View", key=f"view_{i}"):
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
                            st.rerun()
                        else:
                            st.error("Wrong OTP. Try again.")

                with btn_col2:
                    if st.button("This wasn't me — block it"):
                        reverse_transaction(st.session_state.username, meta.get("amount", 0))
                        st.error("Transaction blocked and amount refunded.")
                        st.session_state.pending_tx      = None
                        st.session_state.pending_tx_meta = {}
                        st.session_state.awaiting_otp    = False
                        st.session_state.generated_otp   = None
                        st.session_state.show_agent      = False
                        st.session_state.chat_history    = []
                        st.rerun()

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


# ---------------- ROUTER ----------------
if st.session_state.logged_in:
    main_app()
else:
    auth_page()