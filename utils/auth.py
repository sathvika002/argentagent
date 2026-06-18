from utils.db import connect
import os
import requests
import bcrypt
from urllib.parse import urlencode

GOOGLE_CLIENT_ID     = os.getenv("GOOGLE_CLIENT_ID")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET")
GOOGLE_REDIRECT_URI  = os.getenv("GOOGLE_REDIRECT_URI", "http://localhost:8501/")

MAX_ATTEMPTS = 5


def signup_user(username, password):
    conn = connect()
    cur = conn.cursor()
    try:
        hashed = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
        cur.execute(
            "INSERT INTO users (username, password) VALUES (%s, %s)",
            (username, hashed)
        )
        conn.commit()
    except:
        pass
    conn.close()


def login_user(username, password):
    conn = connect()
    cur = conn.cursor()

    # First, clear expired locks (if locked_until has passed)
    cur.execute(
        """UPDATE users 
           SET locked_until = NULL, failed_attempts = 0 
           WHERE username = %s AND locked_until IS NOT NULL AND locked_until <= NOW()""",
        (username,)
    )
    conn.commit()

    # Lock check — done entirely in Postgres, no Python datetime involved
    cur.execute(
        "SELECT (locked_until IS NOT NULL AND locked_until > NOW()) FROM users WHERE username=%s",
        (username,)
    )
    row = cur.fetchone()

    if row is None:
        conn.close()
        return False  # username doesn't exist

    if row and row[0]:
        conn.close()
        return "LOCKED"

    # Get the stored password
    cur.execute("SELECT password FROM users WHERE username=%s", (username,))
    result = cur.fetchone()
    stored_hash = result[0]

    try:
        is_valid = bcrypt.checkpw(password.encode(), stored_hash.encode())
    except Exception:
        is_valid = (password == stored_hash)

    if is_valid:
        cur.execute(
            "UPDATE users SET failed_attempts = 0, locked_until = NULL WHERE username=%s",
            (username,)
        )
        conn.commit()
        conn.close()
        return True
    else:
        cur.execute(
            """
            UPDATE users
            SET failed_attempts = failed_attempts + 1,
                locked_until = CASE
                    WHEN failed_attempts + 1 >= %s THEN NOW() + INTERVAL '15 minutes'
                    ELSE NULL
                END
            WHERE username=%s
            RETURNING failed_attempts
            """,
            (MAX_ATTEMPTS, username)
        )
        new_count = cur.fetchone()[0]
        conn.commit()
        conn.close()
        return "LOCKED" if new_count >= MAX_ATTEMPTS else False


def verify_user_password(username, password):
    conn = connect()
    cur = conn.cursor()
    cur.execute("SELECT password FROM users WHERE username=%s", (username,))
    result = cur.fetchone()
    conn.close()
    if not result:
        return False
    stored = result[0]
    try:
        return bcrypt.checkpw(password.encode(), stored.encode())
    except Exception:
        return stored == password


def reset_password(username, new_password):
    """Reset user password and unlock account"""
    conn = connect()
    cur = conn.cursor()
    try:
        hashed = bcrypt.hashpw(new_password.encode(), bcrypt.gensalt()).decode()
        cur.execute(
            """UPDATE users 
               SET password = %s, failed_attempts = 0, locked_until = NULL 
               WHERE username = %s""",
            (hashed, username)
        )
        conn.commit()
        rows = cur.rowcount
        conn.close()
        return rows > 0
    except:
        conn.close()
        return False


def get_google_auth_url(state: str) -> str:
    params = {
        "client_id":     GOOGLE_CLIENT_ID,
        "redirect_uri":  GOOGLE_REDIRECT_URI,
        "response_type": "code",
        "scope":         "openid email profile",
        "state":         state,
        "access_type":   "online",
    }
    return "https://accounts.google.com/o/oauth2/v2/auth?" + urlencode(params)


def exchange_code_for_user(code: str) -> dict | None:
    token_resp = requests.post(
        "https://oauth2.googleapis.com/token",
        data={
            "code":          code,
            "client_id":     GOOGLE_CLIENT_ID,
            "client_secret": GOOGLE_CLIENT_SECRET,
            "redirect_uri":  GOOGLE_REDIRECT_URI,
            "grant_type":    "authorization_code",
        },
        timeout=10,
    )
    if not token_resp.ok:
        return None
    access_token = token_resp.json().get("access_token")
    if not access_token:
        return None
    userinfo_resp = requests.get(
        "https://www.googleapis.com/oauth2/v3/userinfo",
        headers={"Authorization": f"Bearer {access_token}"},
        timeout=10,
    )
    return userinfo_resp.json() if userinfo_resp.ok else None


def login_or_create_sso_user(google_id: str, email: str, name: str) -> str:
    conn = connect()
    cur  = conn.cursor()
    cur.execute("SELECT username FROM users WHERE google_id = %s", (google_id,))
    row = cur.fetchone()
    if row:
        conn.close()
        return row[0]
    username = email.split("@")[0]
    cur.execute("SELECT username FROM users WHERE username = %s", (username,))
    if cur.fetchone():
        username = email
    cur.execute(
        "INSERT INTO users (username, password, google_id) VALUES (%s, %s, %s)",
        (username, None, google_id)
    )
    conn.commit()
    conn.close()
    return username