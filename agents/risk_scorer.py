from datetime import datetime
from config import (
    RISK_BLOCK_THRESHOLD,
    RISK_VERIFY_THRESHOLD,
    LARGE_AMOUNT_THRESHOLD,
    BUSINESS_HOUR_START,
    BUSINESS_HOUR_END
)

# --------------------
# TIME CHECK
# --------------------
def get_time_risk_level(timestamp):
    if isinstance(timestamp, str):
        timestamp = datetime.strptime(
            timestamp,
            "%A, %d %B %Y, %I:%M %p"
        )

    hour = timestamp.hour
    minute = timestamp.minute

    # Convert everything to minutes for precision (since you have 11:30)
    total_minutes = hour * 60 + minute

    start = 7 * 60              # 7:00 AM
    end = 23 * 60 + 30         # 11:30 PM
    late_night = 2 * 60        # 2:00 AM
    early_morning = 6 * 60     # 6:00 AM

    if start <= total_minutes <= end:
        return "normal"
    elif total_minutes <= late_night or total_minutes >= end:
        return "medium"   # late night
    elif late_night < total_minutes < early_morning:
        return "high"     # deep night
    else:
        return "medium"


# --------------------
# SCORER
# --------------------
def score_risk(transaction, user_profile, signals):

    flags = []
    breakdown = {
        "transaction": 0,
        "velocity": 0,
        "location": 0,
        "history": 0,
        "time": 0,
        "ml_anomaly": 0
    }

    amount = transaction["amount"]

    # --------------------
    # AMOUNT
    # --------------------
    if amount > LARGE_AMOUNT_THRESHOLD:
        breakdown["transaction"] += 40


    # --------------------
    # LOCATION (controlled, non-stacking)
    # --------------------
    location_score = 0
    location_flag = None

    # strongest signal first
    if signals.get("impossible_travel"):
        location_score = 60
        location_flag = "impossible_travel"

    elif signals.get("is_foreign"):
        # Foreign location is suspicious regardless of amount.
        # Amount only affects whether we push harder toward BLOCK.
        if amount > 10000:
            location_score = 40
            location_flag = "foreign_high_value"
        elif amount > 1000:
            location_score = 30
            location_flag = "foreign_medium_value"
        else:
            location_score = 25
            location_flag = "foreign_low_value"

    elif signals.get("location_severity") == "very_high":
        location_score = 20 if amount > 1000 else 5
        location_flag = "location_jump"

    # velocity bonus (small, not dominant)
    if signals.get("is_foreign") and signals.get("txn_last_5min", 0) > 3:
        location_score += 10
        location_flag = "foreign_velocity"

    # apply once
    breakdown["location"] += location_score
    if location_flag:
        flags.append(location_flag)
    # --------------------
    # VELOCITY
    # --------------------
    if signals.get("txn_last_1min", 0) > 3:
        breakdown["velocity"] += 25
        flags.append("high_velocity_1min")

    if signals.get("txn_last_5min", 0) > 5:
        breakdown["velocity"] += 40
        flags.append("high_velocity_5min")

    # --------------------
    # HISTORY
    # --------------------
    if user_profile.get("past_fraud"):
        breakdown["history"] += 35
        flags.append("past_fraud")

    if user_profile.get("chargebacks", 0) > 2:
        breakdown["history"] += 25
        flags.append("frequent_chargebacks")

    # --------------------
    # TIME
    # --------------------
    time_risk = get_time_risk_level(transaction["timestamp"])

    if time_risk == "medium":
        breakdown["time"] += 10
        flags.append("late_night_txn")

    elif time_risk == "high":
        breakdown["time"] += 20
        flags.append("odd_hour_txn")

    # --------------------
    # ML ANOMALY
    # --------------------
    if signals.get("is_anomalous") and signals.get("anomaly_score", 0) < -0.1:
        breakdown["ml_anomaly"] += 15
        flags.append("anomaly_detected")

    # --------------------
    # AMOUNT BEHAVIOUR
    # --------------------
    if signals.get("amount_severity") == "very_high":
        breakdown["transaction"] += 15
        flags.append("amount_spike")

    elif signals.get("amount_severity") == "high":
        breakdown["transaction"] += 8
        flags.append("amount_elevated")

    # --------------------
    # DIGIT PATTERN
    # --------------------
    if signals.get("amount_pattern_flag"):
        pattern_type = signals.get("amount_pattern_type")
        if pattern_type == "sequential_digits":
            breakdown["transaction"] += 12
            flags.append("sequential_amount_pattern")
        elif pattern_type == "repeating_digits":
            breakdown["transaction"] += 10
            flags.append("repeating_amount_pattern")
        elif pattern_type == "round_number":
            breakdown["transaction"] += 4
            flags.append("round_amount_pattern")

    # --------------------
    # PREVENT OVERSTACKING
    # --------------------
    if breakdown["transaction"] < 20:
        if breakdown["time"] > 0 and breakdown["location"] > 0:
            breakdown["time"] = 0

    # --------------------
    # FINAL SCORE
    # --------------------
    score = sum(breakdown.values())

    if score >= RISK_BLOCK_THRESHOLD:
        level = "HIGH"
    elif score >= RISK_VERIFY_THRESHOLD:
        level = "MEDIUM"
    else:
        level = "LOW"

    return {
        "risk_score": score,
        "risk_level": level,
        "flags": flags,
        "breakdown": breakdown
    }