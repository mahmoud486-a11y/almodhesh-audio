#!/usr/bin/env python3
"""إعداد درس المدهش اليومي: أخبار موثوقة ← درس بالذكاء الاصطناعي ← صوت ElevenLabs ← بيانات الموقع.

الأوامر:
  news     جلب الأخبار من مصادر RSS موثوقة وعرضها فقط (مجاني).
  prepare  إعداد درس اليوم بواسطة Claude وحفظه في site/lessons/DATE.json (تكلفة Claude فقط).
  audio    توليد الصوت الناقص لأحدث درس ضمن الحد اليومي (يستهلك رصيد ElevenLabs).
  build    إعادة بناء site/lessons-data.js.
  run      كل ما سبق بالترتيب. لا يُنشر درس إلا إذا اجتاز كل الفحوص؛ وإلا يبقى آخر درس صالح.

المفاتيح تُقرأ من متغيرات البيئة فقط: ANTHROPIC_API_KEY و ELEVENLABS_API_KEY.
"""
from __future__ import annotations

import argparse
import hashlib
import html
import json
import os
import re
import sys
import time
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent))
import build_site_data  # noqa: E402
import generate_audio as tts  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
SITE = ROOT / "site"
LESSONS_DIR = SITE / "lessons"
SITE_AUDIO = SITE / "audio"
AUDIO_MANIFEST = SITE_AUDIO / "manifest.json"
USAGE_PATH = ROOT / "audio" / "usage.json"  # سجل الاستهلاك اليومي المشترك مع generate_audio.py
AI_USAGE_PATH = ROOT / "logs" / "ai-usage.json"
TIMEZONE = "America/Toronto"

DEFAULT_LESSON_MODEL = "claude-opus-5-5"
# الأسعار بالدولار لكل مليون رمز (مدخلات، مخرجات) لتقدير التكلفة في السجل
MODEL_PRICES = {
    "claude-opus-5-5": (4.00, 20.00),
    "claude-sonnet-5-5": (2.00, 10.00),
    "claude-haiku-5-5": (0.10, 0.50),
}
FALLBACK_MODELS = ("claude-opus-5-5", "claude-sonnet-5-5")  # تدعم fallbacks من جهة الخادم

DEFAULT_TTS_MODEL = "eleven_multilingual_v2"
DEFAULT_LESSON_VOICE = "21m00Tcm4TlvDq8ikWAM"  # صوت أمريكي جاهز؛ يُستبدل بـ ELEVENLABS_LESSON_VOICE_ID

STORIES = 6
WORDS = 20
EN_MIN, EN_MAX = 40, 125
DAILY_MAX_CHARS = 1000
MAX_AGE_DAYS = 4

WEEKDAYS_AR = ["الاثنين", "الثلاثاء", "الأربعاء", "الخميس", "الجمعة", "السبت", "الأحد"]
MONTHS_AR = ["يناير", "فبراير", "مارس", "أبريل", "مايو", "يونيو", "يوليو",
             "أغسطس", "سبتمبر", "أكتوبر", "نوفمبر", "ديسمبر"]

# مصادر رسمية ووكالات معروفة لها خلاصات RSS/Atom عامة
FEEDS = [
    ("https://news.un.org/feed/subscribe/en/news/all/rss.xml", "الأمم المتحدة"),
    ("https://www.who.int/rss-feeds/news-english.xml", "منظمة الصحة العالمية"),
    ("https://www.nasa.gov/news-release/feed/", "ناسا"),
    ("https://www.esa.int/rssfeed/TopNews", "وكالة الفضاء الأوروبية"),
    ("https://feeds.bbci.co.uk/news/world/rss.xml", "بي بي سي"),
    ("https://feeds.bbci.co.uk/news/science_and_environment/rss.xml", "بي بي سي"),
    ("https://feeds.bbci.co.uk/news/technology/rss.xml", "بي بي سي"),
    ("https://feeds.npr.org/1001/rss.xml", "إن بي آر"),
    ("https://www.cbc.ca/webfeed/rss/rss-topstories", "سي بي سي"),
    ("https://www.cbc.ca/webfeed/rss/rss-canada", "سي بي سي"),
    ("https://www.sciencedaily.com/rss/top/science.xml", "ساينس ديلي"),
]

