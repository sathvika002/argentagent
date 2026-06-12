from utils.db import connect
from datetime import datetime


def check_available_balance(username: str) -> float:
    """
    Returns the available balance for a user.
    Available Balance = Total Balance - Holds (authorization holds)
    """
    conn = connect()
    cur = conn.cursor()
    
    cur.execute("SELECT balance FROM users WHERE username = %s", (username,))
    result = cur.fetchone()
    balance = result[0] if result else 0
    
    conn.close()
    return balance


def add_transaction(username, amount, time, location, risk_level, status, report, device=None, transaction_type="DEBIT"):
    """
    Add a transaction to the database.
    
    Args:
        transaction_type: "DEBIT" for outgoing, "CREDIT" for incoming
        status: "approved", "pending", "reversed", "blocked", "declined"
    """
    # Guard: report must be a string — run_pipeline sometimes returns the full dict by mistake
    if isinstance(report, dict):
        report = report.get("report", str(report))

    # Server-side amount validation — frontend min_value=0 is not enough
    if not isinstance(amount, (int, float)) or amount <= 0:
        raise ValueError("Invalid transaction amount")
    if amount > 10_000_000:
        raise ValueError("Amount exceeds maximum limit")

    conn = connect()
    cur = conn.cursor()

    try:
        # Try insert with transaction_type column
        cur.execute("""
            INSERT INTO transactions (username, amount, time, location, risk_level, status, report, transaction_type)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        """, (username, amount, time, location, risk_level, status, report, transaction_type))
    except Exception as e:
        # Fallback if transaction_type column doesn't exist yet (migration not run)
        if "transaction_type" in str(e):
            cur.execute("""
                INSERT INTO transactions (username, amount, time, location, risk_level, status, report)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
            """, (username, amount, time, location, risk_level, status, report))
        else:
            raise

    # Update balance based on transaction type and status:
    # DEBIT: subtract if approved/pending (not if blocked/declined/reversed)
    # CREDIT: always add
    if transaction_type == "CREDIT":
        # Credits always add
        cur.execute("""
            UPDATE users SET balance = balance + %s WHERE username = %s
        """, (amount, username))
    elif transaction_type == "DEBIT":
        # Debits only deduct if approved or pending (not if blocked/reversed/declined)
        if status not in ("reversed", "blocked", "declined"):
            cur.execute("""
                UPDATE users SET balance = balance - %s WHERE username = %s
            """, (amount, username))

    conn.commit()
    conn.close()


def update_transaction_status(tx_id, status):
    conn = connect()
    cur = conn.cursor()

    cur.execute("""
        UPDATE transactions SET status = %s WHERE id = %s
    """, (status, tx_id))

    conn.commit()
    conn.close()


def get_all_transactions(username):
    """
    Returns (id, amount, time, location, risk_level, status, transaction_type)
    Ordered by ID (newest transaction = highest ID = on top).
    """
    conn = connect()
    cur = conn.cursor()

    try:
        # Try with transaction_type column (new schema)
        cur.execute("""
            SELECT id, amount, time, location, risk_level, status, COALESCE(transaction_type, 'DEBIT')
            FROM transactions
            WHERE username = %s
            ORDER BY id DESC
        """, (username,))
    except Exception as e:
        # Fallback if transaction_type column doesn't exist yet
        if "transaction_type" in str(e):
            cur.execute("""
                SELECT id, amount, time, location, risk_level, status, 'DEBIT'
                FROM transactions
                WHERE username = %s
                ORDER BY id DESC
            """, (username,))
        else:
            raise

    data = cur.fetchall()
    conn.close()
    
    return data


def reverse_transaction(username: str, amount: float):
    """
    Marks the most recent pending transaction as reversed AND refunds the balance.

    FIX 1: Previously didn't update the DB status, leaving transactions stuck as 'pending'.
    FIX 2: Uses a subquery so PostgreSQL doesn't complain about LIMIT in UPDATE.
    """
    conn = connect()
    cur = conn.cursor()

    # Mark the most recent pending tx as reversed
    cur.execute("""
        UPDATE transactions SET status = 'reversed'
        WHERE id = (
            SELECT id FROM transactions
            WHERE username = %s AND status = 'pending'
            ORDER BY id DESC
            LIMIT 1
        )
    """, (username,))

    # Refund balance — only if there's actually an amount to refund
    if amount and amount > 0:
        cur.execute("""
            UPDATE users SET balance = balance + %s WHERE username = %s
        """, (amount, username))

    conn.commit()
    conn.close()


def get_pending_transaction(username: str):
    """
    Returns the most recent pending transaction for this user, or None.
    Used to restore session state after a page refresh.
    Returns (id, amount, time, location, risk_level, report)
    """
    conn = connect()
    cur = conn.cursor()

    cur.execute("""
        SELECT id, amount, time, location, risk_level, report
        FROM transactions
        WHERE username = %s AND status = 'pending'
        ORDER BY id DESC
        LIMIT 1
    """, (username,))

    row = cur.fetchone()
    conn.close()
    return row


def get_user_balance(username):
    conn = connect()
    cur = conn.cursor()

    cur.execute(
        "SELECT balance FROM users WHERE username = %s",
        (username,)
    )

    result = cur.fetchone()
    conn.close()
    return result[0] if result else 0


def generate_salary_credit(username: str, time: str, amount: float = 80000):
    """
    Simulate a salary deposit.
    Real banks receive salaries regularly (monthly, bi-weekly, etc.)
    """
    add_transaction(
        username=username,
        amount=amount,
        time=time,
        location="Salary Deposit",
        risk_level="LOW",
        status="approved",
        report="Salary credit received",
        transaction_type="CREDIT"
    )


def generate_refund_credit(username: str, time: str, amount: float):
    """
    Simulate a refund from a merchant (e.g., Amazon, canceled subscription).
    """
    add_transaction(
        username=username,
        amount=amount,
        time=time,
        location="Refund",
        risk_level="LOW",
        status="approved",
        report="Refund credit received",
        transaction_type="CREDIT"
    )


def generate_transfer_credit(username: str, time: str, amount: float, source: str = "Bank Transfer"):
    """
    Simulate an incoming transfer from another account (friend, family, NEFT).
    """
    add_transaction(
        username=username,
        amount=amount,
        time=time,
        location=source,
        risk_level="LOW",
        status="approved",
        report=f"Transfer received from {source}",
        transaction_type="CREDIT"
    )