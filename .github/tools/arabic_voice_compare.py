#!/usr/bin/env python3
"""مقارنة نطق عربي: الترجمات الثلاث (المستوى المتوسط) بصوت عربي واحد، بنموذجي Multilingual v2 و Flash v2.5.
- حد أقصى صارم 460 رصيدًا: يتوقف قبل أي طلب إن تجاوز التقدير ذلك أو لم يكفِ الرصيد.
- لا يلمس الصوت الإنجليزي ولا إعداداته، ولا يحفظ شيئًا في المستودع، ولا ينشر الموقع."""
import json
import math
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
import generate_audio as tts  # noqa: E402

MAX_CREDITS = 460
TEXTS = [
    "أمر رئيس وزراء العراق وزارة الطاقة بإدارة حقول النفط الواقعة تحت السيطرة الكردية، وهي خطوة رفضها الأكراد.",
    "وافقت المملكة العربية السعودية على ميزانية بقيمة 371 مليار دولار في وقت يتباطأ فيه النمو غير النفطي في المملكة.",
    "راجع وزيرا التخطيط والتموين في مصر خطط التنمية البشرية لتوسيع الاستثمار في الصحة والتعليم.",
]
MODELS = [("eleven_multilingual_v2", 1.0), ("eleven_flash_v2_5", 0.5)]  # (النموذج، رصيد لكل حرف)

key = os.environ.get("ELEVENLABS_API_KEY", "").strip()
voice = os.environ.get("ARABIC_VOICE_ID", "").strip()
if not key or not voice:
    sys.exit("المفتاح أو معرّف الصوت العربي غير مضبوط.")
chars = sum(len(t) for t in TEXTS)
planned = math.ceil(sum(chars * rate for _, rate in MODELS))
print(f"الصوت العربي: {voice} | الأحرف: {chars} | الأرصدة المقدّرة: {planned} (الحد {MAX_CREDITS})")
if planned > MAX_CREDITS:
    sys.exit("التقدير يتجاوز الحد المعتمد؛ أُلغيت المقارنة دون استهلاك.")
remaining = tts.remaining_characters(key)
if remaining is None or remaining < planned:
    sys.exit("الرصيد غير كافٍ أو تعذّر فحصه؛ أُلغيت المقارنة دون استهلاك.")
print("الرصيد كافٍ.")

out = Path("arabic-voice-comparison")
out.mkdir(exist_ok=True)
spent = 0.0
for model, rate in MODELS:
    for i, text in enumerate(TEXTS, 1):
        if spent + len(text) * rate > MAX_CREDITS:
            sys.exit("بلغ الحد المعتمد؛ توقفت المقارنة.")
        try:
            audio = tts.synthesize(text, key, voice, model, "mp3_44100_128")
        except RuntimeError as e:
            sys.exit(f"تعذّر التسجيل ({model}، النص {i}): {tts.sanitize(e)[:300]}")
        name = f"{i}-{'multilingual-v2' if 'multilingual' in model else 'flash-v2.5'}.mp3"
        (out / name).write_bytes(audio)
        spent += len(text) * rate
        print(f"  ✓ {name} ({len(text)} حرفًا)")
(out / "texts.json").write_text(json.dumps(TEXTS, ensure_ascii=False, indent=1), encoding="utf-8")
print(f"انتهت المقارنة: 6 ملفات، نحو {math.ceil(spent)} رصيدًا.")
