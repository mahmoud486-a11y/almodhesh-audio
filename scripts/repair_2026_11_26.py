"""إصلاح موجَّه لدرس 26 نوفمبر 2026 (مرة واحدة) — دون أي استدعاء مدفوع.

- يستبدل مستوى المبتدئ (كان نسخة من المتوسط) بنص أُعدّ سلفًا في scripts/repairs/2026-11-26-beginner.json
  بالحقائق الثلاث نفسها، ويتحقق منه بكل فحوص CEFR والتفريق والاختبار.
- يستبدل السؤال الأول في المتقدم (لا يدعمه نصه) دون أي تغيير في نص الأخبار أو صوتها.
- لا يمس المتوسط ولا باقي الأرشيف.

الوضع الافتراضي تجربة جافة (يطبع النتيجة فقط). التطبيق: --apply، ويكتب ملف الدرس فقط.
بعده (بموافقة صريحة فقط) تأتي الخطوتان المدفوعتان من سير العمل المعتاد: التدقيق العربي للمبتدئ وتسجيل أصواته الناقصة.
"""
from __future__ import annotations

import argparse
import copy
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import cefr  # noqa: E402
import daily_lesson as dl  # noqa: E402
import multilevel as ml  # noqa: E402

KEY = "2026-11-26"
PAYLOAD = Path(__file__).resolve().parent / "repairs" / "2026-11-26-beginner.json"


def plan(lesson: dict, payload: dict) -> tuple[dict, list[str]]:
    """يعيد (الدرس بعد الإصلاح، أخطاء التحقق). لا يكتب شيئًا."""
    new = copy.deepcopy(lesson)
    inter = lesson["levels"]["intermediate"]
    b = payload["beginner"]
    facts = {"stories": [{"facts": f["facts"]} for f in lesson["facts"]]}
    errors = ml.validate_level(b, "beginner", dl.known_translations(), ml.LEVELS["beginner"]["audio_max"],
                               {"intermediate": inter, "advanced": lesson["levels"]["advanced"]}, facts)
    stories = []
    for st, src in zip(b["stories"], inter["stories"]):  # الموضوع والمصدر والرابط من المستوى المنشور نفسه
        stories.append({"topic": src["topic"], "en": st["en"].strip(), "ar": st["ar"].strip(),
                        "source": src["source"], "url": src["url"]})
    words = [[w["en"].strip(), w["ar"].strip()] for w in b["words"]]
    translations = {}
    for t in b["translations"]:
        translations.setdefault(t["word"].strip().lower(), t["ar"].strip())
    for en, ar in words:
        translations.setdefault(en.lower(), ar)
    exercises = [{"question": e["question"], "question_ar": e["question_ar"], "options": list(e["options"]),
                  "answer": e["answer"]} for e in b["exercises"]]
    new["levels"]["beginner"] = {"stories": stories, "words": words, "translations": translations, "exercises": exercises,
                                 "audio": {"stories": None, "words": None}, "generated_by": "repair-2026-11-26"}
    adv = new["levels"]["advanced"]["exercises"]
    adv[0] = dict(payload["advanced_exercise_1"])
    adv[2] = dict(payload["advanced_exercise_3"])
    adv_words = new["levels"]["advanced"]["words"]
    swaps = payload["advanced_vocab"]["replace"]
    adv_audio = new["levels"]["advanced"]["audio"]["words"]
    for i, w in enumerate(adv_words):
        if w[0] in swaps:
            w[0], w[1] = swaps[w[0]]
            adv_audio[i] = None  # تسجيل الكلمة القديمة لا يصلح للجديدة؛ تُسجَّل لاحقًا بموافقة (8 كلمات فقط)
    for en, ar in swaps.values():
        new["levels"]["advanced"]["translations"].setdefault(en.lower(), ar.split(" / ")[0])
    new["levels"]["advanced"]["examples"] = copy.deepcopy(payload["advanced_vocab"]["examples"])  # لا يعرضها الموقع بعد؛ للمراجعة والتدقيق
    other_words = {w[0].lower() for lv in ("beginner", "intermediate") for w in new["levels"][lv]["words"]}
    en_words = [w[0] for w in adv_words]
    if len(en_words) != 20 or len({w.lower() for w in en_words}) != 20:
        errors.append("advanced: need 20 distinct words")
    shared = {w.lower() for w in en_words} & other_words
    if len(shared) > ml.MAX_SHARED_WORDS:
        errors.append(f"advanced: too many words shared with other levels: {sorted(shared)}")
    errors += [f"advanced: {e}" for e in cefr.validate_words("advanced", en_words)]
    ex = payload["advanced_vocab"]["examples"]
    for w in swaps.values():
        e = ex.get(w[0])
        if not e or not re.search(rf"\b{re.escape(w[0])}", e["en"], re.I) or not ml.ARABIC.search(e["ar"]):
            errors.append(f"advanced: missing or invalid contextual example for '{w[0]}'")
    errors += [f"advanced: {e}" for e in cefr.validate_exercise_support([adv[0], adv[2]], [s["en"] for s in new["levels"]["advanced"]["stories"]])]
    return new, errors


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="اكتب ملف الدرس (بدونها: تجربة جافة)")
    ap.add_argument("--finish", action="store_true",
                    help="بعد --apply: تدقيق عربي للعناصر الجديدة فقط ثم تسجيل الناقص ثم بناء الموقع (مدفوع، بحارس الميزانية)")
    args = ap.parse_args()
    path = dl.SITE / "lessons" / f"{KEY}.json"
    lesson = dl.read_json(path, None)
    payload = json.loads(PAYLOAD.read_text(encoding="utf-8"))
    if lesson["levels"]["beginner"].get("generated_by") == "repair-2026-11-26":  # لا يُعاد التطبيق ولا التدقيق (لا تكلفة مكررة)
        print("الإصلاح مطبَّق مسبقًا؛ لا تغيير.")
        return finish(path, lesson, review=False) if args.finish and args.apply else 0
    new, errors = plan(lesson, payload)
    if errors:
        print("❌ فشل التحقق، لم يُكتب شيء:")
        for e in errors:
            print(" -", e)
        return 1
    b = new["levels"]["beginner"]
    print("✔ مستوى المبتدئ الجديد اجتاز كل الفحوص.")
    for i, s in enumerate(b["stories"], 1):
        print(f"  {i}. {s['en']}")
    print("✔ سؤالا المتقدم 1 و3 مدعومان بنصه:", [new["levels"]["advanced"]["exercises"][i]["question"] for i in (0, 2)])
    print("✔ كلمات المتقدم بعد استبدال الثماني:", ", ".join(w[0] for w in new["levels"]["advanced"]["words"]))
    for en, e in new["levels"]["advanced"]["examples"].items():
        print(f"   {en}: {e['en']}")
    if not args.apply:
        print("تجربة جافة: لم يُكتب شيء. استخدم --apply بعد الموافقة.")
        return 0
    dl.write_json(path, new)
    print(f"كُتب {path}.")
    if not args.finish:
        print("الخطوات المدفوعة (--finish) لم تُنفَّذ.")
        return 0
    return finish(path, new)


