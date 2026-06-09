from utils.db import connect


def add_transaction(username, amount, time, location, risk_level, status, report, device=None):
    # Guard: report must be a string — run_pipeline sometimes returns the full dict by mistake
    if isinstance(report, dict):
        report = report.get("report", str(report))

    conn = connect()
    cur = conn.cursor()

    cur.execute("""
        INSERT INTO transactions (username, amount, time, location, risk_level, status, report)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
    """, (username, amount, time, location, risk_level, status, report))

    # only deduct balance if not a blocked/reversed transaction
    if status not in ("reversed", "blocked"):
        cur.execute("""
            UPDATE users SET balance = balance - %s WHERE username = %s
        """, (amount, username))
    
    # Server-side amount validation — frontend min_value=0 is not enough
    if not isinstance(amount, (int, float)) or amount <= 0:
        raise ValueError("Invalid transaction amount")
    if amount > 10_000_000:
        raise ValueError("Amount exceeds maximum limit")

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
    Returns (amount, time, location, risk_level, status)
    Ordered oldest → newest.
    """
    conn = connect()
    cur = conn.cursor()

    cur.execute("""
        SELECT amount, time, location, risk_level, status
        FROM transactions
        WHERE username = %s
        ORDER BY id ASC
    """, (username,))

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