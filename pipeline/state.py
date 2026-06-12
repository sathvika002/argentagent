# state.py — expand this
from typing import TypedDict, List, Dict, Any, Optional

class TransactionState(TypedDict):
    # inputs
    username: str
    amount: float
    inject_fraud: bool
    # enriched
    transaction: Dict[str, Any]
    history: List
    user_profile: Dict
    txn_last_1min: int
    txn_last_5min: int
    # computed
    signals: Dict[str, Any]
    risk_score: int
    risk_level: str
    flags: List[str]
    breakdown: Dict
    action: str          # ALLOW / VERIFY / BLOCK / DECLINED
    report: Optional[str]
    decline_reason: Optional[str]  # INSUFFICIENT_FUNDS, etc.