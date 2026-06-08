from utils.db import connect
import os
import requests
from urllib.parse import urlencode
import bcrypt

GOOGLE_CLIENT_ID     = os.getenv("GOOGLE_CLIENT_ID")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET")
GOOGLE_REDIRECT_URI  = os.getenv("GOOGLE_REDIRECT_URI", "http://localhost:8501/")


def signup_user(username, password, email=None):
    hashed = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt())
    conn = connect()
    cur = conn.cursor()
    try:
        cur.execute(
            "INSERT INTO users (username, password, email) VALUES (%s, %s, %s)",
            (username, hashed.decode("utf-8"), email)
        )
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        conn.close()
        return False  # username already taken


def login_user(username, password):
    conn = connect()
    cur = conn.cursor()
    cur.execute("SELECT password FROM users WHERE username=%s", (username,))
    result = cur.fetchone()
    conn.close()
    if not result or result[0] is None:
        return False
    return bcrypt.checkpw(password.encode("utf-8"), result[0].encode("utf-8"))


def verify_user_password(username, password):
    conn = connect()
    cur = conn.cursor()
    cur.execute("SELECT password FROM users WHERE username=%s", (username,))
    result = cur.fetchone()
    conn.close()
    if not result or result[0] is None:
        return False
    return bcrypt.checkpw(password.encode("utf-8"), result[0].encode("utf-8"))


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

    # 1. returning SSO user — already linked
    cur.execute("SELECT username FROM users WHERE google_id = %s", (google_id,))
    row = cur.fetchone()
    if row:
        conn.close()
        return row[0]

    # 2. email matches an existing password account — link them
    cur.execute("SELECT username FROM users WHERE email = %s", (email,))
    row = cur.fetchone()
    if row:
        cur.execute(
            "UPDATE users SET google_id = %s WHERE email = %s",
            (google_id, email)
        )
        conn.commit()
        conn.close()
        return row[0]

    # 3. brand new user — create account
    username = email.split("@")[0]
    cur.execute("SELECT username FROM users WHERE username = %s", (username,))
    if cur.fetchone():
        username = email  # fallback to full email if username taken

    cur.execute(
        "INSERT INTO users (username, password, email, google_id) VALUES (%s, %s, %s, %s)",
        (username, None, email, google_id)
    )
    conn.commit()
    conn.close()
    return username