TOKEN_EDGE = re.compile(r"^[^A-Za-zÀ-ÿ]+|[^A-Za-zÀ-ÿ'-]+$")  # نفس قاعدة الموقع في app.js
ARABIC = re.compile(r"[؀-ۿ]")


# ---------------------------------------------------------------- أدوات عامة
def now_local() -> datetime:
    return datetime.now(ZoneInfo(TIMEZONE))


def arabic_long_date(d: datetime) -> str:
    return f"{WEEKDAYS_AR[d.weekday()]}، {d.day} {MONTHS_AR[d.month - 1]} {d.year}"


def arabic_short_date(d: datetime) -> str:
    return f"{d.day} {MONTHS_AR[d.month - 1]} {d.year}"


def tokens(sentence: str) -> list[str]:
    out = []
    for part in sentence.split():
        clean = TOKEN_EDGE.sub("", part)
        if clean:
            out.append(clean.lower())
    return out


def read_json(path: Path, default):
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else default


def write_json(path: Path, data, indent=1) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=indent) + "\n", encoding="utf-8")


def summary(line: str) -> None:
    """يطبع ويضيف إلى ملخص تشغيلة GitHub Actions إن وُجد."""
    print(line)
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if path:
        with open(path, "a", encoding="utf-8") as f:
            f.write(line + "\n\n")


# ---------------------------------------------------------------- الأخبار
@dataclass
class NewsItem:
    id: int
    source_ar: str
    title: str
    summary: str
    url: str
    published: str  # ISO

    @property
    def published_dt(self) -> datetime:
        return datetime.fromisoformat(self.published)


def _text(el) -> str:
    raw = (el.text or "") if el is not None else ""
    raw = re.sub(r"<[^>]+>", " ", html.unescape(raw))
    return re.sub(r"\s+", " ", raw).strip()


def _parse_date(value: str) -> datetime | None:
    value = (value or "").strip()
    if not value:
        return None
    try:
        dt = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        try:
            dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def parse_feed(xml_bytes: bytes, source_ar: str) -> list[dict]:
    root = ET.fromstring(xml_bytes)
    items = []
    for el in root.iter():
        tag = el.tag.split("}")[-1]
        if tag not in ("item", "entry"):
            continue
        child = {c.tag.split("}")[-1]: c for c in el}
        link = ""
        if "link" in child:
            link = child["link"].get("href") or (child["link"].text or "")
        for c in el:  # Atom: rel="alternate"
            if c.tag.split("}")[-1] == "link" and c.get("rel", "alternate") == "alternate" and c.get("href"):
                link = c.get("href")
                break
        date = None
        for key in ("pubDate", "published", "updated", "date"):
            if key in child:
                date = _parse_date(child[key].text)
                if date:
                    break
        title = _text(child.get("title"))
        desc_el = next((child[k] for k in ("description", "summary", "content") if k in child), None)
        desc = _text(desc_el)
        if title and link.startswith("https://") and date:
            items.append({"source_ar": source_ar, "title": title, "summary": desc[:400],
                          "url": link.strip(), "published": date.isoformat()})
    return items


