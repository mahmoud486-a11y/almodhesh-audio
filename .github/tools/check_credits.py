#!/usr/bin/env python3
"""فحص للقراءة فقط لخطة ElevenLabs قبل النشر (لا يستهلك رصيدًا). لا يطبع الرصيد المتبقي بالأرقام."""
import datetime
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
import generate_audio as tts  # noqa: E402

DAILY_CAP = 3300        # الحد اليومي للنظام الجديد
MONTHLY_NEED = 54400    # الاستهلاك الشهري المتوقع (إنجليزي + عربي)
key = os.environ.get("ELEVENLABS_API_KEY", "").strip()
try:
    s = json.loads(tts.api_request("GET", "/user/subscription", key, timeout=30))
except RuntimeError as e:
    sys.exit(f"تعذر الفحص: {tts.sanitize(e)[:200]}")
remaining = int(s["character_limit"]) - int(s["character_count"])
reset = s.get("next_character_count_reset_unix")
print("الخطة:", s.get("tier"), "| الحالة:", s.get("status"), "| الفوترة:", s.get("billing_period"))
print("الحصة الشهرية:", s.get("character_limit"), "| التجديد:", datetime.datetime.utcfromtimestamp(reset).strftime("%Y-%m-%d") if reset else "؟")
print("تكفي الحصة الشهرية للاستهلاك المتوقع (54,400):", "نعم" if int(s["character_limit"]) >= MONTHLY_NEED else "لا")
print("الرصيد المتبقي يكفي درس اليوم (3,300):", "نعم" if remaining >= DAILY_CAP else "لا")
print("الرصيد المتبقي يكفي شهرًا كاملًا (54,400):", "نعم" if remaining >= MONTHLY_NEED else "لا")
print("الفوترة حسب الاستخدام (تجاوز الحصة) مسموحة للخطة:", s.get("allowed_to_extend_character_limit"),
      "| مفعّلة:", s.get("can_extend_character_limit"), "| حدها الأقصى:", s.get("max_character_limit_extension"))
