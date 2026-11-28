"""تدقيق دون اتصال لكل الدروس متعددة المستويات المحفوظة: نسخ بين المستويات، فحوص CEFR، دعم الاختبارات بالنص.
لا استدعاءات مدفوعة ولا كتابة. الاستخدام: python3 scripts/audit_lessons.py [YYYY-MM-DD ...]"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import cefr  # noqa: E402
import daily_lesson as dl  # noqa: E402
import multilevel as ml  # noqa: E402


def audit(lesson: dict) -> list[str]:
    out = []
    lv = lesson.get("levels")
    if not lv:
        return ["درس قديم بمستوى واحد (لا يُفحص تمايزه)"]
    for lvl, v in lv.items():
        if v.get("same_as"):
            out.append(f"{lvl}: نسخة من {v['same_as']}")
    facts = {"stories": [{"facts": f["facts"]} for f in lesson.get("facts", [])]} if lesson.get("facts") else None
    known = dl.known_translations()
    done = {}
    for lvl in ml.LEVEL_ORDER:
        v = lv.get(lvl)
        if not v or v.get("same_as"):
            continue
        data = {"stories": [{"en": s["en"], "ar": s["ar"]} for s in v["stories"]],
                "words": [{"en": w[0], "ar": w[1]} for w in v["words"]],
                "translations": [{"word": k, "ar": a} for k, a in v["translations"].items()],
                "exercises": v["exercises"]}
        out += [f"{lvl}: {e}" for e in ml.validate_level(data, lvl, known, None, dict(done), facts)]
        done[lvl] = v
    return out


def main(argv: list[str]) -> int:
    paths = sorted((dl.SITE / "lessons").glob("*.json"))
    if argv:
        paths = [p for p in paths if p.stem in argv]
    bad = 0
    for p in paths:
        problems = audit(dl.read_json(p, {}))
        bad += bool(problems)
        print(("⚠️ " if problems else "✔ ") + p.stem)
        for e in problems:
            print("    -", e)
    print(f"\n{len(paths)} درسًا، {bad} فيها ملاحظات")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
