import numpy as np
from sklearn.ensemble import IsolationForest
from datetime import datetime
from config import HOME_COUNTRY

model = IsolationForest(contamination=0.1, random_state=42)

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
def train_model(history):
    X = []

    if not history or len(history) < 5:
        return

    for txn in history:
        amount = clean_amount(txn[0])
        timestamp = parse_time(txn[1])

        if not timestamp:
            continue

        X.append([amount, timestamp.hour])

    if X:
        model.fit(X)


# --------------------
# ML ANOMALY — only run if model has been trained on enough data
# --------------------
def detect_anomaly(tx, history_len: int = 0):
    """
    Returns anomaly signals.
    Suppressed entirely if history is too short for the model to be reliable.
    """
    # IsolationForest needs at least ~10 points to mean anything
    if history_len < 10:
        return {"anomaly_score": 0, "is_anomalous": False}

    timestamp = parse_time(tx["timestamp"])
    if not timestamp:
        return {"anomaly_score": 0, "is_anomalous": False}

    features = np.array([[clean_amount(tx["amount"]), timestamp.hour]])

    try:
        score = model.decision_function(features)[0]
        is_anomaly = model.predict(features)[0] == -1
    except:
        score = 0
        is_anomaly = False

    return {
        "anomaly_score": float(score),
        "is_anomalous": bool(is_anomaly)
    }


# --------------------
# ANALYZER (ONLY SIGNALS)
# --------------------
def analyze_transaction(state):
    tx = state["transaction"]
    history = state.get("history", [])

    signals = {}

    amount = clean_amount(tx["amount"])
    timestamp = parse_time(tx["timestamp"])

    # --------------------
    # AMOUNT BEHAVIOUR
    # --------------------
    if history:
        avg_amount = sum(clean_amount(h[0]) for h in history) / len(history)
        ratio = amount / avg_amount if avg_amount > 0 else 1

        if amount > 1000:  # only care if actually significant money
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

        # Negative time_diff means the simulated clock went backwards
        # (server restart resets time_utils.last_time). Treat as unknown gap.
        if time_diff < 0:
            time_diff = 999

        if last_location and last_location != tx["location"]:
            # FIXED: only flag impossible_travel if < 2 hours (was < 6)
            # A 2-hour gap between cities is genuinely suspicious
            if time_diff < 2:
                signals["impossible_travel"] = True
                signals["location_severity"] = "very_high"
            elif time_diff < 6:
                # Suspicious but plausible (short flight, fast travel)
                # Don't treat the same as an impossible jump
                signals["location_severity"] = "very_high"
            else:
                # Plenty of time to have travelled — not suspicious
                # FIXED: was always "very_high" for ANY location change
                signals["location_severity"] = "normal"
        else:
            signals["location_severity"] = "normal"

    # --------------------
    # VELOCITY
    # --------------------
    signals["txn_last_1min"] = state.get("txn_last_1min", 0)
    signals["txn_last_5min"] = state.get("txn_last_5min", 0)

    # --------------------
    # ML (suppressed for new users)
    # --------------------
    signals.update(detect_anomaly(tx, history_len=len(history)))

    state["signals"] = signals
    return state