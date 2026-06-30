"""
Invisible Unicode watermarking using zero-width characters.

embed_watermark(text, username) — hides the username inside the report text
verify_watermark(text, candidate) — checks if the text was watermarked with candidate
"""

_BIT_0 = "​"   # zero-width space       → 0
_BIT_1 = "‌"   # zero-width non-joiner  → 1


def _encode(username: str) -> str:
    """Convert username to a string of zero-width characters (one per bit)."""
    bits = "".join(f"{ord(c):08b}" for c in username)
    return "".join(_BIT_0 if b == "0" else _BIT_1 for b in bits)


def _decode(hidden: str) -> str:
    """Extract zero-width chars from hidden and decode back to a string."""
    bits = "".join("0" if c == _BIT_0 else "1" for c in hidden if c in (_BIT_0, _BIT_1))
    chars = []
    for i in range(0, len(bits) - 7, 8):
        chars.append(chr(int(bits[i:i + 8], 2)))
    return "".join(chars)


def embed_watermark(text: str, username: str) -> str:
    """Embed username invisibly into text by appending one hidden bit per word."""
    if not username or not text:
        return text

    hidden = _encode(username)
    words = text.split(" ")

    result = []
    for i, word in enumerate(words):
        if i < len(hidden):
            result.append(word + hidden[i])
        else:
            result.append(word)

    # If more hidden bits than words, append the remainder after the last word
    if len(hidden) > len(words):
        result[-1] += hidden[len(words):]

    return " ".join(result)


def verify_watermark(text: str, candidate_username: str) -> bool:
    """Return True if text was watermarked with candidate_username."""
    if not text or not candidate_username:
        return False
    extracted = "".join(c for c in text if c in (_BIT_0, _BIT_1))
    if not extracted:
        return False
    try:
        decoded = _decode(extracted)
        return decoded == candidate_username
    except Exception:
        return False
