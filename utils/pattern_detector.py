"""
pattern_detector.py
────────────────────
Detects "too clean" transaction amounts that suggest a scripted/automated
source rather than organic human spending — a classic card-testing signal.

Card testing = attacker has a stolen card number and runs small transactions
through it (often scripted) to check if the card is still live before
attempting a large purchase. Scripts tend to generate suspiciously
patterned amounts: round numbers, repeated digits, sequential digits.

This does NOT replace existing signals — it's an additive flag that feeds
into agents/risk_scorer.py exactly like impossible_travel or is_foreign.
"""

import re


def _digits_only(amount: float) -> str:
    """
    ₹1234.00 -> '1234'  (rupee part only, paise dropped)
    ₹1234.56 -> '1234'  (we only care about the whole-rupee digits —
                          paise is rarely chosen deliberately by a script)
    """
    whole = int(amount)
    return str(whole)


def is_round_number(amount: float) -> bool:
    """
    True for amounts like 100, 500, 1000, 5000, 10000 — i.e. amounts that
    are suspiciously 'clean'. Real human spending rarely lands on a
    perfectly round number above small change.
    """
    if amount <= 0:
        return False
    # round to nearest 100 and check if it's unchanged AND >= 100
    return amount >= 100 and amount % 100 == 0


def has_repeating_digits(amount: float, min_repeat: int = 3) -> bool:
    """
    True for amounts like 1111.00, 7777.00, 222.22 — same digit repeated
    min_repeat+ times in a row. Scripts often loop with a fixed test value.
    """
    digits = _digits_only(amount)
    pattern = r"(\d)\1{" + str(min_repeat - 1) + ",}"
    return bool(re.search(pattern, digits))


def has_sequential_digits(amount: float, min_run: int = 4) -> bool:
    """
    True for amounts like 1234.00, 12345.00, 9876.00 — ascending or
    descending digit runs. Classic "test value" pattern from scripts
    that increment/decrement a counter.
    """
    digits = _digits_only(amount)
    if len(digits) < min_run:
        return False

    for i in range(len(digits) - min_run + 1):
        window = digits[i : i + min_run]
        nums = [int(d) for d in window]

        ascending = all(nums[j] + 1 == nums[j + 1] for j in range(len(nums) - 1))
        descending = all(nums[j] - 1 == nums[j + 1] for j in range(len(nums) - 1))

        if ascending or descending:
            return True
    return False


def detect_amount_pattern(amount: float) -> dict:
    """
    Main entry point. Returns a dict ready to merge into the `signals` dict
    that flows through agents/analyzer.py -> agents/risk_scorer.py.

    {
        "amount_pattern_flag": bool,
        "amount_pattern_type": str | None
    }
    """
    if has_sequential_digits(amount):
        return {"amount_pattern_flag": True, "amount_pattern_type": "sequential_digits"}

    if has_repeating_digits(amount):
        return {"amount_pattern_flag": True, "amount_pattern_type": "repeating_digits"}

    if is_round_number(amount):
        return {"amount_pattern_flag": True, "amount_pattern_type": "round_number"}

    return {"amount_pattern_flag": False, "amount_pattern_type": None}