def fetch_news(feeds=FEEDS, max_age_days=MAX_AGE_DAYS, per_feed=12) -> list[NewsItem]:
    cutoff = datetime.now(timezone.utc) - timedelta(days=max_age_days)
    seen, collected = set(), []
    for url, source_ar in feeds:
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (almodhesh-lessons)"})
            with urllib.request.urlopen(req, timeout=30) as resp:
                items = parse_feed(resp.read(), source_ar)
        except Exception as e:  # noqa: BLE001 — مصدر واحد معطّل لا يوقف الدرس
            print(f"  تخطي مصدر ({source_ar}) {url}: {str(e)[:120]}")
            continue
        fresh = [i for i in items if _parse_date(i["published"]) >= cutoff]
        fresh.sort(key=lambda i: i["published"], reverse=True)
        added = 0
        for item in fresh:
            if item["url"] in seen or added >= per_feed:
                continue
            seen.add(item["url"])
            collected.append(item)
            added += 1
        print(f"  {source_ar}: {added} خبر حديث ({url})")
    collected.sort(key=lambda i: i["published"], reverse=True)
    return [NewsItem(id=n, **item) for n, item in enumerate(collected, 1)]


# ---------------------------------------------------------------- إعداد الدرس بـ Claude
LESSON_SCHEMA = {
    "type": "object",
    "properties": {
        "archive_title": {"type": "string"},
        "stories": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "news_id": {"type": "integer"},
                    "topic": {"type": "string"},
                    "en": {"type": "string"},
                    "ar": {"type": "string"},
                },
                "required": ["news_id", "topic", "en", "ar"],
                "additionalProperties": False,
            },
        },
        "words": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"en": {"type": "string"}, "ar": {"type": "string"}},
                "required": ["en", "ar"],
                "additionalProperties": False,
            },
        },
        "translations": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"word": {"type": "string"}, "ar": {"type": "string"}},
                "required": ["word", "ar"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["archive_title", "stories", "words", "translations"],
    "additionalProperties": False,
}

SYSTEM_PROMPT = """You write the daily lesson for "Almodhesh" (المدهش), a website where Arabic speakers learn American English from today's news at CEFR level A2–B1.

From the numbered news list, choose exactly 6 stories:
- recent, factual, and from different sources and topics (for example science, space, health, environment, technology, economy, Canada, world, education, sport);
- avoid graphic violence and sensational or opinion pieces; keep politics neutral and factual.

For each story write:
- "news_id": the number of the item you used. Every fact must come from that item only. Never invent details.
- "en": ONE simple American English sentence that states the main fact, 60–115 characters, ending with a period. Use common words, present or past simple, American spelling. Spell numbers as digits or simple words.
- "ar": a natural Modern Standard Arabic translation of that sentence.
- "topic": a short Arabic title of 2–4 words.

Then:
- "words": exactly 20 useful vocabulary words. Each "en" must be a single word copied exactly as it appears inside one of your 6 sentences (lowercase unless a proper noun). Prefer verbs, nouns and adjectives a learner needs; no "the", "a", "and", or names unless important. "ar": its Arabic meaning in that sentence.
- "translations": an Arabic gloss for EVERY distinct word in the 6 sentences (lowercase "word" exactly as it appears without surrounding punctuation, keeping apostrophes and hyphens, e.g. "nasa's", "long-term").
- "archive_title": the 6 topics as short Arabic categories joined with "، " and "و" before the last, e.g. "بيئة، فضاء، سلامة، صحة، تقنية وقوانين".

Style examples from a previous lesson:
- en: "NASA's Curiosity rover photographed drifting clouds after sunset on Mars." ar: "صوّرت مركبة كيريوسيتي التابعة لناسا غيوماً منجرفة بعد غروب الشمس على المريخ." topic: "غيوم فوق المريخ"
- en: "The WHO issued its first guidelines for diagnosing and treating type 1 diabetes in adults." ar: "أصدرت منظمة الصحة العالمية أول إرشادات لها لتشخيص وعلاج السكري من النوع الأول لدى البالغين." topic: "إرشادات جديدة للسكري"
"""


def news_prompt(items: list[NewsItem], budget: int, feedback: list[str]) -> str:
    lines = [f"Today is {now_local():%A, %B %d, %Y}. Audio budget: the 6 sentences plus the 20 words "
             f"must total at most {budget} characters.", "", "News list:"]
    for it in items:
        lines.append(f"[{it.id}] {it.source_ar} | {it.published[:10]} | {it.title} — {it.summary}")
    if feedback:
        lines += ["", "Your previous answer was rejected. Fix these problems:"] + [f"- {f}" for f in feedback]
    return "\n".join(lines)


