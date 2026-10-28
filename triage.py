"""AI-assisted, explainable triage with a safe rule-based fallback.

An AI output is advisory, not proof that a complaint is true or false. Critical
keyword rules bypass the normal queue before any optional model call.
"""
from __future__ import annotations
import base64, json, re
import requests
from backend.config import GEMINI_API_KEY, GEMINI_MODEL, GROQ_API_KEY, GROQ_MODEL

CRITICAL_TERMS = [
    "road cave-in", "road collapsed", "building collapse", "building collapsed",
    "live wire", "electric shock", "electrocution", "fire accident", "major flood",
    "flash flood", "person unconscious", "not breathing", "severe bleeding",
    "gas leak", "chemical leak", "bridge collapse", "open manhole with person",
]
HIGH_TERMS = ["overflowing sewage", "water contamination", "dengue cluster", "mosquito breeding", "large pothole", "fallen electric pole", "contaminated water", "sewage overflow"]
CATEGORY_TERMS = {
    "Water & Drainage": ["water", "drain", "leak", "sewage", "flood", "waterlogging", "pipeline", "overflow"],
    "Road & Transport": ["road", "pothole", "traffic", "footpath", "bridge", "cave-in", "street"],
    "Waste & Sanitation": ["garbage", "waste", "dump", "sanitation", "rubbish", "litter", "smell"],
    "Public Health": ["dengue", "mosquito", "fever", "outbreak", "health", "contamination", "infection"],
    "Electricity & Lighting": ["electricity", "streetlight", "light", "wire", "pole", "power", "shock"],
    "Other Civic Issue": [],
}


def _contains(text: str, terms: list[str]) -> bool:
    low = text.lower()
    return any(term in low for term in terms)


def _parse_json(text: str) -> dict:
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.IGNORECASE)
    result = json.loads(text)
    if not isinstance(result, dict):
        raise ValueError("AI response was not an object")
    return result


def _call_gemini(prompt: str, media: bytes | None, mime: str | None) -> dict | None:
    if not GEMINI_API_KEY:
        return None
    parts: list[dict] = [{"text": prompt}]
    if media and mime and mime.startswith("image/") and len(media) <= 4 * 1024 * 1024:
        parts.append({"inline_data": {"mime_type": mime, "data": base64.b64encode(media).decode()}})
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent"
    try:
        response = requests.post(url, params={"key": GEMINI_API_KEY}, json={"contents": [{"parts": parts}], "generationConfig": {"responseMimeType": "application/json", "temperature": 0.1}}, timeout=18)
        response.raise_for_status()
        text = response.json()["candidates"][0]["content"]["parts"][0]["text"]
        result = _parse_json(text)
        result["provider"] = "Gemini"
        return result
    except Exception:
        return None


def _call_groq(prompt: str, media: bytes | None, mime: str | None) -> dict | None:
    if not GROQ_API_KEY:
        return None
    content: list[dict] = [{"type": "text", "text": prompt}]
    if media and mime and mime.startswith("image/") and len(media) <= 4 * 1024 * 1024:
        data_uri = f"data:{mime};base64,{base64.b64encode(media).decode()}"
        content.append({"type": "image_url", "image_url": {"url": data_uri}})
    try:
        response = requests.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"},
            json={"model": GROQ_MODEL, "messages": [{"role": "user", "content": content}], "temperature": 0.1, "response_format": {"type": "json_object"}},
            timeout=18,
        )
        response.raise_for_status()
        result = _parse_json(response.json()["choices"][0]["message"]["content"])
        result["provider"] = "Groq"
        return result
    except Exception:
        return None


def assess_complaint(category: str, description: str, severity: str, media: bytes | None = None, mime: str | None = None, allow_external_ai: bool = False) -> dict:
    text = f"{category}. {description}".lower()
    # Emergency bypass is deterministic and occurs before optional model scoring.
    critical = _contains(text, CRITICAL_TERMS) or severity.lower() == "critical"
    high_signal = _contains(text, HIGH_TERMS) or severity.lower() == "high"
    if critical:
        score, risk = 100, "Critical"
    elif high_signal:
        score, risk = 82, "High"
    elif severity.lower() == "low":
        score, risk = 28, "Low"
    else:
        score, risk = 52, "Medium"

    prompt = (
        "You are an assistant that triages civic service complaints. Do not diagnose illnesses and do not decide that a citizen is lying. "
        "Assess relevance and urgency, not legal truth. If an image is attached, compare visible evidence to the category/description without identifying people. "
        "Return JSON only with keys: category_match (true/false/uncertain), confidence (integer 0-100), suggested_severity (Low/Medium/High/Critical), "
        "reason (short plain-language explanation), needs_human_review (boolean). Never downgrade an obvious emergency.\n"
        f"Category: {category}\nDescription: {description[:2500]}\nUser-reported severity: {severity}\n"
    )
    model_result = (_call_gemini(prompt, media, mime) or _call_groq(prompt, media, mime)) if allow_external_ai else None
    if model_result:
        try:
            ai_sev = str(model_result.get("suggested_severity", severity)).title()
            if ai_sev not in {"Low", "Medium", "High", "Critical"}:
                ai_sev = severity.title() if severity.title() in {"Low", "Medium", "High", "Critical"} else "Medium"
            conf = max(0, min(100, int(model_result.get("confidence", 50))))
            match = str(model_result.get("category_match", "uncertain")).lower()
            if critical:
                ai_sev, score = "Critical", 100
            else:
                score = max(score, {"Low": 25, "Medium": 50, "High": 80, "Critical": 95}[ai_sev])
            return {
                "critical_override": critical, "priority_score": score, "risk_level": "Critical" if critical else ai_sev,
                "severity": ai_sev, "ai_validation": "Likely match" if match == "true" else ("Mismatch - review" if match == "false" else "Needs human review"),
                "ai_confidence": conf, "ai_reason": str(model_result.get("reason", "AI-assisted relevance assessment"))[:800],
                "triage_provider": str(model_result.get("provider", "AI")),
                "review_required": True if match != "true" or bool(model_result.get("needs_human_review", True)) else False,
            }
        except Exception:
            pass

    category_terms = CATEGORY_TERMS.get(category, [])
    content_match = _contains(text, category_terms) if category_terms else len(description.strip()) > 12
    if media:
        validation = "Media requires review"
        confidence = 58 if content_match else 38
        reason = "Rule-based text check completed. Media has not been independently verified; a human should confirm that the attachment supports the report."
        review = True
    elif content_match:
        validation = "Text appears consistent"
        confidence = 62
        reason = "The description contains terms related to the selected category. This is a weak consistency signal, not proof of validity."
        review = True
    else:
        validation = "Needs human review"
        confidence = 42
        reason = "The description did not provide enough category-specific signals for an automatic recommendation. No complaint is rejected by this rule."
        review = True
    if critical:
        validation = "Urgent - bypass queue"
        reason = "A configured critical-safety trigger was detected. Urgent routing takes precedence over standard triage and must be reviewed by a responsible human."
    return {"critical_override": critical, "priority_score": score, "risk_level": risk, "severity": risk if critical or high_signal else severity.title(), "ai_validation": validation, "ai_confidence": confidence, "ai_reason": reason, "triage_provider": "Rules", "review_required": review}
