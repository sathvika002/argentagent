import psycopg2
import os
from dotenv import load_dotenv
from config import DEFAULT_BALANCE


load_dotenv()

DB_CONFIG = {
    "dbname": os.getenv("DB_NAME"),
    "user":   os.getenv("DB_USER"),
    "password": os.getenv("DB_PASSWORD", ""),
    "host":   os.getenv("DB_HOST", "localhost"),
    "port":   int(os.getenv("DB_PORT", 5432))
}

def connect():
    return psycopg2.connect(**DB_CONFIG)

def init_db():
    conn = connect()
    cur = conn.cursor()

    cur.execute(f"""
        CREATE TABLE IF NOT EXISTS users (
            username TEXT PRIMARY KEY,
            password TEXT,
            balance FLOAT DEFAULT {DEFAULT_BALANCE}
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS transactions (
            id SERIAL PRIMARY KEY,
            username TEXT,
            amount FLOAT,
            time TEXT,
            location TEXT,
            risk_level TEXT,
            status TEXT,
            report TEXT
        )
    """)

    # safe migration for older databases that might not have report column
    cur.execute("""
        ALTER TABLE transactions
        ADD COLUMN IF NOT EXISTS report TEXT
    """)

    # NEW — safe migration: adds google_id column for SSO users
    # existing rows get NULL, which means they are password-based accounts
    cur.execute("""
        ALTER TABLE users
        ADD COLUMN IF NOT EXISTS google_id TEXT DEFAULT NULL
    """)

    cur.execute("""
    ALTER TABLE users
    ADD COLUMN IF NOT EXISTS email TEXT DEFAULT NULL
    """)
    conn.commit()
    conn.close()