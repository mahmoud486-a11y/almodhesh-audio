#!/usr/bin/env python3
"""يبني site/lessons-data.js من ملفات الدروس site/lessons/YYYY-MM-DD.json.

الملف الناتج يعرّف المتغيرات نفسها التي كان app.js الأصلي يعرّفها في أوله
(lessonDate, stories, words, lessons, lessonAudio, lessonWordAudio, archive,
automaticTranslations)، فيبقى منطق الموقع في app.js دون أي تعديل.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SITE = ROOT / "site"
LESSONS_DIR = SITE / "lessons"
OUTPUT = SITE / "lessons-data.js"
BASE_TRANSLATIONS = LESSONS_DIR / "_base-translations.json"
KEY_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
LEVELS = ["beginner", "intermediate", "advanced"]
DEFAULT_LEVEL = "intermediate"


def view(lesson: dict, level: str) -> dict:
    """محتوى الدرس لمستوى معيّن. الدروس القديمة (بلا مستويات) تظهر كما هي في كل المستويات."""
    if "levels" not in lesson:
        return lesson
    levels = lesson["levels"]
    return levels.get(level) or levels[lesson.get("default_level", DEFAULT_LEVEL)]


def load_lessons(lessons_dir: Path | None = None) -> list[dict]:
    lessons_dir = lessons_dir or LESSONS_DIR
    lessons = []
    for path in sorted(lessons_dir.glob("*.json")):
        if not KEY_RE.match(path.stem):
            continue
        lesson = json.loads(path.read_text(encoding="utf-8"))
        if lesson.get("key") != path.stem:
            raise ValueError(f"{path.name}: key لا يطابق اسم الملف")
        if lesson.get("pending_audio"):
            continue  # درس لم تكتمل تسجيلاته بعد: لا يُنشر، ويبقى آخر درس مكتمل
        lessons.append(lesson)
    lessons.sort(key=lambda l: l["key"], reverse=True)  # الأحدث أولًا
    if not lessons:
        raise ValueError("لا توجد دروس")
    return lessons


def merged_translations(lessons: list[dict], base_path: Path = BASE_TRANSLATIONS) -> dict:
    merged = json.loads(base_path.read_text(encoding="utf-8")) if base_path.exists() else {}
    # من الأقدم إلى الأحدث، ولا تُستبدل ترجمة موجودة حتى لا يتغير عرض الدروس السابقة
    for lesson in reversed(lessons):
        views = [lesson["levels"][l] for l in LEVELS if l in lesson.get("levels", {})] or [lesson]
        for v in views:
            for word, ar in v.get("translations", {}).items():
                merged.setdefault(word.lower(), ar)
    return merged


def js(value) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def render(lessons: list[dict], translations: dict, level: str = DEFAULT_LEVEL, level_file: bool = False) -> str:
    latest = lessons[0]["key"]
    lessons_obj = {}
    for l in lessons:
        v = view(l, level)
        lessons_obj[l["key"]] = {"date": l["date"], "stories": v["stories"], "words": v["words"]}
        if v.get("exercises"):
            lessons_obj[l["key"]]["exercises"] = v["exercises"]
    lesson_audio, word_audio, arabic_audio = {}, {}, {}
    for l in lessons:
        audio = view(l, level).get("audio") or {}
        if "levels" in l and audio.get("stories_ar"):
            arabic_audio[l["key"]] = audio["stories_ar"]
        if audio.get("stories"):
            lesson_audio[l["key"]] = audio["stories"]
        if audio.get("words"):
            word_audio[l["key"]] = audio["words"]
    archive = [
        {"key": l["key"], "date": l["archive_date"], "title": l["archive_title"], "count": len(view(l, level)["stories"])}
        for l in lessons
    ]
    return (
        "// ملف مُولَّد تلقائيًا من site/lessons/*.json بواسطة scripts/build_site_data.py — لا تعدّله يدويًا.\n"
        f"const lessonDate={js(latest)};\n"
        f"const lessons={js(lessons_obj)};\n"
        "const stories=lessons[lessonDate].stories;\n"
        "const words=lessons[lessonDate].words;\n"
        f"const automaticTranslations={js(translations)};\n"
        f"const lessonAudio={js(lesson_audio)};\n"
        f"const lessonWordAudio={js(word_audio)};\n"
        f"const archive={js(archive)};\n"
        + (f"const lessonArabicAudio={js(arabic_audio)};\n" if level_file else "")
    )


def build(lessons_dir: Path | None = None, output: Path | None = None) -> str:
    """يكتب lessons-data-<level>.js لكل مستوى، و lessons-data.js (المتوسط) للتوافق مع النسخ المحفوظة."""
    lessons_dir = lessons_dir or LESSONS_DIR
    output = output or OUTPUT
    lessons = load_lessons(lessons_dir)
    translations = merged_translations(lessons, lessons_dir / "_base-translations.json")
    for level in LEVELS:
        output.with_name(f"lessons-data-{level}.js").write_text(render(lessons, translations, level, True), encoding="utf-8")
    output.write_text(render(lessons, translations, DEFAULT_LEVEL), encoding="utf-8")
    # ملف صغير جدًا (بضعة بايتات) يفحصه الموقع كل 5 دقائق للتنبيه بوجود درس أحدث؛ بلا أي تكلفة API
    output.with_name("latest.json").write_text(json.dumps({"lesson": lessons[0]["key"]}) + "\n", encoding="utf-8")
    return lessons[0]["key"]


if __name__ == "__main__":
    print(f"تم بناء {OUTPUT.relative_to(ROOT)} — أحدث درس: {build()}")
