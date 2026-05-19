ArgentAgent – AI-Powered Transaction Risk Analysis System

Overview

ArgentAgent is a prototype AI-driven transaction monitoring and risk scoring system designed to simulate real-world fraud detection workflows. The goal of this project is to build a modular, experiment-friendly platform where intelligent agents analyze user transactions based on behavioral patterns such as time, location, and transaction amount, and then assign a risk score with actionable insights.

This project is intentionally built in a simple, extensible way, so you can continuously improve it by plugging in better algorithms, models, and security strategies as your understanding deepens.

Core Idea

ArgentAgent simulates a financial system with:

User authentication (login/signup)
Transaction execution
Behavioral monitoring (time + location)
AI-based risk analysis
Automated response (OTP / rollback simulation)

It uses AI agents to:

Analyze transaction behavior
Score risk
Report findings and suggest next steps
Features
1. User Authentication
New users can sign up
Existing users can log in
Credentials are stored in a local database
2. Transaction Simulation (Tab 1)
Users initiate transactions
Transaction includes:
Amount
Timestamp (from device)
Location (simulated or device-based)
Stored in a transaction database
3. Monitoring & Verification (Tab 2)
Tracks:
Time patterns
Location patterns
Transaction history
Detects anomalies such as:
Unusual transaction time
New/unexpected location
Abnormal transaction amount
4. Risk Scoring System

A core component that:

Performs basic threat modeling internally
Assigns a risk score
Classifies risk as:
Low
Medium
High
Example Logic (initial version)
New location → +30 risk
Unusual time → +20 risk
Large amount deviation → +40 risk
5. AI Agent System

Agents communicate using a structured workflow (Crew-style):

a. Analyzer Agent
Observes transaction data
Identifies anomalies
b. Risk Scorer Agent
Applies risk scoring logic
Performs internal threat modeling
Outputs risk score + classification
c. Reporter Agent
Generates human-readable explanation
Suggests next steps:
Approve
Flag
Trigger OTP
6. Security Actions
OTP Simulation
Triggered when risk exceeds threshold
Simulated notification (no real SMS)
Fraud Response (Tab 3)
Simulates account balance
If high-risk fraud detected:
Transaction is reversed
Funds returned to original account
7. Experimentation-Friendly Design

This project is intentionally flexible so you can:

Swap risk scoring algorithms
Add ML models later
Integrate real APIs (location, OTP, etc.)
Improve anomaly detection logic
Expand threat modeling depth
Tech Stack
Frontend/UI: Streamlit
Backend Logic: Python
AI Frameworks:
LangChain
LangGraph
CrewAI
LLM Provider: OpenAI
Database: SQLite (initial version)


Likelihood (suspicion level)
Factor	Meaning
velocity anomaly	very high suspicion
foreign location	medium suspicion
unusual time	low-medium
Impact (damage potential)
Factor	Meaning
amount	biggest driver
account pattern	optional future


Chargeback Logic:

User makes transaction
        ↓
Risk Scorer
        ↓
If risky → flag
        ↓
Transactions Tab → "Monitor this"
        ↓
User goes to Monitoring Tab
        ↓
PIN verification
        ↓
Shows explanation
        ↓
User decision
   ↓           ↓
 YES         NO
 ↓            ↓
Confirm     Reverse (simulate)
 ↓            ↓
Update DB   Update balance