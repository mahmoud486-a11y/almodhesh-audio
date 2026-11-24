"""درس المدهش متعدد المستويات: الخبر نفسه بثلاثة مستويات (مبتدئ، متوسط، متقدم).

الخطوات (كل خطوة مرة واحدة في اليوم):
1. جلب الأخبار مرة واحدة (نفس مصادر وسياسة daily_lesson).
2. طلب واحد لاختيار 6 أخبار واستخراج الحقائق فقط (نقاط قصيرة) — هذا يضمن تطابق الحقائق في المستويات الثلاثة.
3. طلب لكل مستوى يكتب الجمل من الحقائق بكلمات جديدة (لا يرى نص المقال)، مع الترجمة، و20 كلمة، و3 أسئلة فهم.
4. الصوت: ElevenLabs للمستويات المحددة في AUDIO_LEVELS فقط وضمن الحد اليومي؛ أي نص متطابق يعيد استخدام تسجيله.
   بقية المستويات تعمل بصوت المتصفح الأمريكي مجانًا.

المتغيرات:
  LESSON_LEVELS  المستويات التي تُكتب نصوصها بـ Claude (الافتراضي: الثلاثة). المستوى غير المفعّل يأخذ نص المتوسط.
  AUDIO_LEVELS   المستويات التي تُولّد تسجيلاتها بـ ElevenLabs (الافتراضي: intermediate فقط).
"""
from __future__ import annotations

import hashlib
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import daily_lesson as dl
from daily_lesson import (ARABIC, CATEGORIES, MAX_MAJOR_EVENTS, MENA_COUNTRIES, MENA_KEYWORDS, MIN_CATEGORIES,
                          STORIES, WORDS, read_json, summary, tokens, write_json)

LEVEL_ORDER = ["beginner", "intermediate", "advanced"]
DEFAULT_LEVEL = "intermediate"
EXERCISES = 3
LEVELS = {
    "beginner": {
        "ar": "مبتدئ", "cefr": "A1–A2", "en_min": 30, "en_max": 95,
        "style": "CEFR A1–A2. ONE short sentence (8–15 words), present or past simple, the 1,500 most common English "
                 "words, no idioms, no passive voice. Vocabulary: concrete everyday words. Comprehension questions "
                 "are very simple (who / what / where) with short options.",
    },
    "intermediate": {
        "ar": "متوسط", "cefr": "B1–B2", "en_min": 60, "en_max": 140,
        "style": "CEFR B1–B2. ONE natural sentence (14–24 words) that may use a relative clause, present perfect or "
                 "passive voice. Vocabulary: common news and work words. Comprehension questions check the main "
                 "idea and one detail.",
    },
    "advanced": {
        "ar": "متقدم", "cefr": "C1–C2", "en_min": 90, "en_max": 230,
        "style": "CEFR C1–C2. One or two sophisticated sentences (22–38 words in total) in a professional news "
                 "register: complex clauses, precise and formal vocabulary, natural collocations. Vocabulary: "
                 "advanced and academic words. Comprehension questions test inference, cause and effect, or "
                 "the meaning of a phrase in context.",
    },
}


def mirror_default(lesson: dict) -> None:
    """نسخة من المستوى المتوسط بالصيغة القديمة (stories/words/translations/audio) في أعلى الدرس،
    حتى يعمل الموقع والأدوات القديمة لو تم الرجوع إلى النسخة السابقة من الكود."""
    v = lesson["levels"][lesson.get("default_level", DEFAULT_LEVEL)]
    for k in ("stories", "words", "translations", "audio"):
        lesson[k] = v[k]


def env_levels(name: str, default: list[str]) -> list[str]:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    levels = [l.strip().lower() for l in raw.split(",") if l.strip()]
    return [l for l in LEVEL_ORDER if l in levels] or default


