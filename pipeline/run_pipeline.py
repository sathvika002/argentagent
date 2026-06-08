"""
run_pipeline.py
───────────────
LangGraph-powered pipeline. Every transaction flows through a typed
state graph with conditional routing based on risk score.
"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import datetime
import random

from langgraph.graph import StateGraph, START, END

from pipeline.state import TransactionState
from config import RISK_BLOCK_THRESHOLD, RISK_VERIFY_THRESHOLD
from utils.db import connect
from utils.time_utils import get_current_time
from utils.location import get_location
from agents.analyzer import analyze_transaction
from agents.risk_scorer import score_risk
from agents.reporter import generate_report


# ── Fraud injection rate ──────────────────────────────────────────
FRAUD_INJECTION_RATE = 0.0

# ── Device pools per user (in-memory) ────────────────────────────
ALL_DEVICES = [
    "iPhone 14",
    "Samsung Galaxy S23",
    "MacBook Pro",
    "Windows Laptop",
    "iPad Pro",
    "Pixel 7",
]
_user_device_pools: dict[str, list[str]] = {}

# ── Velocity tracker (in-memory) ─────────────────────────────────
_tx_timestamps: dict[str, list[datetime.datetime]] = {}


# ─────────────────────────────────────────
# HELPERS  (unchanged from original)
# ─────────────────────────────────────────

def _get_device_pool(username: str) -> list[str]:
    if username not in _user_device_pools:
        _user_device_pools[username] = random.sample(ALL_DEVICES, 2)
    return _user_device_pools[username]


def _generate_device(username: str, inject_fraud: bool) -> tuple[str, bool, bool]:
    """Returns (device_name, is_new_device, is_device_mismatch)"""
    pool = _get_device_pool(username)

    if inject_fraud:
        others = [d for d in ALL_DEVICES if d not in pool]
        device = random.choice(others) if others else "Unknown Device"
        return device, True, True

    r = random.random()
    if r < 0.88:
        return random.choice(pool), False, False
    elif r < 0.97:
        others = [d for d in ALL_DEVICES if d not in pool]
        device = random.choice(others) if others else pool[0]
        return device, True, False
    else:
        return "Unknown Device", True, True


def _update_velocity(username: str) -> tuple[int, int]:
    now = datetime.datetime.now()
    if username not in _tx_timestamps:
        _tx_timestamps[username] = []

    _tx_timestamps[username].append(now)

    cutoff_5min = now - datetime.timedelta(minutes=5)
    _tx_timestamps[username] = [
        t for t in _tx_timestamps[username] if t > cutoff_5min
    ]

    cutoff_1min = now - datetime.timedelta(minutes=1)
    count_1min = sum(1 for t in _tx_timestamps[username] if t > cutoff_1min)
    count_5min = len(_tx_timestamps[username])

    return count_1min, count_5min


def _generate_amount(base_amount: float, history: list, inject_fraud: bool) -> float:
    if not inject_fraud:
        return round(base_amount, 2)

    if history and len(history) >= 3:
        amounts = [float(str(h[0]).replace("₹", "").strip()) for h in history[-20:]]
        mean = sum(amounts) / len(amounts)
    else:
        mean = base_amount

    return round(mean * random.uniform(5, 10), 2)


def _get_history(username: str) -> list:
    conn = connect()
    cur = conn.cursor()
    cur.execute("""
        SELECT amount, time, location, risk_level, status
        FROM transactions
        WHERE username = %s
        ORDER BY id DESC
        LIMIT 50
    """, (username,))
    rows = cur.fetchall()
    conn.close()
    return list(reversed(rows))


def _get_user_profile(username: str) -> dict:
    conn = connect()
    cur = conn.cursor()

    cur.execute("""
        SELECT COUNT(*) FROM transactions
        WHERE username = %s AND status = 'reversed'
    """, (username,))
    chargebacks = cur.fetchone()[0] or 0

    cur.execute("""
        SELECT COUNT(*) FROM transactions
        WHERE username = %s AND risk_level = 'CRITICAL'
    """, (username,))
    past_criticals = cur.fetchone()[0] or 0

    conn.close()
    return {
        "chargebacks": chargebacks,
        "past_fraud":  past_criticals > 0,
    }


# ─────────────────────────────────────────
# LANGGRAPH NODES
# ─────────────────────────────────────────

from utils.time_utils import seed_last_time

def node_load_context(state: TransactionState) -> dict:
    history = _get_history(state["username"])
    profile = _get_user_profile(state["username"])
    
    # seed the time simulation from the last known transaction
    if history:
        last_tx_time = history[-1][1]  # index 1 is the time column
        seed_last_time(last_tx_time)
    
    return {"history": history, "user_profile": profile}


def node_enrich(state: TransactionState) -> dict:
    inject = state["inject_fraud"]
    time     = get_current_time(inject_fraud=inject)
    location = get_location(state["username"], inject_fraud=inject)
    device, is_new, is_mismatch = _generate_device(state["username"], inject)
    amount   = _generate_amount(state["amount"], state["history"], inject)
    c1, c5   = _update_velocity(state["username"])

    return {
        "transaction": {
            "username":  state["username"],
            "amount":    amount,
            "timestamp": time,
            "location":  location,
            "device":    device,
        },
        "txn_last_1min":   c1,
        "txn_last_5min":   c5,
        "new_device":      is_new,
        "device_mismatch": is_mismatch,
    }


def node_analyze(state: TransactionState) -> dict:
    # analyze_transaction expects and returns the full state dict
    updated = analyze_transaction(dict(state))
    return {"signals": updated["signals"]}


def node_score(state: TransactionState) -> dict:
    result = score_risk(
        transaction=state["transaction"],
        user_profile=state["user_profile"],
        signals=state["signals"],
    )
    print("DEBUG score_risk output:", result)
    return result  # has risk_score, risk_level, flags, breakdown


def node_block(state: TransactionState) -> dict:
    return {"action": "BLOCK", "report": "Transaction blocked by risk engine."}


def node_allow(state: TransactionState) -> dict:
    return {"action": "ALLOW", "report": None}


def node_verify_and_report(state: TransactionState) -> dict:
    # LLM only called on the VERIFY path — saves cost on BLOCK and ALLOW
    try:
        report_output = generate_report(dict(state))
        report = report_output.get("report", "Report unavailable.")
        if isinstance(report, dict):
            report = report.get("report", "Report unavailable.")
    except Exception as e:
        print("REPORT ERROR:", e)
        report = "Report generation failed."

    return {"action": "VERIFY", "report": report}


# ─────────────────────────────────────────
# CONDITIONAL EDGE
# ─────────────────────────────────────────

def route_by_risk(state: TransactionState) -> str:
    score = state["risk_score"]
    if score >= RISK_BLOCK_THRESHOLD:
        return "block"
    if score >= RISK_VERIFY_THRESHOLD:
        return "verify"
    return "allow"


# ─────────────────────────────────────────
# BUILD GRAPH
# ─────────────────────────────────────────

def _build_graph():
    g = StateGraph(TransactionState)

    g.add_node("load_context",      node_load_context)
    g.add_node("enrich",            node_enrich)
    g.add_node("analyze",           node_analyze)
    g.add_node("score",             node_score)
    g.add_node("block",             node_block)
    g.add_node("verify_and_report", node_verify_and_report)
    g.add_node("allow",             node_allow)

    g.add_edge(START,          "load_context")
    g.add_edge("load_context", "enrich")
    g.add_edge("enrich",       "analyze")
    g.add_edge("analyze",      "score")

    g.add_conditional_edges("score", route_by_risk, {
        "block":  "block",
        "verify": "verify_and_report",
        "allow":  "allow",
    })

    g.add_edge("block",             END)
    g.add_edge("verify_and_report", END)
    g.add_edge("allow",             END)

    return g.compile()


_graph = _build_graph()


# ─────────────────────────────────────────
# PUBLIC ENTRY POINT  (app.py calls this)
# ─────────────────────────────────────────

def run_pipeline(transaction_input: dict) -> dict:
    """
    Input:  { "username": str, "amount": float }
    Output: full state dict — same keys app.py already expects
    """
    initial: TransactionState = {
        "username":      transaction_input["username"],
        "amount":        float(transaction_input["amount"]),
        "inject_fraud":  random.random() < FRAUD_INJECTION_RATE,
        # everything else gets filled in by the nodes
        "history":        [],
        "user_profile":   {},
        "transaction":    {},
        "txn_last_1min":  0,
        "txn_last_5min":  0,
        "new_device":     False,
        "device_mismatch":False,
        "signals":        {},
        "risk_score":     0,
        "risk_level":     "LOW",
        "flags":          [],
        "breakdown":      {},
        "action":         "ALLOW",
        "report":         None,
    }

    result = _graph.invoke(initial)
    result["injected_fraud"] = initial["inject_fraud"]
    return result