def call_claude(prompt: str, model: str) -> tuple[dict, dict]:
    import anthropic  # يُستورد هنا حتى تعمل الأوامر الأخرى دون المكتبة

    client = anthropic.Anthropic()  # يقرأ ANTHROPIC_API_KEY من البيئة
    kwargs = dict(
        model=model,
        max_tokens=16000,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": prompt}],
        output_config={"effort": "medium", "format": {"type": "json_schema", "schema": LESSON_SCHEMA}},
    )
    if model in FALLBACK_MODELS:
        # عند رفض نادر من مصنّفات الأمان يعيد الخادم المحاولة على نموذج بديل تلقائيًا
        response = client.beta.messages.create(
            betas=["server-side-fallback-2026-07-01"], fallbacks="default", **kwargs)
    else:
        response = client.messages.create(**kwargs)
    if response.stop_reason == "refusal":
        raise RuntimeError(f"رفض النموذج الطلب: {getattr(response, 'stop_details', None)}")
    if response.stop_reason == "max_tokens":
        raise RuntimeError("انقطع رد النموذج (max_tokens)")
    text = next(b.text for b in response.content if b.type == "text")
    usage = {"input_tokens": response.usage.input_tokens, "output_tokens": response.usage.output_tokens,
             "model": response.model, "request_id": getattr(response, "_request_id", None)}
    return json.loads(text), usage


def validate_lesson(data: dict, items: list[NewsItem], budget: int, known: dict) -> list[str]:
    errors = []
    by_id = {i.id: i for i in items}
    stories = data.get("stories", [])
    words = data.get("words", [])
    if len(stories) != STORIES:
        errors.append(f"need exactly {STORIES} stories, got {len(stories)}")
    ids = [s.get("news_id") for s in stories]
    if len(set(ids)) != len(ids):
        errors.append("each story must use a different news_id")
    for n, s in enumerate(stories, 1):
        if s.get("news_id") not in by_id:
            errors.append(f"story {n}: news_id {s.get('news_id')} is not in the list")
        en = s.get("en", "").strip()
        if not (EN_MIN <= len(en) <= EN_MAX):
            errors.append(f"story {n}: English sentence must be {EN_MIN}-{EN_MAX} characters (got {len(en)})")
        if ARABIC.search(en):
            errors.append(f"story {n}: English sentence contains Arabic")
        if not ARABIC.search(s.get("ar", "")) or not ARABIC.search(s.get("topic", "")):
            errors.append(f"story {n}: Arabic translation/topic missing")
    sentence_tokens = {t for s in stories for t in tokens(s.get("en", ""))}
    if len(words) != WORDS:
        errors.append(f"need exactly {WORDS} words, got {len(words)}")
    lowered = [w.get("en", "").strip().lower() for w in words]
    if len(set(lowered)) != len(lowered):
        errors.append("words must be distinct")
    for w in words:
        if w.get("en", "").strip().lower() not in sentence_tokens:
            errors.append(f"word '{w.get('en')}' does not appear in the sentences")
        if not ARABIC.search(w.get("ar", "")):
            errors.append(f"word '{w.get('en')}' has no Arabic meaning")
    chars = audio_chars(stories, [[w.get("en", ""), w.get("ar", "")] for w in words])
    if chars > budget:
        errors.append(f"sentences + words total {chars} characters; must be at most {budget}. Shorten sentences")
    glossary = {t["word"].strip().lower(): t["ar"] for t in data.get("translations", []) if ARABIC.search(t.get("ar", ""))}
    missing = [t for t in sentence_tokens if t not in glossary and t not in known]
    if len(missing) > max(2, len(sentence_tokens) // 20):
        errors.append(f"translations missing for: {', '.join(sorted(missing)[:25])}")
    if not ARABIC.search(data.get("archive_title", "")):
        errors.append("archive_title must be Arabic")
    return errors


def audio_chars(stories: list[dict], words: list[list[str]]) -> int:
    return sum(len(s["en"].strip()) for s in stories) + sum(len(w[0].strip()) for w in words)


def to_lesson(data: dict, items: list[NewsItem], day: datetime) -> dict:
    by_id = {i.id: i for i in items}
    stories = []
    for s in data["stories"]:
        item = by_id[s["news_id"]]
        published = item.published_dt.astimezone(ZoneInfo(TIMEZONE))
        stories.append({
            "topic": s["topic"].strip(),
            "en": s["en"].strip(),
            "ar": s["ar"].strip(),
            "source": f"{item.source_ar} · {arabic_short_date(published)}",
            "url": item.url,  # الرابط من الخلاصة نفسها، وليس من النموذج
        })
    words = [[w["en"].strip(), w["ar"].strip()] for w in data["words"]]
    translations = {}
    for t in data["translations"]:
        key = t["word"].strip().lower()
        if key and ARABIC.search(t["ar"]):
            translations.setdefault(key, t["ar"].strip())
    for en, ar in words:
        translations.setdefault(en.lower(), ar)
    return {
        "key": day.strftime("%Y-%m-%d"),
        "date": arabic_long_date(day),
        "archive_date": arabic_short_date(day),
        "archive_title": data["archive_title"].strip(),
        "stories": stories,
        "words": words,
        "translations": translations,
        "audio": {"stories": None, "words": None},
        "generated": {"by": "claude", "at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")},
    }


