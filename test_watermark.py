"""
Quick verification that watermarking works end-to-end.
Run from project root:  python test_watermark.py <username>
"""
import sys
from utils.watermark import embed_watermark, verify_watermark
from utils.db import connect

def test_module(username="alice"):
    print("=== 1. Module test ===")
    sample = "Risk Score: 65 Risk Level: MEDIUM Flags: new_device, odd_hour Reason: Transaction from an unrecognised device late at night."
    watermarked = embed_watermark(sample, username)

    visible_same = watermarked.replace("​", "").replace("‌", "") == sample
    print(f"  Visible text unchanged : {visible_same}")
    print(f"  verify({username})     : {verify_watermark(watermarked, username)}")
    print(f"  verify(wrong_user)     : {verify_watermark(watermarked, 'wrong_user')}")
    print(f"  verify(plain text)     : {verify_watermark(sample, username)}")

def test_db(username):
    print("\n=== 2. Database check ===")
    conn = connect()
    cur = conn.cursor()
    cur.execute("""
        SELECT id, report FROM transactions
        WHERE username = %s AND report IS NOT NULL
        ORDER BY id DESC
        LIMIT 5
    """, (username,))
    rows = cur.fetchall()
    conn.close()

    if not rows:
        print(f"  No reports found in DB for '{username}'. Run a transaction first.")
        return

    for tx_id, report in rows:
        if report:
            result = verify_watermark(report, username)
            hidden_count = sum(1 for c in report if c in ("​", "‌"))
            print(f"  tx #{tx_id}: watermark verified={result}  (hidden chars: {hidden_count})")
        else:
            print(f"  tx #{tx_id}: no report text stored")

if __name__ == "__main__":
    username = sys.argv[1] if len(sys.argv) > 1 else "alice"
    print(f"Testing watermark for username: '{username}'\n")
    test_module(username)
    test_db(username)