def review_ids(lesson: dict) -> set[str]:
    """عناصر التدقيق: كل ما في المبتدئ، وما تغيّر في المتقدم فقط (الكلمات الجديدة وأمثلتها والسؤالان)."""
    adv = lesson["levels"]["advanced"]
    ids = {k for k in ml.review_items(lesson, ["beginner"]) if ":beginner" in k}
    ids |= {f"w:advanced:{i}" for i, w in enumerate(adv["words"]) if w[0] in {v[0] for v in json.loads(PAYLOAD.read_text(encoding="utf-8"))["advanced_vocab"]["replace"].values()}}
    ids |= {f"x:advanced:{w}" for w in adv.get("examples", {})} | {"q:advanced:0", "q:advanced:2"}
    return ids


def finish(path: Path, lesson: dict, review: bool = True) -> int:
    import ledger
    try:
        previous = lesson.get("review")
        if review and not ml.run_review(lesson, path, only=review_ids(lesson)):
            return 1
        if review and previous:
            lesson["review_previous"] = previous  # لا يُمحى سجل التدقيق الأصلي
            dl.write_json(path, lesson)
        ok = ml.generate_audio(dl.DAILY_MAX_CHARS, ["beginner", "advanced"], path)
        print(f"أحدث درس في الموقع: {dl.build_site_data.build(dl.LESSONS_DIR, dl.SITE / 'lessons-data.js')}")
        return 0 if ok else 1
    finally:
        ledger.end()


if __name__ == "__main__":
    raise SystemExit(main())
