from dotenv import load_dotenv
import os
from openai import OpenAI

load_dotenv()

api_key = os.getenv("OPENAI_API_KEY")

if not api_key:
    raise ValueError("API key not found. Check your .env file.")

client = OpenAI(api_key=api_key)


def generate_report(state):

    risk_score  = state.get("risk_score", 0)
    risk_level  = state.get("risk_level", "UNKNOWN")
    flags       = state.get("flags", [])
    breakdown   = state.get("breakdown", {})
    transaction = state.get("transaction", {})

    # Build a readable breakdown string
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

    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.1
    )

    return {
        "report": response.choices[0].message.content
    }