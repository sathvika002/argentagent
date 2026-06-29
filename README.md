VIEW IN CODE CODE 



ArgentAgent — AI-Powered Transaction Risk Analysis System

A prototype fraud detection system that combines rule-based risk scoring, unsupervised anomaly detection, and a conversational GPT-4o-mini verification agent into a single modular pipeline. Built with Streamlit and PostgreSQL.

How It Works:

Every transaction runs through a LangGraph state pipeline with five stages:
Transaction Input
      ↓
Load Context       ← fetch last 50 transactions + user profile from DB
      ↓
Enrich             ← generate timestamp, location, device, apply fraud injection
      ↓
Analyze            ← compute signals (amount deviation, location, velocity, ML anomaly)
      ↓
Score              ← aggregate signals into composite risk score
      ↓
   ┌──┴──────────┐
Score ≥ 70     Score 40–69     Score < 40
   ↓               ↓               ↓
 BLOCK           VERIFY          ALLOW
(auto-block)   (OTP + agent)   (auto-approve)

Risk Scoring:

The scorer aggregates six independent signal categories into a composite score. Each category contributes independently — no stacking between dominant signals.
SignalScore AddedImpossible travel (location jump < 2 hrs)+60Foreign transaction, high value (> ₹10,000)+40Large amount (> ₹50,000)+40High velocity — 5 transactions in 5 min+40Past fraud history on account+35High velocity — 3 transactions in 1 min+25Foreign transaction, medium value (> ₹1,000)+30Frequent chargebacks (> 2)+25Off-hours transaction (1–6 AM)+20ML anomaly (Isolation Forest)+15Amount spike (> 15× user average)+15Late-night transaction (past 11:30 PM)+10
Thresholds (configurable in config.py):

≥ 70 → BLOCK — transaction auto-rejected, balance not charged
40–69 → VERIFY — routed to conversational agent + OTP
< 40 → ALLOW — transaction approved automatically


Features
User Authentication

Username/password signup and login:
Google OAuth SSO (returns users matched by google_id, new users created from email prefix)
Credentials stored in PostgreSQL

Transaction Pipeline:

User enters an amount; the pipeline generates timestamp, location, and device
Timestamp — Gaussian distribution centred at 2 PM (std = 3), clamped to 08:00–23:59 for normal transactions; forced to 1–6 AM when fraud is injected
Location — tiered probability: 70% home city (Bangalore), 15% nearby, 8% distant Indian city, 7% international
Device — drawn from a per-user pool of 2 trusted devices; 12% chance of a new/unknown device

Anomaly Detection (Isolation Forest):

Trained on each user's historical transaction amounts and hours
Suppressed entirely for users with fewer than 10 transactions — prevents unreliable signals on new accounts
Contributes +15 to risk score when anomaly score drops below −0.1

Conversational Verification Agent:

Triggered for MEDIUM-risk transactions (score 40–69)
GPT-4o-mini with structured JSON output (reply + intent)
Classifies user response as YES (confirmed) → sends OTP, NO (disputed) → reverses transaction, UNCLEAR → asks follow-up
Temperature set to 0.3 for consistent, predictable behaviour in a security context
Full conversation history sent on every API call (LLMs are stateless)


OTP Flow:

6-digit OTP generated server-side on YES intent
Displayed in an in-UI expander (prototype — no real SMS delivery)
Correct OTP → transaction status updated to approved
Wrong OTP or "this wasn't me" → transaction reversed, balance refunded

Chargeback / Reversal
User disputes transaction via agent
            ↓
reverse_transaction() called
            ↓
Most recent 'pending' tx → status = 'reversed'
            ↓
Balance refunded: UPDATE users SET balance = balance + amount
Fraud Injection (Development / Testing)
A configurable injection rate (FRAUD_INJECTION_RATE in run_pipeline.py) deliberately corrupts a proportion of transactions with high-risk signals — international location, off-hours timestamp (1–6 AM), and amount spiked 5–10× the user's average. This allows the pipeline to be tested against meaningful fraud scenarios without a live dataset. Set to 0.0 by default (disabled).
Report Generation
A second GPT-4o-mini call generates a short structured report for each VERIFY-path transaction, summarising the risk score, per-category breakdown, and primary risk factor. Stored in the database alongside the transaction record.

Project Structure:

argentagent/
├── app.py                  # Streamlit UI — auth, tabs, session state
├── config.py               # Thresholds, constants, env config
├── requirements.txt
│
├── pipeline/
│   ├── run_pipeline.py     # LangGraph state graph — entry point
│   └── state.py            # TransactionState TypedDict
│
├── agents/
│   ├── analyzer.py         # Signal generation + Isolation Forest
│   ├── risk_scorer.py      # Composite score + risk level
│   ├── reporter.py         # GPT-4o-mini report generation
│   └── agent.py            # Conversational fraud verification agent
│
└── utils/
    ├── db.py               # PostgreSQL connection + schema init
    ├── auth.py             # Login, signup, Google OAuth
    ├── transactions.py     # DB read/write for transactions + balance
    ├── location.py         # Tiered location pool + coordinates
    └── time_utils.py       # Gaussian timestamp generation

Tech Stack

Layer.                          Technology
Frontend                     Streamlit
Backend                      Python 3
Pipeline orchestration       LangGraph (StateGraph)
Database                     PostgreSQL + psycopg2
Anomaly detection            scikit-learn — Isolation Forest
Conversational agent.        OpenAI API — GPT-4o-mini
Report generation            OpenAI API — GPT-4o-mini
Auth                         Password-based + Google OAuth 2.0
Data                         pandas, numpy
Config                       python-dotenv

Setup
1. Clone and install
bashgit clone https://github.com/sathvika002/argentagent.git
cd argentagent
pip install -r requirements.txt
2. Create a .env file in the project root:
envOPENAI_API_KEY=your_openai_key_here

# Optional — only needed for Google SSO
GOOGLE_CLIENT_ID=your_google_client_id
GOOGLE_CLIENT_SECRET=your_google_client_secret
GOOGLE_REDIRECT_URI=http://localhost:8501/
3. Set up PostgreSQL
Create a database named argentagent and a user named sathvika (or update the credentials in utils/db.py):
sqlCREATE DATABASE argentagent;
CREATE USER sathvika WITH PASSWORD '';
GRANT ALL PRIVILEGES ON DATABASE argentagent TO sathvika;
The schema (users + transactions tables) is created automatically on first run via init_db().
4. Run
bashstreamlit run app.py

Configuration
All thresholds are in config.py and can be changed without touching pipeline logic:
pythonRISK_BLOCK_THRESHOLD   = 70      # score >= this → auto-block
RISK_VERIFY_THRESHOLD  = 40      # score >= this → verification
LARGE_AMOUNT_THRESHOLD = 50000   # ₹ — triggers +40 to score
BUSINESS_HOUR_START    = 8       # used for time risk classification
BUSINESS_HOUR_END      = 23
DEFAULT_BALANCE        = 500000  # ₹ — starting balance for new users
To enable fraud injection for testing:
python# pipeline/run_pipeline.py
FRAUD_INJECTION_RATE = 0.15   # 15% of transactions get injected signals
