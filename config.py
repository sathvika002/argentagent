from dotenv import load_dotenv
import os

load_dotenv()

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

# Risk thresholds
RISK_BLOCK_THRESHOLD = 70
RISK_VERIFY_THRESHOLD = 40

# Amount threshold
LARGE_AMOUNT_THRESHOLD = 50000

# Time window (clean + consistent)
BUSINESS_HOUR_START = 8
BUSINESS_HOUR_END = 23

# Location normalization
HOME_CITY = "bengaluru"
HOME_COUNTRY = "india"

# Default balance
DEFAULT_BALANCE = 500000

# NEW — Google OAuth credentials (set these in your .env file)
GOOGLE_CLIENT_ID     = os.getenv("GOOGLE_CLIENT_ID")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET")
GOOGLE_REDIRECT_URI  = os.getenv("GOOGLE_REDIRECT_URI", "http://localhost:8501/")