def record_ai_usage(day: str, usage: dict, attempt: int) -> float:
    inp, out = MODEL_PRICES.get(usage["model"], MODEL_PRICES.get(DEFAULT_LESSON_MODEL))
    cost = usage["input_tokens"] / 1e6 * inp + usage["output_tokens"] / 1e6 * out
    log = read_json(AI_USAGE_PATH, [])
    log.append({"date": day, "attempt": attempt, **usage, "est_cost_usd": round(cost, 5)})
    write_json(AI_USAGE_PATH, log[-400:])
    return cost


def known_translations() -> dict:
    lessons = build_site_data.load_lessons(LESSONS_DIR)
    return build_site_data.merged_translations(lessons, LESSONS_DIR / "_base-translations.json")


def prepare(day: datetime, model: str, budget: int, attempts: int = 3) -> dict | None:
    key = day.strftime("%Y-%m-%d")
    path = LESSONS_DIR / f"{key}.json"
    if path.exists():
        print(f"درس {key} موجود مسبقًا؛ لا حاجة لإعداده (لا تكلفة).")
        return read_json(path, None)
    print("جلب الأخبار:")
    items = fetch_news()
    if len(items) < 12:
        summary(f"⚠️ عدد الأخبار الحديثة غير كافٍ ({len(items)})؛ يبقى آخر درس صالح.")
        return None
    known = known_translations()
    feedback: list[str] = []
    total_cost = 0.0
    for attempt in range(1, attempts + 1):
        print(f"طلب الدرس من {model} (محاولة {attempt}) ...")
        try:
            data, usage = call_claude(news_prompt(items, budget, feedback), model)
        except Exception as e:  # noqa: BLE001
            print(f"  فشل الطلب: {str(e)[:300]}")
            feedback = []
            time.sleep(10)
            continue
        total_cost += record_ai_usage(key, usage, attempt)
        print(f"  الرموز: {usage['input_tokens']} مدخلات، {usage['output_tokens']} مخرجات")
        feedback = validate_lesson(data, items, budget, known)
        if not feedback:
            lesson = to_lesson(data, items, day)
            write_json(path, lesson)
            summary(f"✅ أُعدّ درس {key} ({audio_chars(lesson['stories'], lesson['words'])} حرف صوتي، "
                    f"تكلفة تقديرية ${total_cost:.4f})")
            return lesson
        print("  رُفض الدرس:\n   - " + "\n   - ".join(feedback))
    summary(f"❌ تعذر إعداد درس صالح بعد {attempts} محاولات (تكلفة ${total_cost:.4f}). يبقى آخر درس صالح.")
    return None


