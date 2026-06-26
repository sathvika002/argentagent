"""
agent.py
--------
A conversational fraud verification agent.
Given a risk result and user's message, it:
  - Asks clarifying questions
  - Determines user intent: YES (they did it) or NO (fraud)
  - Returns { reply, intent }
"""

import os
from openai import OpenAI

_client = None

def get_client():
    global _client
    if _client is None:
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise ValueError("OPENAI_API_KEY not set. Check Azure App Settings.")
        _client = OpenAI(api_key=api_key)
    return _client


SYSTEM_PROMPT = """You are ArgentAgent, a friendly but firm fraud detection assistant for a banking app.

Your job is to verify a suspicious transaction with the user. Keep messages SHORT (1–2 sentences max).

Rules:
- Ask if they made the transaction.
- If they say yes / confirm / it was me → reply with confirmation and set intent=YES
- If they say no / wasn't me / fraud / block → reply with reassurance and set intent=NO
- If unclear, ask one follow-up question.
- Never reveal internal scores.
- Always end your JSON with the intent field.

Respond ONLY with valid JSON in this exact format:
{
  "reply": "your short message to the user",
  "intent": "YES" | "NO" | "UNCLEAR"
}
"""


def fraud_agent_reply(risk_result: dict, user_message: str, history: list = None) -> dict:
    """
    risk_result: the full pipeline output
    user_message: what the user just typed
    history: list of {"role": ..., "content": ...} dicts (optional)
    """
    transaction = risk_result.get("transaction", {})
    amount = transaction.get("amount", 0)
    location = transaction.get("location", "unknown")
    risk_score = risk_result.get("risk_score", 0)
    anomalies = risk_result.get("anomalies", [])
    anomaly_desc = ", ".join(a["description"] for a in anomalies) if anomalies else "general anomaly"

    context = f"""
Transaction details:
- Amount: ₹{amount:,.0f}
- Location: {location}
- Risk Score: {risk_score}/100
- Anomalies: {anomaly_desc}

The user just said: "{user_message}"
"""

    messages = [{"role": "system", "content": SYSTEM_PROMPT}]

    if history:
        for msg in history:
            if msg["role"] in ("user", "assistant"):
                messages.append({
                    "role": msg["role"],
                    "content": msg["content"]
                })

    messages.append({"role": "user", "content": context})

    try:
        print("AGENT: building messages", flush=True)  # ADD
        response = get_client().chat.completions.create(
            model="gpt-4o-mini",
            messages=messages,
            temperature=0.3,
            max_tokens=200,
            timeout=15,
        )
        print("AGENT: got response", flush=True)  # ADD

        raw = response.choices[0].message.content.strip()

        import json
        # Strip markdown fences if present
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        data = json.loads(raw)
        return {
            "reply": data.get("reply", "Can you confirm if this was you?"),
            "intent": data.get("intent", "UNCLEAR"),
        }

    except Exception as e:
        return {
            "reply": f"Sorry, I'm having trouble connecting. Was this transaction made by you? (yes/no)",
            "intent": "UNCLEAR",
        }