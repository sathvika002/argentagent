"""
Watermark verification tool.
Run from project root:  python test_watermark.py <username>
"""
import sys
from utils.watermark import embed_watermark, verify_watermark, _BIT_0, _BIT_1
from utils.db import connect


def _hidden_char_count(text):
    return sum(1 for c in text if c in (_BIT_0, _BIT_1))


def test_module(username):
    print("=== 1. Module test (no DB needed) ===")
    sample = "Risk Score: 65 Risk Level: MEDIUM Flags: new_device, odd_hour Reason: Transaction from an unrecognised device late at night."
    watermarked = embed_watermark(sample, username)

    visible_same = watermarked.replace(_BIT_0, "").replace(_BIT_1, "") == sample
    print(f"  Visible text unchanged : {visible_same}")
    print(f"  Hidden chars embedded  : {_hidden_char_count(watermarked)}")
    print(f"  verify({username!r})  : {verify_watermark(watermarked, username)}")
    print(f"  verify('wrong_user')  : {verify_watermark(watermarked, 'wrong_user')}")
    print(f"  verify(plain text)    : {verify_watermark(sample, username)}")


def test_latest(username):
    print("\n=== 2. Latest VERIFY report from DB ===")
    conn = connect()
    cur = conn.cursor()

    # Most recent LLM-generated report for this user (VERIFY path only)
    cur.execute("""
        SELECT id, report, status, risk_level
        FROM transactions
        WHERE username = %s
          AND report IS NOT NULL
          AND report NOT LIKE 'Transaction blocked%%'
          AND report NOT LIKE 'DECLINED%%'
          AND report NOT LIKE 'Salary%%'
          AND report NOT LIKE 'Report generation failed%%'
        ORDER BY id DESC
        LIMIT 1
    """, (username,))
    row = cur.fetchone()
    conn.close()

    if not row:
        print(f"  No VERIFY-path reports found for '{username}'.")
        print("  Make a transaction that lands on the VERIFY path (medium risk),")
        print("  then run this script again.")
        return

    tx_id, report, status, risk_level = row
    hidden = _hidden_char_count(report)
    verified = verify_watermark(report, username)

    print(f"  tx #{tx_id}  |  status={status}  risk={risk_level}")
    print(f"  Hidden chars  : {hidden}")
    print(f"  Verified      : {verified}")
    if not verified and hidden == 0:
        print("  >> This report has no watermark — it was generated before the fix.")
        print("  >> Make a fresh transaction and run this script again.")


def test_all(username):
    print("\n=== 3. Recent VERIFY reports (last 5) ===")
    conn = connect()
    cur = conn.cursor()
    cur.execute("""
        SELECT id, LEFT(report, 50), status, risk_level
        FROM transactions
        WHERE username = %s AND report IS NOT NULL
        ORDER BY id DESC
        LIMIT 5
    """, (username,))
    rows = cur.fetchall()
    conn.close()

    for tx_id, snippet, status, risk_level in rows:
        print(f"  tx #{tx_id}  [{risk_level}/{status}]  preview: {snippet!r}")


if __name__ == "__main__":
    username = sys.argv[1] if len(sys.argv) > 1 else "alice"
    print(f"Watermark check for username: '{username}'\n")
    test_module(username)
    test_latest(username)
    test_all(username)
