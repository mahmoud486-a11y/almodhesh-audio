#!/usr/bin/env python3
"""بحث للقراءة فقط في مكتبة أصوات ElevenLabs عن أصوات عربية ذكورية للتعليق الإخباري بالفصحى.
طلبات GET فقط (/v1/shared-voices) — لا تستهلك أي رصيد ولا تضيف صوتًا إلى الحساب ولا تغيّر أي إعداد."""
import json
import os
import sys
import urllib.parse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
import generate_audio as tts  # noqa: E402

key = os.environ.get("ELEVENLABS_API_KEY", "").strip()
if not key:
    sys.exit("ELEVENLABS_API_KEY غير مضبوط.")

found = {}
queries = [
    {"language": "ar", "gender": "male", "use_cases": "news"},
    {"language": "ar", "gender": "male", "use_cases": "informative_educational"},
    {"language": "ar", "gender": "male", "use_cases": "narrative_story"},
    {"language": "ar", "gender": "male", "search": "news"},
    {"language": "ar", "gender": "male", "search": "fusha"},
    {"language": "ar", "gender": "male", "search": "standard"},
    {"language": "ar", "gender": "male"},
]
for q in queries:
    params = {"page_size": "100", "sort": "cloned_by_count", **q}
    try:
        data = json.loads(tts.api_request("GET", "/shared-voices", key, query="?" + urllib.parse.urlencode(params), timeout=60))
    except RuntimeError as e:
        print(f"تعذر البحث ({q}): {tts.sanitize(e)[:300]}")
        if "missing_permissions" in str(e):
            sys.exit("المفتاح يحتاج صلاحية Voices → Read للبحث في مكتبة الأصوات.")
        continue
    for v in data.get("voices", []):
        found.setdefault(v.get("voice_id"), v)

def score(v):
    text = " ".join(str(v.get(k, "")) for k in ("name", "description", "accent", "descriptive", "use_case", "locale")).lower()
    s = 0
    s += 6 * any(w in text for w in ("news", "broadcast", "anchor", "أخبار", "إخبار", "نشرة"))
    s += 5 * any(w in text for w in ("standard", "msa", "fusha", "fus'ha", "classical", "فصحى", "فصيح", "modern standard"))
    s += 3 * any(w in text for w in ("narrat", "documentary", "educational", "informative", "professional", "clear", "deep"))
    s -= 4 * any(w in text for w in ("egyptian", "gulf", "saudi dialect", "levantine", "moroccan", "darija", "khaleeji", "iraqi", "lebanese", "syrian", "عامية"))
    s += min(5, (v.get("cloned_by_count") or 0) // 500)
    s += 2 * (v.get("category") == "professional")
    return s

ranked = sorted((v for v in found.values() if (v.get("gender") or "").lower() == "male"), key=score, reverse=True)
print(f"أصوات عربية ذكورية وُجدت: {len(ranked)} — أفضل 12 مرشحًا:\n")
for v in ranked[:12]:
    print(json.dumps({
        "score": score(v), "name": v.get("name"), "voice_id": v.get("voice_id"),
        "public_owner_id": v.get("public_owner_id"), "category": v.get("category"),
        "accent": v.get("accent"), "age": v.get("age"), "descriptive": v.get("descriptive"),
        "use_case": v.get("use_case"), "language": v.get("language"), "locale": v.get("locale"),
        "cloned_by_count": v.get("cloned_by_count"), "free_users_allowed": v.get("free_users_allowed"),
        "description": (v.get("description") or "")[:240], "preview_url": v.get("preview_url"),
    }, ensure_ascii=False))