# ---------------------------------------------------------------- الصوت
def latest_lesson_path() -> Path:
    keys = sorted(p for p in LESSONS_DIR.glob("*.json") if build_site_data.KEY_RE.match(p.stem))
    return keys[-1]


def audio_jobs(lesson: dict, voice_id: str, model_id: str, manifest: dict) -> list[tuple[str, str, str]]:
    """(المسار النسبي، النص، البصمة) لكل تسجيل ناقص. القصص أولًا ثم الكلمات."""
    key = lesson["key"]
    wanted = [(f"audio/{key}/news-{i}.mp3", s["en"]) for i, s in enumerate(lesson["stories"], 1)]
    wanted += [(f"audio/{key}/words/word-{i:02d}.mp3", w[0]) for i, w in enumerate(lesson["words"], 1)]
    jobs = []
    for rel, text in wanted:
        digest = hashlib.sha256(f"{voice_id}|{model_id}|{text}".encode()).hexdigest()
        if (SITE / rel).exists() and manifest.get(rel, {}).get("sha256") == digest:
            continue
        jobs.append((rel, text, digest))
    return jobs


def attach_audio(lesson: dict, manifest: dict) -> None:
    key = lesson["key"]
    stories = [f"audio/{key}/news-{i}.mp3" for i in range(1, len(lesson["stories"]) + 1)]
    words = [f"audio/{key}/words/word-{i:02d}.mp3" for i in range(1, len(lesson["words"]) + 1)]
    # null لكل تسجيل غير موجود ← يستخدم الموقع صوت المتصفح لهذه الجملة فقط
    s = [p if (SITE / p).exists() else None for p in stories]
    w = [p if (SITE / p).exists() else None for p in words]
    lesson["audio"] = {"stories": s if any(s) else None, "words": w if any(w) else None}


def generate_audio(daily_cap: int = DAILY_MAX_CHARS) -> bool:
    path = latest_lesson_path()
    lesson = read_json(path, None)
    voice_id = os.environ.get("ELEVENLABS_LESSON_VOICE_ID", "").strip() or DEFAULT_LESSON_VOICE
    model_id = os.environ.get("ELEVENLABS_LESSON_MODEL_ID", "").strip() or DEFAULT_TTS_MODEL
    manifest = read_json(AUDIO_MANIFEST, {})
    jobs = audio_jobs(lesson, voice_id, model_id, manifest)
    if not jobs:
        print(f"كل تسجيلات درس {lesson['key']} موجودة؛ لا استهلاك.")
        attach_audio(lesson, manifest)
        write_json(path, lesson)
        return True

    usage = tts.load_usage(USAGE_PATH)
    today = tts.local_date(TIMEZONE)
    available = max(0, daily_cap - int(usage.get(today, 0)))
    needed = sum(len(t) for _, t, _ in jobs)
    print(f"التسجيلات الناقصة: {len(jobs)} | الأحرف المطلوبة: {needed} | المتاح اليوم: {available} من {daily_cap}")
    selected, total = [], 0
    for job in jobs:  # بالترتيب: القصص أولًا
        if total + len(job[1]) <= available:
            selected.append(job)
            total += len(job[1])
    if not selected:
        summary(f"⚠️ الحد اليومي لا يسمح بتوليد الصوت الآن (المتاح {available}). الدرس يعمل بصوت المتصفح.")
        attach_audio(lesson, manifest)
        write_json(path, lesson)
        return False

    api_key = os.environ.get("ELEVENLABS_API_KEY", "").strip()
    if not api_key:
        summary("⚠️ لم يُضبط ELEVENLABS_API_KEY؛ الدرس يعمل بصوت المتصفح.")
        return False
    remaining = tts.remaining_characters(api_key)
    if remaining is None or remaining < total:
        summary(f"⚠️ الرصيد غير كافٍ أو تعذّر فحصه (المتبقي: {remaining}، المطلوب: {total}). لم يُولَّد صوت.")
        attach_audio(lesson, manifest)
        write_json(path, lesson)
        return False
    print(f"الرصيد المتبقي في ElevenLabs: {remaining} | سيُولَّد {len(selected)} تسجيل ({total} حرف)")

    done, failed = 0, 0
    for rel, text, digest in selected:
        try:
            audio = tts.synthesize(text, api_key, voice_id, model_id, "mp3_44100_128")
        except RuntimeError as e:
            failed += 1
            print(f"  فشل {rel}: {e}")
            if "HTTP 401" in str(e) or "quota_exceeded" in str(e):
                break
            continue
        (SITE / rel).parent.mkdir(parents=True, exist_ok=True)
        (SITE / rel).write_bytes(audio)
        manifest[rel] = {"sha256": digest, "chars": len(text), "voice_id": voice_id, "model_id": model_id}
        usage[today] = int(usage.get(today, 0)) + len(text)
        write_json(AUDIO_MANIFEST, manifest)  # حفظ فوري حتى لا يُعاد توليد ما نجح
        tts.save_usage(usage, USAGE_PATH)
        done += 1
    attach_audio(lesson, manifest)
    write_json(path, lesson)
    missing = len(jobs) - done
    summary(f"🔊 صوت درس {lesson['key']}: وُلّد {done} تسجيل، فشل {failed}، ناقص {missing} "
            f"(استُخدم اليوم {usage.get(today, 0)} من {daily_cap} حرف)")
    return missing == 0


