from dotenv import load_dotenv
import os
from openai import OpenAI

from utils.watermark import embed_watermark

load_dotenv()

_client = None

def get_client():
    global _client
    if _client is None:
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise ValueError("API key not found. Check your .env file.")
        _client = OpenAI(api_key=api_key)
    return _client


def generate_report(state):
    risk_score  = state.get("risk_score", 0)
    risk_level  = state.get("risk_level", "UNKNOWN")
    flags       = state.get("flags", [])
    breakdown   = state.get("breakdown", {})

    breakdown_lines = "\n".join(
        f"  {k}: +{v}" for k, v in breakdown.items() if v > 0
    )

    prompt = f"""
You are a banking fraud system analyst.

Output a SHORT report in EXACTLY this format, no extra text:

Risk Score: {risk_score}
Risk Level: {risk_level}
Score Breakdown:
{breakdown_lines}
Flags: {", ".join(flags) if flags else "none"}
Reason: <one sentence explaining the biggest risk factor>

Rules:
- Do NOT change the score or level — they are computed, not your job
- The breakdown lines are already provided above, copy them as-is
- Reason must be ONE sentence, direct, no fluff
- No paragraphs, no storytelling
"""

    response = get_client().chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.1
    )

    raw_report = response.choices[0].message.content
    username = state.get("username", "")
    watermarked_report = embed_watermark(raw_report, username)

    return {
        "report": watermarked_report
    }
