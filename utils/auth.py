from utils.db import connect
import os
import requests
import bcrypt
from datetime import datetime, timedelta
from urllib.parse import urlencode

GOOGLE_CLIENT_ID     = os.getenv("GOOGLE_CLIENT_ID")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET")
GOOGLE_REDIRECT_URI  = os.getenv("GOOGLE_REDIRECT_URI", "http://localhost:8501/")

MAX_ATTEMPTS = 5
LOCKOUT_MINUTES = 15


def signup_user(username, password):
    conn = connect()
    cur = conn.cursor()
    try:
        hashed = bcrypt.hashpw(
            password.encode(), bcrypt.gensalt()
        ).decode()
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

    # Check if account is locked — comparison done in Postgres, avoids timezone bugs
    cur.execute(
        "SELECT (locked_until IS NOT NULL AND locked_until > NOW()) FROM users WHERE username=%s",
        (username,)
    )
    row = cur.fetchone()

    if row and row[0]:
        conn.close()
        return "LOCKED"

    # Check password
    cur.execute(
        "SELECT password FROM users WHERE username=%s",
        (username,)
    )
    result = cur.fetchone()

    if not result:
        conn.close()
        return False

    stored_hash = result[0]

    # Handle both bcrypt hashes and legacy plaintext passwords
    try:
        is_valid = bcrypt.checkpw(password.encode(), stored_hash.encode())
    except Exception:
        is_valid = (password == stored_hash)

    if is_valid:
        # Correct password — reset the counter and clear any lock
        cur.execute(
            "UPDATE users SET failed_attempts = 0, locked_until = NULL WHERE username=%s",
            (username,)
        )
        conn.commit()
        conn.close()
        return True
    else:
        # Wrong password — increment attempts, lock if threshold reached
        cur.execute(
            """
            UPDATE users 
            SET failed_attempts = failed_attempts + 1,
                locked_until = CASE 
                    WHEN failed_attempts + 1 >= %s 
                    THEN NOW() + INTERVAL '15 minutes'
                    ELSE NULL 
                END
            WHERE username=%s
            """,
            (MAX_ATTEMPTS, username)
        )
        conn.commit()

        cur.execute(
            "SELECT failed_attempts FROM users WHERE username=%s",
            (username,)
        )
        attempts = cur.fetchone()[0]
        conn.close()

        if attempts >= MAX_ATTEMPTS:
            return "LOCKED"
        return False


def verify_user_password(username, password):
    conn = connect()
    cur = conn.cursor()
    cur.execute(
        "SELECT password FROM users WHERE username=%s",
        (username,)
    )
    result = cur.fetchone()
    conn.close()
    if not result:
        return False
    stored = result[0]
    try:
        return bcrypt.checkpw(password.encode(), stored.encode())
    except Exception:
        return stored == password


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