# ---------------------------------------------------------------- التشغيل
def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("command", choices=["news", "prepare", "audio", "build", "run"])
    p.add_argument("--date", help="تاريخ الدرس YYYY-MM-DD (الافتراضي: اليوم بتوقيت أوتاوا)")
    p.add_argument("--daily-max-chars", type=int, default=DAILY_MAX_CHARS)
    args = p.parse_args(argv)

    day = now_local()
    if args.date:
        day = datetime.strptime(args.date, "%Y-%m-%d").replace(tzinfo=ZoneInfo(TIMEZONE))
    model = os.environ.get("LESSON_MODEL", "").strip() or DEFAULT_LESSON_MODEL

    if args.command == "news":
        items = fetch_news()
        print(f"\nالمجموع: {len(items)} خبر حديث")
        for it in items[:40]:
            print(f"[{it.id}] {it.source_ar} | {it.published[:16]} | {it.title}\n     {it.url}")
        return 0 if len(items) >= 12 else 1
    if args.command == "build":
        print(f"أحدث درس: {build_site_data.build(LESSONS_DIR, SITE / 'lessons-data.js')}")
        return 0

    today_exists = (LESSONS_DIR / f"{day:%Y-%m-%d}.json").exists()
    if args.command in ("prepare", "run") and not today_exists and not os.environ.get("ANTHROPIC_API_KEY"):
        summary("ℹ️ لم يُضبط ANTHROPIC_API_KEY بعد؛ لم يُعدّ درس جديد ولم يتغير شيء. يبقى آخر درس صالح منشورًا.")
        return 0

    ok = True
    if args.command in ("prepare", "run"):
        # حجم الدرس الصوتي لا يتجاوز الحد اليومي؛ والاستهلاك الفعلي يُفحص مرة أخرى قبل التوليد
        ok = prepare(day, model, args.daily_max_chars) is not None
    if args.command == "audio" or (args.command == "run" and ok):
        ok = generate_audio(args.daily_max_chars) and ok
    if args.command in ("run", "audio"):
        print(f"أحدث درس في الموقع: {build_site_data.build(LESSONS_DIR, SITE / 'lessons-data.js')}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