# ---------------------------------------------------------------- الخطوة 1: اختيار الأخبار واستخراج الحقائق
FACTS_SCHEMA = {
    "type": "object",
    "properties": {
        "archive_title": {"type": "string"},
        "stories": {"type": "array", "items": {
            "type": "object",
            "properties": {
                "news_id": {"type": "integer"},
                "category": {"type": "string", "enum": CATEGORIES},
                "country": {"type": "string", "enum": MENA_COUNTRIES},
                "topic": {"type": "string"},
                "facts": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["news_id", "category", "country", "topic", "facts"],
            "additionalProperties": False,
        }},
    },
    "required": ["archive_title", "stories"],
    "additionalProperties": False,
}

FACTS_PROMPT = """You choose the daily news for "Almodhesh" (المدهش), a website where Arabic speakers learn American English from news.

From the numbered news list, choose exactly 6 stories. Selection policy (mandatory):
- Every story must be about the Middle East and North Africa (MENA): it must happen in, or directly concern, a MENA country. Countries elsewhere in Africa (for example Senegal, Nigeria, Kenya) are NOT MENA. Set "country" to that country, or "MENA region" for a story about several of them.
- Cover at least 4 different categories from economy, technology, health, education, science, sport, culture and major event. Prefer positive, practical and human-interest news: business and jobs, innovation, health care, schools and universities, research, sports results, arts, heritage, travel and food.
- Use the category "major event" for wars, conflicts, attacks, elections, diplomacy and other political news. Include at most ONE such story, only if it is truly major, and keep it neutral without graphic details.
- Avoid opinion pieces, rumors, crime stories and sensational news. Prefer different sources and different countries.

For each story give:
- "news_id": the number of the item.
- "category" and "country": as defined above.
- "topic": a short Arabic title of 2–4 words.
- "facts": 2 to 4 short factual statements in plain English, using only information stated in that item (who, what, where, when, numbers). Write them as neutral notes in your own words, not quotes. The first fact must name the MENA country, city or people. Never invent details.

Also give "archive_title": the 6 topics as short Arabic categories joined with "، " and "و" before the last, e.g. "اقتصاد، صحة، تعليم، علوم، رياضة وثقافة".
"""


def facts_prompt(items, feedback):
    lines = [f"Today is {dl.now_local():%A, %B %d, %Y}.", "", "News list:"]
    lines += [f"[{it.id}] {it.source_ar} | {it.published[:10]} | {it.title} — {it.summary}" for it in items]
    if feedback:
        lines += ["", "Your previous answer was rejected. Fix these problems:"] + [f"- {f}" for f in feedback]
    return "\n".join(lines)


def mentions_mena(text: str) -> bool:
    text = " " + re.sub(r"[^a-zà-ÿ' -]", " ", text.lower()) + " "
    return any(re.search(rf"(?<![a-zà-ÿ]){re.escape(k)}(?![a-zà-ÿ])", text) for k in MENA_KEYWORDS)


def validate_facts(data: dict, items) -> list[str]:
    errors = []
    by_id = {i.id: i for i in items}
    stories = data.get("stories", [])
    if len(stories) != STORIES:
        errors.append(f"need exactly {STORIES} stories, got {len(stories)}")
    ids = [s.get("news_id") for s in stories]
    if len(set(ids)) != len(ids):
        errors.append("each story must use a different news_id")
    for n, s in enumerate(stories, 1):
        if s.get("news_id") not in by_id:
            errors.append(f"story {n}: news_id {s.get('news_id')} is not in the list")
        if s.get("country") not in MENA_COUNTRIES:
            errors.append(f"story {n}: must be about a MENA country (got {s.get('country')!r})")
        if s.get("category") not in CATEGORIES:
            errors.append(f"story {n}: invalid category {s.get('category')!r}")
        facts = [f for f in s.get("facts", []) if isinstance(f, str) and f.strip()]
        if not 2 <= len(facts) <= 4:
            errors.append(f"story {n}: give 2 to 4 facts")
        if any(ARABIC.search(f) for f in facts):
            errors.append(f"story {n}: facts must be in English")
        if facts and not mentions_mena(" ".join(facts)):
            errors.append(f"story {n}: the facts must name the MENA country, city or people")
        if not ARABIC.search(s.get("topic", "")):
            errors.append(f"story {n}: Arabic topic missing")
    cats = [s.get("category") for s in stories]
    if len(set(cats)) < MIN_CATEGORIES:
        errors.append(f"use at least {MIN_CATEGORIES} different categories (got {len(set(cats))})")
    if cats.count("major event") > MAX_MAJOR_EVENTS:
        errors.append(f"at most {MAX_MAJOR_EVENTS} 'major event' story; replace the others with economy, technology, "
                      "health, education, science, sport or culture news")
    if not ARABIC.search(data.get("archive_title", "")):
        errors.append("archive_title must be Arabic")
    return errors


# ---------------------------------------------------------------- الخطوة 2: نص كل مستوى
LEVEL_SCHEMA = {
    "type": "object",
    "properties": {
        "stories": {"type": "array", "items": {
            "type": "object",
            "properties": {"en": {"type": "string"}, "ar": {"type": "string"}},
            "required": ["en", "ar"], "additionalProperties": False}},
        "words": {"type": "array", "items": {
            "type": "object",
            "properties": {"en": {"type": "string"}, "ar": {"type": "string"}},
            "required": ["en", "ar"], "additionalProperties": False}},
        "translations": {"type": "array", "items": {
            "type": "object",
            "properties": {"word": {"type": "string"}, "ar": {"type": "string"}},
            "required": ["word", "ar"], "additionalProperties": False}},
        "exercises": {"type": "array", "items": {
            "type": "object",
            "properties": {
                "question": {"type": "string"},
                "question_ar": {"type": "string"},
                "options": {"type": "array", "items": {"type": "string"}},
                "answer": {"type": "integer"},
            },
            "required": ["question", "question_ar", "options", "answer"], "additionalProperties": False}},
    },
    "required": ["stories", "words", "translations", "exercises"],
    "additionalProperties": False,
}

LEVEL_PROMPT = """You write one level of the daily lesson for "Almodhesh" (المدهش), where Arabic speakers learn American English from news.

You receive 6 numbered stories, each with a few facts. Write ONLY from these facts: do not add, change or invent any fact, number, name or date, so all levels stay factually identical. Write in your own words; do not reproduce any source wording.

Level: {level_name} ({cefr}). {style}

Return:
- "stories": exactly 6 items in the same order. "en": American English ({en_min}–{en_max} characters, American spelling, ending with a period) that names the MENA country, city or people. "ar": a natural and accurate Modern Standard Arabic translation.
- "words": exactly 20 vocabulary words suited to this level. Each "en" is a single word copied exactly as it appears in your sentences (lowercase unless a proper noun); "ar" is its Arabic meaning in that sentence.
- "translations": an Arabic gloss for EVERY distinct word in your 6 sentences ("word" lowercase as it appears without surrounding punctuation, keeping apostrophes and hyphens).
- "exercises": exactly 3 multiple-choice comprehension questions about these stories, suited to this level. "question" in English, "question_ar" its Arabic translation, "options": exactly 4 short distinct English options, "answer": the index (0–3) of the correct option.
"""


def level_prompt(facts: dict, feedback) -> str:
    lines = ["Stories and facts:"]
    for n, s in enumerate(facts["stories"], 1):
        lines.append(f"{n}. [{s['category']}, {s['country']}] " + " ".join(f.strip() for f in s["facts"]))
    if feedback:
        lines += ["", "Your previous answer was rejected. Fix these problems:"] + [f"- {f}" for f in feedback]
    return "\n".join(lines)


def validate_level(data: dict, level: str, known: dict, budget: int | None) -> list[str]:
    cfg = LEVELS[level]
    errors = []
    stories, words, exercises = data.get("stories", []), data.get("words", []), data.get("exercises", [])
    if len(stories) != STORIES:
        errors.append(f"need exactly {STORIES} stories, got {len(stories)}")
    for n, s in enumerate(stories, 1):
        en = s.get("en", "").strip()
        if not cfg["en_min"] <= len(en) <= cfg["en_max"]:
            errors.append(f"story {n}: English must be {cfg['en_min']}-{cfg['en_max']} characters (got {len(en)})")
        if ARABIC.search(en):
            errors.append(f"story {n}: English text contains Arabic")
        if not ARABIC.search(s.get("ar", "")):
            errors.append(f"story {n}: Arabic translation missing")
        if en and not mentions_mena(en):
            errors.append(f"story {n}: the English text must name the MENA country, city or people")
    sentence_tokens = {t for s in stories for t in tokens(s.get("en", ""))}
    lowered = [w.get("en", "").strip().lower() for w in words]
    if len(words) != WORDS:
        errors.append(f"need exactly {WORDS} words, got {len(words)}")
    if len(set(lowered)) != len(lowered):
        errors.append("words must be distinct")
    for w in words:
        if w.get("en", "").strip().lower() not in sentence_tokens:
            errors.append(f"word '{w.get('en')}' does not appear in the sentences")
        if not ARABIC.search(w.get("ar", "")):
            errors.append(f"word '{w.get('en')}' has no Arabic meaning")
    glossary = {t.get("word", "").strip().lower() for t in data.get("translations", []) if ARABIC.search(t.get("ar", ""))}
    missing = [t for t in sentence_tokens if t not in glossary and t not in known]
    if len(missing) > max(2, len(sentence_tokens) // 20):
        errors.append(f"translations missing for: {', '.join(sorted(missing)[:25])}")
    if len(exercises) != EXERCISES:
        errors.append(f"need exactly {EXERCISES} exercises, got {len(exercises)}")
    for n, e in enumerate(exercises, 1):
        opts = [o.strip() for o in e.get("options", []) if isinstance(o, str) and o.strip()]
        if len(opts) != 4 or len(set(o.lower() for o in opts)) != 4:
            errors.append(f"exercise {n}: needs 4 distinct options")
        if not isinstance(e.get("answer"), int) or not 0 <= e["answer"] <= 3:
            errors.append(f"exercise {n}: answer must be 0-3")
        if not e.get("question", "").strip() or ARABIC.search(e.get("question", "")):
            errors.append(f"exercise {n}: question must be English")
        if not ARABIC.search(e.get("question_ar", "")):
            errors.append(f"exercise {n}: question_ar must be Arabic")
    if budget is not None:
        chars = dl.audio_chars(stories, [[w.get("en", ""), ""] for w in words])
        if chars > budget:
            errors.append(f"sentences + words total {chars} characters; must be at most {budget}. Shorten sentences")
    return errors


def build_level(data: dict, facts: dict, items, generated_by: str) -> dict:
    by_id = {i.id: i for i in items}
    stories = []
    for f, s in zip(facts["stories"], data["stories"]):
        item = by_id[f["news_id"]]
        published = item.published_dt.astimezone(ZoneInfo(dl.TIMEZONE))
        stories.append({"topic": f["topic"].strip(), "en": s["en"].strip(), "ar": s["ar"].strip(),
                        "source": f"{item.source_ar} · {dl.arabic_short_date(published)}",
                        "url": item.url})  # المصدر والرابط من الخلاصة نفسها، لا من النموذج
    words = [[w["en"].strip(), w["ar"].strip()] for w in data["words"]]
    translations = {}
    for t in data["translations"]:
        k = t["word"].strip().lower()
        if k and ARABIC.search(t["ar"]):
            translations.setdefault(k, t["ar"].strip())
    for en, ar in words:
        translations.setdefault(en.lower(), ar)
    exercises = [{"question": e["question"].strip(), "question_ar": e["question_ar"].strip(),
                  "options": [o.strip() for o in e["options"]], "answer": e["answer"]} for e in data["exercises"]]
    return {"stories": stories, "words": words, "translations": translations, "exercises": exercises,
            "audio": {"stories": None, "words": None}, "generated_by": generated_by}


def _ask(prompt_fn, validate_fn, system, schema, model, key, label, attempts=3):
    feedback, cost = [], 0.0
    for attempt in range(1, attempts + 1):
        print(f"{label}: طلب من {model} (محاولة {attempt}) ...")
        try:
            data, usage = dl.call_claude(prompt_fn(feedback), model, system=system, schema=schema)
        except Exception as e:  # noqa: BLE001
            print(f"  فشل الطلب: {dl.tts.sanitize(e)[:300]}")
            feedback = []
            time.sleep(10)
            continue
        cost += dl.record_ai_usage(key, {**usage, "step": label}, attempt)
        feedback = validate_fn(data)
        if not feedback:
            return data, cost
        print("  رُفض:\n   - " + "\n   - ".join(feedback[:12]))
    return None, cost


def prepare(day: datetime, model: str, daily_cap: int, text_levels: list[str], audio_levels: list[str]) -> dict | None:
    key = day.strftime("%Y-%m-%d")
    path = dl.LESSONS_DIR / f"{key}.json"
    if path.exists():
        print(f"درس {key} موجود مسبقًا؛ لا حاجة لإعداده (لا تكلفة).")
        return read_json(path, None)
    print("جلب الأخبار:")
    items = dl.fetch_news()
    if len(items) < 12:
        summary(f"⚠️ عدد الأخبار الحديثة غير كافٍ ({len(items)})؛ يبقى آخر درس صالح.")
        return None

    facts, total = _ask(lambda fb: facts_prompt(items, fb), lambda d: validate_facts(d, items),
                        FACTS_PROMPT, FACTS_SCHEMA, model, key, "facts")
    if facts is None:
        summary("❌ تعذر اختيار أخبار صالحة. يبقى آخر درس صالح.")
        return None

    known = dl.known_translations()
    results: dict[str, dict] = {}
    # المتوسط أولًا: هو المستوى الافتراضي وبديل أي مستوى يفشل
    for level in sorted(text_levels, key=lambda l: l != DEFAULT_LEVEL):
        cfg = LEVELS[level]
        system = LEVEL_PROMPT.format(level_name=level, **{k: cfg[k] for k in ("cefr", "style", "en_min", "en_max")})
        budget = daily_cap if level in audio_levels else None
        data, cost = _ask(lambda fb: level_prompt(facts, fb), lambda d, lv=level, b=budget: validate_level(d, lv, known, b),
                          system, LEVEL_SCHEMA, model, key, level)
        total += cost
        if data is not None:
            results[level] = build_level(data, facts, items, "claude")
    if not results:
        summary(f"❌ تعذر إعداد أي مستوى (تكلفة ${total:.4f}). يبقى آخر درس صالح.")
        return None

    base = DEFAULT_LEVEL if DEFAULT_LEVEL in results else next(iter(results))
    levels = {}
    for level in LEVEL_ORDER:
        if level in results:
            levels[level] = results[level]
        else:  # المستوى غير المفعّل أو الذي فشل يعرض نص مستوى آخر (لا يتوقف الدرس)
            levels[level] = {**results[base], "same_as": base, "audio": {"stories": None, "words": None}}
    lesson = {
        "key": key,
        "date": dl.arabic_long_date(day),
        "archive_date": dl.arabic_short_date(day),
        "archive_title": facts["archive_title"].strip(),
        "default_level": DEFAULT_LEVEL,
        "facts": [{"news_id": s["news_id"], "category": s["category"], "country": s["country"], "facts": s["facts"]}
                  for s in facts["stories"]],
        "levels": levels,
        "generated": {"by": "claude", "at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")},
    }
    mirror_default(lesson)
    write_json(path, lesson)
    made = ", ".join(f"{LEVELS[l]['ar']}" + ("" if l in results else f" (=نص {LEVELS[base]['ar']})") for l in LEVEL_ORDER)
    summary(f"✅ أُعدّ درس {key} بالمستويات: {made} — تكلفة تقديرية ${total:.4f}")
    return lesson


# ---------------------------------------------------------------- الصوت
def level_paths(lesson: dict, level: str | None) -> tuple[list[str], list[str]]:
    key = lesson["key"]
    view = lesson["levels"][level] if level else lesson
    prefix = f"audio/{key}/{level}" if level else f"audio/{key}"  # الدروس القديمة بلا مستويات تحتفظ بمساراتها
    return ([f"{prefix}/news-{i}.mp3" for i in range(1, len(view["stories"]) + 1)],
            [f"{prefix}/words/word-{i:02d}.mp3" for i in range(1, len(view["words"]) + 1)])


def digest_of(text: str, voice_id: str, model_id: str) -> str:
    return hashlib.sha256(f"{voice_id}|{model_id}|{text}".encode()).hexdigest()


def existing_by_digest(manifest: dict) -> dict:
    return {v["sha256"]: rel for rel, v in manifest.items() if (dl.SITE / rel).exists()}


def attach(lesson: dict, level: str | None, voice_id: str, model_id: str, manifest: dict) -> None:
    """يربط كل جملة وكلمة بتسجيلها إن وُجد — بما فيها تسجيل لنص مطابق في درس أو مستوى آخر."""
    view = lesson["levels"][level] if level else lesson
    known = existing_by_digest(manifest)
    s_paths, w_paths = level_paths(lesson, level)
    def resolve(own, text):
        if (dl.SITE / own).exists():
            return own
        return known.get(digest_of(text, voice_id, model_id))
    s = [resolve(p, st["en"]) for p, st in zip(s_paths, view["stories"])]
    w = [resolve(p, wd[0]) for p, wd in zip(w_paths, view["words"])]
    view["audio"] = {"stories": s if any(s) else None, "words": w if any(w) else None}


def generate_audio(daily_cap: int, audio_levels: list[str]) -> bool:
    path = dl.latest_lesson_path()
    lesson = read_json(path, None)
    voice_id = os.environ.get("ELEVENLABS_LESSON_VOICE_ID", "").strip() or dl.DEFAULT_LESSON_VOICE
    model_id = os.environ.get("ELEVENLABS_LESSON_MODEL_ID", "").strip() or dl.DEFAULT_TTS_MODEL
    manifest = read_json(dl.AUDIO_MANIFEST, {})
    targets = [l for l in LEVEL_ORDER if l in audio_levels] if "levels" in lesson else [None]
    targets.sort(key=lambda l: l != DEFAULT_LEVEL)  # المتوسط أولًا

    # التسجيلات الناقصة فقط، مع إعادة استخدام أي تسجيل لنص مطابق، ودون تكرار النص نفسه في التشغيلة
    jobs, planned = [], set()
    known = existing_by_digest(manifest)
    for level in targets:
        view = lesson["levels"][level] if level else lesson
        s_paths, w_paths = level_paths(lesson, level)
        for rel, text in list(zip(s_paths, [s["en"] for s in view["stories"]])) + \
                         list(zip(w_paths, [w[0] for w in view["words"]])):
            d = digest_of(text, voice_id, model_id)
            if (dl.SITE / rel).exists() or d in known or d in planned:
                continue
            planned.add(d)
            jobs.append((rel, text, d))

    def finish():
        for level in ([l for l in LEVEL_ORDER] if "levels" in lesson else [None]):
            attach(lesson, level, voice_id, model_id, manifest)
        if "levels" in lesson:
            mirror_default(lesson)
        write_json(path, lesson)

    if not jobs:
        print(f"كل تسجيلات درس {lesson['key']} المطلوبة موجودة؛ لا استهلاك.")
        finish()
        return True

    usage = dl.tts.load_usage(dl.USAGE_PATH)
    today = dl.tts.local_date(dl.TIMEZONE)
    available = max(0, daily_cap - int(usage.get(today, 0)))
    selected, total = [], 0
    for job in jobs:
        if total + len(job[1]) <= available:
            selected.append(job)
            total += len(job[1])
    print(f"التسجيلات الناقصة: {len(jobs)} | المتاح اليوم: {available} من {daily_cap} | سيُولَّد: {len(selected)} ({total} حرف)")
    api_key = os.environ.get("ELEVENLABS_API_KEY", "").strip()
    if not selected or not api_key:
        summary("⚠️ لا يتسع الحد اليومي أو لا يوجد مفتاح ElevenLabs؛ الجمل الناقصة تعمل بصوت المتصفح.")
        finish()
        return False
    remaining = dl.tts.remaining_characters(api_key)
    if remaining is None or remaining < total:
        summary(f"⚠️ رصيد ElevenLabs غير كافٍ أو تعذّر فحصه (المطلوب: {total} حرف). لم يُولَّد صوت.")
        finish()
        return False

    done = failed = 0
    for rel, text, d in selected:
        try:
            audio = dl.tts.synthesize(text, api_key, voice_id, model_id, "mp3_44100_128")
        except RuntimeError as e:
            failed += 1
            print(f"  فشل {rel}: {dl.tts.sanitize(e)}")
            if "HTTP 401" in str(e) or "quota_exceeded" in str(e):
                break
            continue
        (dl.SITE / rel).parent.mkdir(parents=True, exist_ok=True)
        (dl.SITE / rel).write_bytes(audio)
        manifest[rel] = {"sha256": d, "chars": len(text), "voice_id": voice_id, "model_id": model_id}
        usage[today] = int(usage.get(today, 0)) + len(text)
        write_json(dl.AUDIO_MANIFEST, manifest)
        dl.tts.save_usage(usage, dl.USAGE_PATH)
        done += 1
    finish()
    missing = len(jobs) - done
    summary(f"🔊 صوت درس {lesson['key']}: وُلّد {done}، فشل {failed}، ناقص {missing} "
            f"(استُخدم اليوم {usage.get(today, 0)} من {daily_cap} حرف)")
    return missing == 0
