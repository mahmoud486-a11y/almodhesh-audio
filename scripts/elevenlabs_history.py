#!/usr/bin/env python3
"""يحدد الصوت المستخدم في درس سابق من سجل ElevenLabs (قراءة فقط، لا يستهلك رصيدًا).

يبحث في سجل التوليد (Speech History) عن نصوص جمل الدرس، ويعرض معرّف الصوت واسمه والنموذج.
يحتاج المفتاح صلاحية Speech History → Read (وصلاحية Voices → Read لعرض تفاصيل الصوت).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import generate_audio as tts  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent


def main(argv=None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--lesson", default="2026-11-21")
    p.add_argument("--pages", type=int, default=5)
    args = p.parse_args(argv)

    key = os.environ.get("ELEVENLABS_API_KEY", "").strip()
    if not key:
        print("ELEVENLABS_API_KEY غير مضبوط.")
        return 2
    lesson = json.loads((ROOT / "site" / "lessons" / f"{args.lesson}.json").read_text(encoding="utf-8"))
    targets = {s["en"].strip().lower(): f"news-{i}" for i, s in enumerate(lesson["stories"], 1)}
    targets.update({w[0].strip().lower(): f"word:{w[0]}" for w in lesson["words"]})

    items, cursor = [], None
    for _ in range(args.pages):
        query = "?page_size=100" + (f"&start_after_history_item_id={cursor}" if cursor else "")
        try:
            data = json.loads(tts.api_request("GET", "/history", key, query=query, timeout=60))
        except RuntimeError as e:
            print(f"تعذرت قراءة السجل: {tts.sanitize(e)[:300]}")
            if "missing_permissions" in str(e) or "HTTP 401" in str(e):
                print("أضف للمفتاح صلاحية Speech History → Read ثم أعد التشغيل.")
            return 4
        items += data.get("history", [])
        if not data.get("has_more"):
            break
        cursor = data.get("last_history_item_id")

    print(f"عناصر السجل المقروءة: {len(items)}")
    matches = [it for it in items if (it.get("text") or "").strip().lower() in targets]
    for it in matches:
        when = datetime.fromtimestamp(it.get("date_unix", 0), timezone.utc).strftime("%Y-%m-%d %H:%M")
        print(f"  {targets[it['text'].strip().lower()]:<20} {when}  voice={it.get('voice_id')} "
              f"({it.get('voice_name')})  model={it.get('model_id')}")
    if not matches:
        print("لم يُعثر على جمل الدرس في السجل (ربما وُلّدت بحساب آخر أو بأداة أخرى).")
        recent = Counter((it.get("voice_id"), it.get("voice_name"), it.get("model_id")) for it in items[:100])
        for (vid, name, model), n in recent.most_common(5):
            print(f"  أكثر الأصوات استخدامًا مؤخرًا: voice={vid} ({name}) model={model} — {n} مرة")
        return 1

    (vid, name, model), n = Counter(
        (m.get("voice_id"), m.get("voice_name"), m.get("model_id")) for m in matches).most_common(1)[0]
    print(f"\nالصوت المستخدم: {name} | ELEVENLABS_LESSON_VOICE_ID={vid} | النموذج: {model} ({n} تسجيل)")
    try:
        voice = json.loads(tts.api_request("GET", f"/voices/{vid}", key, timeout=60))
        print(f"تفاصيل الصوت: {json.dumps(voice.get('labels', {}), ensure_ascii=False)} | الفئة: {voice.get('category')}")
    except RuntimeError as e:
        print(f"(تعذر جلب تفاصيل الصوت: {tts.sanitize(e)[:150]})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
