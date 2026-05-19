from utils.db import connect
import os
import requests
from urllib.parse import urlencode

# ── Google OAuth config (loaded from .env) ────────────────────────────────────
GOOGLE_CLIENT_ID     = os.getenv("GOOGLE_CLIENT_ID")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET")
GOOGLE_REDIRECT_URI  = os.getenv("GOOGLE_REDIRECT_URI", "http://localhost:8501/")


# ─────────────────────────────────────────────────────────────────
# ORIGINAL FUNCTIONS — completely unchanged
# ─────────────────────────────────────────────────────────────────

def signup_user(username, password):
    conn = connect()
    cur = conn.cursor()

    try:
        cur.execute(
            "INSERT INTO users (username, password) VALUES (%s, %s)",
            (username, password)
        )
        conn.commit()
    except:
        pass

    conn.close()


def login_user(username, password):
    conn = connect()
    cur = conn.cursor()

    cur.execute(
        "SELECT * FROM users WHERE username=%s AND password=%s",
        (username, password)
    )

    result = cur.fetchone()
    conn.close()

    return result is not None


def verify_user_password(username, password):
    conn = connect()
    cur = conn.cursor()

    cur.execute(
        "SELECT password FROM users WHERE username=%s",
        (username,)
    )

    result = cur.fetchone()
    conn.close()

    return result and result[0] == password


# ─────────────────────────────────────────────────────────────────
# NEW — Google SSO (three functions, does not touch anything above)
# ─────────────────────────────────────────────────────────────────

def get_google_auth_url(state: str) -> str:
    """
    Builds the Google authorization URL the user's browser gets sent to.
    `state` is a random nonce we generated — Google echoes it back so we can
    confirm the redirect wasn't forged (CSRF protection).
    """
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
    print("DEBUG: redirect_uri being sent:", GOOGLE_REDIRECT_URI)
    """
    Server-side only: exchanges the one-time code Google gave us for an
    access token, then calls Google's UserInfo endpoint to get the profile.
    Returns {"sub", "email", "name", ...} or None if anything fails.
    """
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
    """
    Finds or creates a DB row for a Google account.
    - Known google_id → return that username (returning user).
    - Unknown → insert a new user with no password (SSO-only account).
    Username is the email prefix ("sathvika" from "sathvika@gmail.com").
    Falls back to the full email if that prefix is already taken by a
    different password-based account.
    """
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