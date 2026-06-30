import numpy as np
from sklearn.ensemble import IsolationForest
from datetime import datetime
from config import HOME_COUNTRY

from utils.pattern_detector import detect_amount_pattern

# ONE model per user instead of one global model
models = {}

# --------------------
# HELPERS
# --------------------
def clean_amount(a):
    try:
        return float(str(a).replace("₹", "").strip())
    except:
        return 0.0


def parse_time(t):
    if isinstance(t, str):
        try:
            return datetime.strptime(t, "%A, %d %B %Y, %I:%M %p")
        except:
            return None
    return t


# --------------------
# TRAIN MODEL
# --------------------
def train_model(history, username):
    X = []

    if not history or len(history) < 5:
        return

    for txn in history:
        amount = clean_amount(txn[0])
        timestamp = parse_time(txn[1])
        location = txn[2] if len(txn) > 2 else ""

        if not timestamp:
            continue

        location_score = 0 if "india" in str(location).lower() else 1

        X.append([amount, timestamp.hour, location_score])

    if X:
        # create or overwrite this user's personal model
        models[username] = IsolationForest(contamination=0.1, random_state=42)
        models[username].fit(X)


# --------------------
# ML ANOMALY
# --------------------
def detect_anomaly(tx, history_len: int = 0, username: str = ""):
    if history_len < 10:
        return {"anomaly_score": 0, "is_anomalous": False}

    # no model trained for this user yet
    if username not in models:
        return {"anomaly_score": 0, "is_anomalous": False}

    timestamp = parse_time(tx["timestamp"])
    if not timestamp:
        return {"anomaly_score": 0, "is_anomalous": False}

    location = tx.get("location", "")
    location_score = 0 if "india" in str(location).lower() else 1

    features = np.array([[
        clean_amount(tx["amount"]),
        timestamp.hour,
        location_score
    ]])

    try:
        score = models[username].decision_function(features)[0]
        is_anomaly = models[username].predict(features)[0] == -1
    except:
        score = 0
        is_anomaly = False

    return {
        "anomaly_score": float(score),
        "is_anomalous": bool(is_anomaly)
    }


# --------------------
# ANALYZER
# --------------------
def analyze_transaction(state):
    tx = state["transaction"]
    history = state.get("history", [])
    username = state.get("username", "")

    signals = {}

    amount = clean_amount(tx["amount"])
    timestamp = parse_time(tx["timestamp"])

    # train this user's personal model on their history
    train_model(history, username)

    # --------------------
    # AMOUNT BEHAVIOUR
    # --------------------
    if history:
        avg_amount = sum(clean_amount(h[0]) for h in history) / len(history)
        ratio = amount / avg_amount if avg_amount > 0 else 1

        if amount > 1000:
            if ratio > 15:
                signals["amount_severity"] = "very_high"
            elif ratio > 8:
                signals["amount_severity"] = "high"
            else:
                signals["amount_severity"] = "normal"
        else:
            signals["amount_severity"] = "normal"
        if amount < 500:
            signals["location_severity"] = "normal"
            signals["impossible_travel"] = False

    # --------------------
    # LOCATION
    # --------------------
    signals["is_foreign"] = HOME_COUNTRY.lower() not in str(tx["location"]).lower()

    if history:
        last = history[-1]
        last_time = parse_time(last[1])
        last_location = last[2] if len(last) > 2 else None
        current_time = timestamp

        if last_time and current_time:
            time_diff = (current_time - last_time).total_seconds() / 3600
        else:
            time_diff = 999

        if time_diff < 0:
            time_diff = 999

        if last_location and last_location != tx["location"]:
            if time_diff < 2:
                signals["impossible_travel"] = True
                signals["location_severity"] = "very_high"
            elif time_diff < 6:
                signals["location_severity"] = "very_high"
            else:
                signals["location_severity"] = "normal"
        else:
            signals["location_severity"] = "normal"

    # --------------------
    # VELOCITY
    # --------------------
    v1 = state.get("txn_last_1min", 0)
    v5 = state.get("txn_last_5min", 0)
    signals["txn_last_1min"] = v1
    signals["txn_last_5min"] = v5

    if v1 > 3 or v5 > 5:
        signals["velocity_anomaly"] = True
    else:
        signals["velocity_anomaly"] = False

    # --------------------
    # ML (per-user, suppressed for new users)
    # --------------------
    signals.update(detect_anomaly(tx, history_len=len(history), username=username))

    # --------------------
    # DIGIT PATTERN (steganographic / scripted-amount detection)
    # --------------------
    signals.update(detect_amount_pattern(amount))
    
    state["signals"] = signals
    return state