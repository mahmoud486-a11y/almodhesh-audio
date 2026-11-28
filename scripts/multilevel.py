"""درس المدهش متعدد المستويات: الخبر نفسه بثلاثة مستويات (مبتدئ، متوسط، متقدم).

الخطوات (كل خطوة مرة واحدة في اليوم):
1. جلب الأخبار مرة واحدة (نفس مصادر وسياسة daily_lesson).
2. طلب واحد لاختيار 3 أخبار (سياسة، اقتصاد، صحة) واستخراج الحقائق فقط — هذا يضمن تطابق الحقائق في المستويات الثلاثة.
3. طلب لكل مستوى يكتب الجمل من الحقائق بكلمات جديدة (لا يرى نص المقال)، مع الترجمة، و20 كلمة، و3 أسئلة فهم.
   Haiku أولًا (حتى 3 محاولات)؛ فإن فشل التحقق فمحاولتان بـ Sonnet لذلك المستوى وحده، وبشرط أن تتسع الميزانية.
   لا يُنسخ نص مستوى إلى آخر أبدًا: إن تعذّر أي مستوى لا يُنشر الدرس ويبقى آخر درس صالح، وتفشل التشغيلة (تنبيه بالبريد).
4. التدقيق اللغوي العربي (Sonnet) ثم صوت ElevenLabs لكل مستوى (ضمن الحد اليومي 3,300 حرف)؛ أي نص متطابق يعيد استخدام تسجيله.
5. كل طلب إلى Claude يمر بحارس الميزانية الشهرية (budget.py، سقف 2.40 دولار) قبل إرساله، وكل رفض يُسجَّل بسببه
   في logs/validation-failures.json.

لا يُستخدم صوت المتصفح أبدًا: الدرس لا يُنشر حتى تكتمل كل تسجيلاته؛ وحتى ذلك يبقى آخر درس مكتمل منشورًا.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import budget
import cefr
import daily_lesson as dl
from daily_lesson import (ARABIC, MENA_COUNTRIES, MENA_KEYWORDS, ClaudeCallError,
                          WORDS, read_json, summary, tokens, write_json)

STORIES = 3           # ثلاثة أخبار يوميًا بالمستويات الثلاثة
CATEGORIES = ["politics", "economy", "health"]  # خبر سياسي، وخبر اقتصادي، وخبر صحي — بهذا الترتيب
# كلمات وظيفية لا تصلح مفردات للتعلّم (أدوات، حروف جر، ضمائر، أفعال مساعدة)
FUNCTION_WORDS = set("""a an the and or but so if as at by in on of to for from with into onto over under about after
before than then that this these those there here it its he she they we you i me him her them us his their our your
my is are was were be been being am do does did has have had will would can could shall should may might must not no
yes very more most much many some any all each both other such own same just also too only up down out off again""".split())
MIN_SOURCES = 2       # تنوع المصادر: مصدران مختلفان على الأقل (ويُفضَّل ثلاثة)

LEVEL_ORDER = ["beginner", "intermediate", "advanced"]
DEFAULT_LEVEL = "intermediate"
EXERCISES = 3
LEVELS = {
    "beginner": {
        "ar": "مبتدئ", "cefr": "A1–A2", "en_min": 40, "en_max": 210, "audio_max": 560,
        "style": "CEFR A1–A2. Each story: two to four VERY short sentences (5–12 words each), present simple or 'will', "
                 "the 1,500 most common English words, no passive voice, no relative clauses, no idioms, no "
                 "participle phrases. Vocabulary: concrete everyday words (not news jargon). Comprehension questions "
                 "are very simple (who / what / where / when) with short options.",
    },
    "intermediate": {
        "ar": "متوسط", "cefr": "B1–B2", "en_min": 60, "en_max": 200, "audio_max": 560,
        "style": "CEFR B1–B2. ONE natural sentence per story (15–26 words) that may use an infinitive of purpose, a "
                 "relative clause, present perfect or passive voice. Vocabulary: common news and work words. "
                 "Comprehension questions check the main idea and one detail.",
    },
    "advanced": {
        "ar": "متقدم", "cefr": "C1–C2", "en_min": 90, "en_max": 280, "audio_max": 780,
        "style": "CEFR C1–C2. One or two sophisticated sentences per story (24–42 words in total) in an authentic "
                 "news register: subordinate and participle clauses, passive or reduced constructions, precise formal "
                 "vocabulary and natural collocations. Vocabulary: advanced, formal or academic words (not everyday words). "
                 "Comprehension questions test inference, cause and effect, or the meaning of a phrase in context.",
    },
}


def mirror_default(lesson: dict) -> None:
    """نسخة من المستوى المتوسط بالصيغة القديمة (stories/words/translations/audio) في أعلى الدرس،
    حتى يعمل الموقع والأدوات القديمة لو تم الرجوع إلى النسخة السابقة من الكود."""
    v = lesson["levels"][lesson.get("default_level", DEFAULT_LEVEL)]
    for k in ("stories", "words", "translations", "audio"):
        lesson[k] = v[k]


def _unused_env_levels(name: str, default: list[str]) -> list[str]:
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

From the numbered news list, choose exactly 3 stories. Selection policy (mandatory):
- Every story must be about the Middle East and North Africa (MENA): it must happen in, or directly concern, a MENA country. Countries elsewhere in Africa (for example Senegal, Nigeria, Kenya) are NOT MENA. Set "country" to that country, or "MENA region" for a story about several of them.
- Choose exactly one story for each category, and in each category pick the MOST important and significant story of the day for a broad audience across the region:
  - "politics": major regional or international developments that affect the Middle East (diplomacy, agreements, elections, major government decisions, international relations).
  - "economy": news that affects people's lives: income, jobs and employment, cost of living and prices, energy, trade, major investment.
  - "health": significant medical discoveries, new treatments, disease prevention and public health measures that benefit many people.
- Judge importance by how many people it affects and how much: prefer news with real consequences over routine news. Do NOT choose routine government meetings, minor official announcements or ceremonies, insignificant local events, celebrity news or gossip, sensational headlines, opinion pieces, rumors or crime stories.
- Prefer recent, verified news from reliable sources (for example Reuters, AP, BBC, WHO, UN); stay neutral, accurate and factual. For the politics story prefer diplomacy, agreements and policy decisions over fighting, with no graphic details.
- The health story must be mainly about health (patients, diseases, medicine, hospitals, public health), not a general plan that only mentions health.
- Prefer a different source and a different country for each story (at least 2 different sources).

For each story give:
- "news_id": the number of the item.
- "category" and "country": as defined above.
- "topic": a short Arabic title of 2–4 words.
- "facts": 2 to 4 short factual statements in plain English, using only information stated in that item (who, what, where, when, numbers). Write them as neutral notes in your own words, not quotes. The first fact must name the MENA country, city or people. Never invent details.

Also give "archive_title": the 3 topics as short Arabic categories joined with "، " and "و" before the last, e.g. "سياسة، اقتصاد وصحة".
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
    if sorted(c for c in cats if c) != sorted(CATEGORIES):
        errors.append(f"choose exactly one politics, one economy and one health story (got {', '.join(map(str, cats))})")
    sources = {by_id[i].source_ar for i in ids if i in by_id}
    if len(sources) < MIN_SOURCES:
        errors.append(f"use at least {MIN_SOURCES} different sources (got {len(sources)}: {', '.join(sorted(sources))})")
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

You receive 3 numbered stories, each with a few facts. Write ONLY from these facts: do not add, change or invent any fact, number, name or date, so all levels stay factually identical. Write in your own words; do not reproduce any source wording.

Level: {level_name} ({cefr}). {style}

Return:
- "stories": exactly 3 items in the same order. "en": American English ({en_min}–{en_max} characters, American spelling, ending with a period) that names the MENA country, city or people. "ar": a natural and accurate Modern Standard Arabic translation.
- Each level must be genuinely different: its own vocabulary, sentence structure and difficulty, not a copy or light edit of another level.
- "words": exactly 20 useful vocabulary words suited to this level (nouns, verbs, adjectives or adverbs). Never choose articles, prepositions, pronouns, conjunctions, auxiliary verbs or personal names. Each "en" is a single word copied exactly as it appears in your texts (lowercase unless a proper noun); "ar" is its Arabic meaning in that sentence.
- "translations": an Arabic gloss for EVERY distinct word in your 3 texts ("word" lowercase as it appears without surrounding punctuation, keeping apostrophes and hyphens).
- Audio limit: the 3 English texts plus the 20 words must total at most {audio_max} characters.
- "exercises": exactly 3 multiple-choice comprehension questions about these stories, suited to this level. "question" in English, "question_ar" its Arabic translation, "options": exactly 4 short distinct English options, "answer": the index (0–3) of the correct option.
- Quiz rule (strict): every question and its correct answer must be answerable from YOUR three English texts alone. Use words that appear in your texts; never ask about a detail that your text leaves out, even if it is in the facts. The three wrong options must be clearly wrong according to your texts.
- Do not add any number, name, place or claim that is not in the facts. Keep attributions (for example "sources say") when the facts give them.
- The three levels are checked automatically for sentence length, grammar, vocabulary difficulty and readability, so follow the level description exactly.
"""


def level_prompt(facts: dict, feedback, used_words=()) -> str:
    lines = ["Stories and facts:"]
    for n, s in enumerate(facts["stories"], 1):
        lines.append(f"{n}. [{s['category']}, {s['country']}] " + " ".join(f.strip() for f in s["facts"]))
    if used_words:
        lines += ["", "Vocabulary already taught in another level today (choose different words that suit your level): "
                  + ", ".join(sorted(used_words))]
    if feedback:
        lines += ["", "Your previous answer was rejected. Fix these problems:"] + [f"- {f}" for f in feedback]
    return "\n".join(lines)


# أقصى عدد كلمات مشتركة مسموح بين قائمة مستوى وقائمة مستوى آخر في اليوم نفسه
MAX_SHARED_WORDS = 6


def validate_level(data: dict, level: str, known: dict, budget_chars: int | None, others: dict | None = None,
                   facts: dict | None = None) -> list[str]:
    cfg = LEVELS[level]
    errors = []
    for other, prev in (others or {}).items():  # المستويات مختلفة فعلًا: نصوص وكلمات
        prev_words = {w["en"].lower() for w in prev["words"]} if isinstance(prev["words"][0], dict) else {w[0].lower() for w in prev["words"]}
        shared = prev_words & {w.get("en", "").strip().lower() for w in data.get("words", [])}
        if len(shared) > MAX_SHARED_WORDS:
            errors.append(f"{len(shared)} of your words are already used by the {other} level ({', '.join(sorted(shared))}); "
                          f"at most {MAX_SHARED_WORDS} may repeat. Choose different words suited to your level")
        prev_texts = {st["en"].strip().lower() for st in prev["stories"]}
        for n, st in enumerate(data.get("stories", []), 1):
            if st.get("en", "").strip().lower() in prev_texts:
                errors.append(f"story {n}: identical to the {other} level; rewrite it for your level")
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
        if w.get("en", "").strip().lower() in FUNCTION_WORDS:
            errors.append(f"word '{w.get('en')}' is a function word; choose a useful noun, verb, adjective or adverb")
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
    texts = [st.get("en", "").strip() for st in stories]
    if len(texts) == STORIES and all(texts):
        errors += cefr.validate_text_level(level, texts)
        errors += cefr.validate_differentiation(
            level, texts, {o: [st["en"] for st in prev["stories"]] for o, prev in (others or {}).items()})
        if facts:
            errors += cefr.validate_fact_support(texts, [st["facts"] for st in facts["stories"]])
        errors += cefr.validate_exercise_support(exercises, texts)
    errors += cefr.validate_words(level, [w.get("en", "").strip() for w in words])
    if budget_chars is not None:
        chars = dl.audio_chars(stories, [[w.get("en", ""), ""] for w in words])
        if chars > budget_chars:
            errors.append(f"sentences + words total {chars} characters; must be at most {budget_chars}. Shorten sentences")
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


# ---------------------------------------------------------------- الخطوة 3: التدقيق اللغوي العربي قبل النشر
REVIEW_MODEL = "claude-sonnet-5-5"  # تدقيق لغوي قوي بتكلفة أقل؛ يُغيَّر بالمتغير REVIEW_MODEL (مثل claude-opus-5-5)
REVIEW_SCHEMA = {
    "type": "object",
    "properties": {"corrections": {"type": "array", "items": {
        "type": "object",
        "properties": {"id": {"type": "string"}, "ar": {"type": "string"}, "issue": {"type": "string"}},
        "required": ["id", "ar", "issue"], "additionalProperties": False}}},
    "required": ["corrections"],
    "additionalProperties": False,
}
REVIEW_PROMPT = """You are a senior Arabic editor and English–Arabic translator reviewing a lesson for "Almodhesh" (المدهش), where Arabic speakers learn English from news, before it is published.

Each item has an id, the English source (and sometimes the sentence it comes from) and the current Arabic. Review EVERY item and return a correction for each one that is not perfect:
- Accurate: keeps the exact English meaning, facts, names and numbers; adds and omits nothing.
- Natural, fluent and clear professional Modern Standard Arabic, as written by a careful news editor; never literal or awkward word-for-word renderings.
- Grammatically correct: gender and number agreement (including duals), verb forms, case endings where written, prepositions, and word order.
- Correct spelling: hamzas, taa marbuta / haa, alif maqsura / yaa, and standard spelling of names and places.
- Arabic punctuation (، ؛ ؟) and no stray English punctuation.
- Word items ("w:" and "g:"): give the precise Arabic meaning of the English word as used in its sentence (a short word or phrase, no explanations in brackets unless essential).
- Question items ("q:"): a natural Arabic rendering of the English question.
- Keep numbers as digits exactly as in the English. Keep proper names in their common Arabic spelling.

Return "corrections" with only the items that need a change: "id", the full corrected Arabic in "ar", and a short English "issue". If everything is already perfect, return an empty list."""

ARABIC_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789")


def numbers_in(text: str) -> list[str]:
    return re.findall(r"\d+(?:\.\d+)?", text.translate(ARABIC_DIGITS).replace(",", ""))


def polish_arabic(text: str) -> str:
    """تصحيحات آلية مضمونة: الفاصلة وعلامة الاستفهام العربيتان، والمسافات الزائدة."""
    text = re.sub(r"(?<=[\u0600-\u06FF]) ?, ?(?=\S)", "، ", text)
    text = re.sub(r"(?<=[\u0600-\u06FF]) ?\?", "؟", text)
    text = re.sub(r"(?<=[\u0600-\u06FF]) ?; ?", "؛ ", text)
    return re.sub(r"\s{2,}", " ", text).strip()


def known_without(key: str) -> dict:
    """الترجمات المعروضة فعلًا من دروس أخرى (الأقدم يغلب، كما في build_site_data) دون هذا الدرس."""
    try:
        lessons = [l for l in dl.build_site_data.load_lessons(dl.LESSONS_DIR) if l["key"] != key]
    except ValueError:  # لا دروس منشورة بعد
        lessons = []
    return dl.build_site_data.merged_translations(lessons, dl.LESSONS_DIR / "_base-translations.json")


def review_items(lesson: dict, levels=None, known=None) -> dict:
    """نصوص التدقيق. كلمة القاموس الموجودة في درس سابق لا تُدقَّق: الموقع يعرض أول ترجمة لها (الأقدم يغلب)،
    فترجمة هذا الدرس لها لا تُعرض أصلًا. أما كلمات الدرس وجمله وأسئلته فتُدقَّق كلها."""
    known = known or {}
    items = {"archive": {"en": "Categories: politics, economy, health", "ar": lesson["archive_title"]}}
    mid = lesson["levels"][DEFAULT_LEVEL]
    for i, st in enumerate(mid["stories"]):
        items[f"topic:{i}"] = {"en": "Short title for: " + st["en"], "ar": st["topic"]}
    for lv in (levels or LEVEL_ORDER):
        v = lesson["levels"][lv]
        ctx = lambda word: next((st["en"] for st in v["stories"] if word.lower() in tokens(st["en"])), "")
        for i, st in enumerate(v["stories"]):
            items[f"s:{lv}:{i}"] = {"en": st["en"], "ar": st["ar"]}
        for i, (en, ar) in enumerate(v["words"]):
            items[f"w:{lv}:{i}"] = {"en": en, "sentence": ctx(en), "ar": ar}
        for i, e in enumerate(v["exercises"]):
            items[f"q:{lv}:{i}"] = {"en": e["question"], "ar": e["question_ar"]}
        for word, ar in v["translations"].items():
            if word.lower() in known:
                continue
            items[f"g:{lv}:{word}"] = {"en": word, "sentence": ctx(word), "ar": ar}
    return items


def review_prompt(items: dict, feedback) -> str:
    lines = ["Items:"] + [json.dumps({"id": k, **v}, ensure_ascii=False) for k, v in items.items()]
    if feedback:
        lines += ["", "Your previous answer was rejected. Fix these problems:"] + [f"- {f}" for f in feedback]
    return "\n".join(lines)


def validate_review(data: dict, items: dict) -> list[str]:
    errors = []
    for c in data.get("corrections", []):
        cid, ar = c.get("id"), c.get("ar", "")
        if cid not in items:
            errors.append(f"unknown id {cid!r}")
            continue
        if not ARABIC.search(ar):
            errors.append(f"{cid}: corrected text must be Arabic")
        if cid.startswith("s:") and sorted(numbers_in(items[cid]["en"])) != sorted(numbers_in(ar)):
            errors.append(f"{cid}: keep every number from the English exactly ({', '.join(numbers_in(items[cid]['en']))})")
    return errors


def apply_review(lesson: dict, corrections: list[dict]) -> None:
    by_id = {c["id"]: polish_arabic(c["ar"]) for c in corrections}
    if "archive" in by_id:
        lesson["archive_title"] = by_id["archive"]
    for lv in LEVEL_ORDER:
        v = lesson["levels"][lv]
        for i, st in enumerate(v["stories"]):
            st["topic"] = by_id.get(f"topic:{i}", st["topic"])
            st["ar"] = polish_arabic(by_id.get(f"s:{lv}:{i}", st["ar"]))
        for i, w in enumerate(v["words"]):
            new = by_id.get(f"w:{lv}:{i}")
            if new:
                if v["translations"].get(w[0].lower()) == w[1]:
                    v["translations"][w[0].lower()] = new
                w[1] = new
        for i, e in enumerate(v["exercises"]):
            e["question_ar"] = polish_arabic(by_id.get(f"q:{lv}:{i}", e["question_ar"]))
        for word in list(v["translations"]):
            v["translations"][word] = by_id.get(f"g:{lv}:{word}", v["translations"][word])


# ---------------------------------------------------------------- الميزانية وسجل الرفض
MAX_TOKENS = {"facts": 6000, "level": 16000, "level_fallback": 7000, "review": 8000}
FALLBACK_LEVEL_MODEL = "claude-sonnet-5-5"  # احتياط لمستوى فاشل فقط، وبشرط أن تتسع الميزانية
LEVEL_ATTEMPTS = 3        # محاولات Haiku لكل مستوى
FALLBACK_ATTEMPTS = 2     # محاولات Sonnet لكل مستوى فاشل (كل محاولة تمر بحارس الميزانية)
RESERVE_INPUT_TOKENS = {"level": 4000, "review": 25000}  # تقدير متحفظ لمدخلات الخطوات القادمة (المقاس: 1.7 ألف و16 ألف)


def failures_path() -> Path:
    return dl.AI_USAGE_PATH.with_name("validation-failures.json")


def log_failure(key: str, step: str, model: str, attempt: int, reasons: list[str], kind: str = "validation") -> None:
    """سبب كل رفض أو إعادة محاولة أو منع بالميزانية، بنصه الدقيق."""
    log = read_json(failures_path(), [])
    log.append({"date": key, "step": step, "model": model, "attempt": attempt, "kind": kind,
                "reasons": [dl.tts.sanitize(r)[:400] for r in reasons][:40],
                "at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")})
    write_json(failures_path(), log[-1000:])


def worst_cost(model: str, input_tokens: int, max_tokens: int) -> float:
    return budget.cost_of(dl.MODEL_PRICES, model, input_tokens, max_tokens, dl.DEFAULT_LESSON_MODEL)


def review_model() -> str:
    return os.environ.get("REVIEW_MODEL", "").strip() or REVIEW_MODEL


def reserve_review() -> float:
    return worst_cost(review_model(), RESERVE_INPUT_TOKENS["review"], MAX_TOKENS["review"])


def reserve_levels(model: str, n: int) -> float:
    return n * worst_cost(model, RESERVE_INPUT_TOKENS["level"], MAX_TOKENS["level"])


def _ask(prompt_fn, validate_fn, system, schema, model, key, label, attempts=3, effort="medium",
         max_tokens=16000, reserve_after=0.0, feedback0=None):
    """طلب مع إعادة محاولة بتغذية راجعة دقيقة. يعيد (البيانات أو None، التكلفة، آخر الأسباب، هل منعته الميزانية).
    قبل كل طلب: الإنفاق الشهري + أسوأ تكلفة لهذا الطلب + الخطوات الإلزامية التالية ≤ سقف الميزانية، وإلا لا يُرسَل."""
    feedback, cost = list(feedback0 or []), 0.0
    reasons: list[str] = list(feedback)
    for attempt in range(1, attempts + 1):
        prompt = prompt_fn(feedback)
        in_tokens = budget.estimate_input_tokens(system, prompt)
        worst = worst_cost(model, in_tokens, max_tokens)
        spent = budget.month_spent(read_json(dl.AI_USAGE_PATH, []), key[:7])
        allowed, why = budget.check(spent, worst, reserve_after)
        if not allowed:
            print(f"{label}: لم يُرسَل الطلب — {why}")
            log_failure(key, label, model, attempt, [why], "budget")
            return None, cost, [why], True
        print(f"{label}: طلب من {model} (محاولة {attempt}) ...")
        try:
            data, usage = dl.call_claude(prompt, model, system=system, schema=schema, effort=effort, max_tokens=max_tokens)
        except Exception as e:  # noqa: BLE001
            msg = dl.tts.sanitize(e)[:300]
            print(f"  فشل الطلب: {msg}")
            if isinstance(e, ClaudeCallError):  # حوسب على الرد: يُسجَّل بتكلفته الفعلية
                cost += dl.record_ai_usage(key, {**e.usage, "step": label, "error": True}, attempt)
            else:  # لم يصل رد: نسجّل تكلفة المدخلات المقدَّرة فقط (احتياطًا)
                cost += dl.record_ai_usage(key, {"input_tokens": in_tokens, "output_tokens": 0, "model": model,
                                                 "step": label, "error": True}, attempt)
            reasons = [f"API/response error: {msg}"]
            log_failure(key, label, model, attempt, reasons, "error")
            feedback = []
            time.sleep(10)
            continue
        cost += dl.record_ai_usage(key, {**usage, "step": label}, attempt)
        feedback = validate_fn(data)
        if not feedback:
            return data, cost, [], False
        reasons = feedback
        log_failure(key, label, model, attempt, feedback, "validation")
        print("  رُفض:\n   - " + "\n   - ".join(feedback[:12]))
    return None, cost, reasons, False


def generate_level(level, facts, items, done, known, key, model, reserve_after):
    """Haiku أولًا ثم (إن فشل التحقق) Sonnet لهذا المستوى وحده إن اتسعت الميزانية. لا نسخ من مستوى آخر أبدًا.
    يعيد (البيانات أو None، التكلفة، النموذج الناجح)."""
    cfg = LEVELS[level]
    system = LEVEL_PROMPT.format(level_name=level, **{k: cfg[k] for k in ("cefr", "style", "en_min", "en_max", "audio_max")})
    used = {(w["en"] if isinstance(w, dict) else w[0]).lower() for r in done.values() for w in r["words"]}
    prompt_fn = lambda fb, u=used: level_prompt(facts, fb, u)
    validate = lambda d: validate_level(d, level, known, cfg["audio_max"], done, facts)
    data, cost, reasons, blocked = _ask(prompt_fn, validate, system, LEVEL_SCHEMA, model, key, level,
                                        attempts=LEVEL_ATTEMPTS, max_tokens=MAX_TOKENS["level"], reserve_after=reserve_after)
    if data is not None:
        return data, cost, model
    if blocked or model == FALLBACK_LEVEL_MODEL:
        return None, cost, model
    print(f"{level}: فشل Haiku؛ محاولة Sonnet لهذا المستوى وحده إن اتسعت الميزانية.")
    data, extra, reasons, blocked = _ask(
        prompt_fn, validate, system + "\nBe compact: no commentary, and give each gloss in one or two Arabic words.",
        LEVEL_SCHEMA, FALLBACK_LEVEL_MODEL, key, f"{level}-fallback", attempts=FALLBACK_ATTEMPTS,
        max_tokens=MAX_TOKENS["level_fallback"], reserve_after=reserve_after, feedback0=reasons)
    return data, cost + extra, FALLBACK_LEVEL_MODEL


def run_review(lesson: dict, path: Path, levels=None) -> bool:
    model = review_model()
    items = review_items(lesson, levels, known_without(lesson["key"]))
    data, cost, reasons, _ = _ask(lambda fb: review_prompt(items, fb), lambda d: validate_review(d, items),
                                  REVIEW_PROMPT, REVIEW_SCHEMA, model, lesson["key"], "review", effort="high",
                                  max_tokens=MAX_TOKENS["review"])
    if data is None:
        lesson["pending_review"] = True
        write_json(path, lesson)
        summary(f"❌ تعذر إكمال التدقيق اللغوي (تكلفة ${cost:.4f}): {'; '.join(reasons)[:300]}. "
                "لا يُسجَّل الدرس ولا يُنشر؛ يبقى آخر درس صالح.")
        return False
    apply_review(lesson, data["corrections"])
    lesson.pop("pending_review", None)
    lesson["review"] = {"model": model, "corrections": len(data["corrections"]),
                        "issues": [{"id": c["id"], "issue": c["issue"]} for c in data["corrections"]],
                        "at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}
    mirror_default(lesson)
    write_json(path, lesson)
    summary(f"🔍 التدقيق اللغوي ({model}): {len(data['corrections'])} تصحيحًا من {len(items)} نصًا عربيًا — تكلفة ${cost:.4f}")
    return True


def prepare(day: datetime, model: str, daily_cap: int | None = None, text_levels=None, audio_levels=None) -> dict | None:
    """يُعدّ درس اليوم بالمستويات الثلاثة كلها. لا يوجد احتياط بالنسخ: أي مستوى يتعذّر يوقف الدرس كله."""
    key = day.strftime("%Y-%m-%d")
    path = dl.LESSONS_DIR / f"{key}.json"
    if path.exists():
        lesson = read_json(path, None)
        if lesson.get("pending_review"):
            print(f"درس {key} محفوظ لكن تدقيقه اللغوي لم يكتمل؛ استكمال التدقيق فقط.")
            return lesson if run_review(lesson, path) else None
        print(f"درس {key} موجود مسبقًا؛ لا حاجة لإعداده (لا تكلفة).")
        return lesson
    print("جلب الأخبار:")
    items = dl.fetch_news()
    if len(items) < 12:
        summary(f"⚠️ عدد الأخبار الحديثة غير كافٍ ({len(items)})؛ يبقى آخر درس صالح.")
        return None

    order = sorted(LEVEL_ORDER, key=lambda l: l != DEFAULT_LEVEL)  # المتوسط أولًا
    facts, total, reasons, _ = _ask(
        lambda fb: facts_prompt(items, fb), lambda d: validate_facts(d, items), FACTS_PROMPT, FACTS_SCHEMA, model, key,
        "facts", max_tokens=MAX_TOKENS["facts"], reserve_after=reserve_levels(model, len(order)) + reserve_review())
    if facts is None:
        log_failure(key, "lesson", model, 0, reasons or ["facts step failed"], "blocked")
        summary("❌ تعذر اختيار أخبار صالحة. لا يُنشر درس جديد ويبقى آخر درس صالح. السبب: " + "; ".join(reasons)[:300])
        return None
    facts["stories"].sort(key=lambda s: CATEGORIES.index(s["category"]))

    known = dl.known_translations()
    results: dict[str, dict] = {}
    models: dict[str, str] = {}
    for n, level in enumerate(order):
        after = reserve_levels(model, len(order) - n - 1) + reserve_review()
        data, cost, used_model = generate_level(level, facts, items, dict(results), known, key, model, after)
        total += cost
        if data is None:
            log_failure(key, level, used_model, 0, ["no valid text for this level"], "blocked")
            summary(f"❌ تعذر إعداد مستوى {LEVELS[level]['ar']} ({LEVELS[level]['cefr']}) بعد كل المحاولات المسموحة "
                    f"(تكلفة ${total:.4f}). لا يُنشر الدرس ولا يُنسخ نص من مستوى آخر؛ يبقى آخر درس صالح. "
                    "الأسباب الدقيقة في logs/validation-failures.json")
            return None
        results[level] = build_level(data, facts, items, "claude")
        results[level]["generated_model"] = used_model

    levels = {level: results[level] for level in LEVEL_ORDER}
    lesson = {
        "key": key,
        "date": dl.arabic_long_date(day),
        "archive_date": dl.arabic_short_date(day),
        "archive_title": facts["archive_title"].strip(),
        "default_level": DEFAULT_LEVEL,
        "facts": [{"news_id": s["news_id"], "category": s["category"], "country": s["country"], "facts": s["facts"]}
                  for s in facts["stories"]],
        "levels": levels,
        "pending_audio": True,  # لا يظهر في الموقع حتى تكتمل تسجيلات ElevenLabs
        "pending_review": True,  # ولا يُسجَّل حتى يكتمل التدقيق اللغوي
        "generated": {"by": "claude", "at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")},
    }
    mirror_default(lesson)
    write_json(path, lesson)
    summary(f"✅ أُعدّ درس {key} بالمستويات الثلاثة ({', '.join(LEVELS[l]['ar'] + ' ' + results[l]['generated_model'] for l in LEVEL_ORDER)}) "
            f"— تكلفة تقديرية ${total:.4f}")
    return lesson if run_review(lesson, path) else None


# ---------------------------------------------------------------- الصوت
def level_paths(lesson: dict, level: str | None) -> tuple[list[str], list[str]]:
    key = lesson["key"]
    view = lesson["levels"][level] if level else lesson
    prefix = f"audio/{key}/{level}" if level else f"audio/{key}"  # الدروس القديمة بلا مستويات تحتفظ بمساراتها
    return ([f"{prefix}/news-{i}.mp3" for i in range(1, len(view["stories"]) + 1)],
            [f"{prefix}/words/word-{i:02d}.mp3" for i in range(1, len(view["words"]) + 1)])


def arabic_paths(lesson: dict, level: str) -> list[str]:
    """تسجيلات الترجمة العربية لكل خبر (للاستماع ثنائي اللغة)."""
    return [f"audio/{lesson['key']}/{level}/news-{i}-ar.mp3" for i in range(1, len(lesson["levels"][level]["stories"]) + 1)]


DEFAULT_ARABIC_VOICE = "fkqevZRU7Xj52dY1CTkq"  # الصوت العربي المختار بعد مقارنة الاستماع (مع Multilingual v2)


def voices() -> tuple[str, str, str]:
    """(الصوت الإنجليزي، الصوت العربي، النموذج). الصوت الإنجليزي ونموذجه كما هما دون أي تغيير؛
    والترجمة العربية بالصوت العربي المختار وبالنموذج نفسه (Multilingual v2)."""
    en = os.environ.get("ELEVENLABS_LESSON_VOICE_ID", "").strip() or dl.DEFAULT_LESSON_VOICE
    ar = os.environ.get("ELEVENLABS_ARABIC_VOICE_ID", "").strip() or DEFAULT_ARABIC_VOICE
    model = os.environ.get("ELEVENLABS_LESSON_MODEL_ID", "").strip() or dl.DEFAULT_TTS_MODEL
    return en, ar, model


def digest_of(text: str, voice_id: str, model_id: str) -> str:
    return hashlib.sha256(f"{voice_id}|{model_id}|{text}".encode()).hexdigest()


def existing_by_digest(manifest: dict) -> dict:
    return {v["sha256"]: rel for rel, v in manifest.items() if (dl.SITE / rel).exists()}


def attach(lesson: dict, level: str | None, voice_id: str, model_id: str, manifest: dict, ar_voice: str | None = None) -> None:
    """يربط كل جملة وكلمة بتسجيلها إن وُجد — بما فيها تسجيل لنص مطابق في درس أو مستوى آخر."""
    view = lesson["levels"][level] if level else lesson
    known = existing_by_digest(manifest)
    s_paths, w_paths = level_paths(lesson, level)
    def resolve(own, text, voice=voice_id):
        if (dl.SITE / own).exists() and manifest.get(own, {}).get("sha256") in (None, digest_of(text, voice, model_id)):
            return own
        return known.get(digest_of(text, voice, model_id))
    s = [resolve(p, st["en"]) for p, st in zip(s_paths, view["stories"])]
    w = [resolve(p, wd[0]) for p, wd in zip(w_paths, view["words"])]
    view["audio"] = {"stories": s if any(s) else None, "words": w if any(w) else None}
    if level:  # الترجمة العربية مسموعة (الدروس الجديدة فقط)
        a = [resolve(p, st["ar"], ar_voice or voice_id) for p, st in zip(arabic_paths(lesson, level), view["stories"])]
        view["audio"]["stories_ar"] = a if any(a) else None


def audio_complete(lesson: dict) -> bool:
    views = [lesson["levels"][l] for l in LEVEL_ORDER] if "levels" in lesson else [lesson]
    keys = ("stories", "words", "stories_ar") if "levels" in lesson else ("stories", "words")
    return all((v.get("audio") or {}).get(k) and all(v["audio"][k]) for v in views for k in keys)


def generate_audio(daily_cap: int, audio_levels: list[str], path: Path | None = None) -> bool:
    path = path or dl.latest_lesson_path()
    lesson = read_json(path, None)
    if lesson.get("pending_review"):
        summary(f"⏸ درس {lesson['key']} لم يكتمل تدقيقه اللغوي بعد؛ لا يُسجَّل ولا يُنشر حتى يكتمل.")
        return False
    voice_id, ar_voice, model_id = voices()
    manifest = read_json(dl.AUDIO_MANIFEST, {})
    targets = [l for l in LEVEL_ORDER if l in audio_levels] if "levels" in lesson else [None]
    targets.sort(key=lambda l: l != DEFAULT_LEVEL)  # المتوسط أولًا

    # التسجيلات الناقصة فقط، مع إعادة استخدام أي تسجيل لنص مطابق، ودون تكرار النص نفسه في التشغيلة
    jobs, planned = [], set()
    known = existing_by_digest(manifest)
    for level in targets:
        view = lesson["levels"][level] if level else lesson
        s_paths, w_paths = level_paths(lesson, level)
        wanted = [(rel, text, voice_id) for rel, text in list(zip(s_paths, [s["en"] for s in view["stories"]])) +
                  list(zip(w_paths, [w[0] for w in view["words"]]))]
        if level:  # الترجمة العربية لكل خبر بصوت عربي
            wanted += [(rel, s["ar"], ar_voice) for rel, s in zip(arabic_paths(lesson, level), view["stories"])]
        for rel, text, voice in wanted:
            d = digest_of(text, voice, model_id)
            if ((dl.SITE / rel).exists() and manifest.get(rel, {}).get("sha256") in (None, d)) or d in known or d in planned:
                continue
            planned.add(d)
            jobs.append((rel, text, d, voice))

    def finish():
        for level in ([l for l in LEVEL_ORDER] if "levels" in lesson else [None]):
            attach(lesson, level, voice_id, model_id, manifest, ar_voice)
        if "levels" in lesson:
            mirror_default(lesson)
            if audio_complete(lesson):
                lesson.pop("pending_audio", None)  # اكتملت التسجيلات: يُنشر الدرس
            else:
                lesson["pending_audio"] = True
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
        summary("⚠️ لا يتسع الحد اليومي أو لا يوجد مفتاح ElevenLabs؛ يبقى الدرس غير منشور حتى تكتمل تسجيلاته.")
        finish()
        return False
    remaining = dl.tts.remaining_characters(api_key)
    if remaining is None or remaining < total:
        summary(f"⚠️ رصيد ElevenLabs غير كافٍ أو تعذّر فحصه (المطلوب: {total} حرف). لم يُولَّد صوت.")
        finish()
        return False

    done = failed = 0
    for rel, text, d, voice in selected:
        try:
            audio = dl.tts.synthesize(text, api_key, voice, model_id, "mp3_44100_128")
        except RuntimeError as e:
            failed += 1
            print(f"  فشل {rel}: {dl.tts.sanitize(e)}")
            if "HTTP 401" in str(e) or "quota_exceeded" in str(e):
                break
            continue
        (dl.SITE / rel).parent.mkdir(parents=True, exist_ok=True)
        (dl.SITE / rel).write_bytes(audio)
        manifest[rel] = {"sha256": d, "chars": len(text), "voice_id": voice, "model_id": model_id}
        usage[today] = int(usage.get(today, 0)) + len(text)
        write_json(dl.AUDIO_MANIFEST, manifest)
        dl.tts.save_usage(usage, dl.USAGE_PATH)
        done += 1
    finish()
    missing = len(jobs) - done
    summary(f"🔊 صوت درس {lesson['key']}: وُلّد {done}، فشل {failed}، ناقص {missing} "
            f"(استُخدم اليوم {usage.get(today, 0)} من {daily_cap} حرف)")
    return missing == 0


def backfill(daily_cap: int) -> bool:
    """تسجيل ElevenLabs لمرة واحدة للدروس القديمة التي ليس لها تسجيلات (ضمن الحد اليومي)."""
    paths = sorted((p for p in dl.LESSONS_DIR.glob("*.json") if dl.build_site_data.KEY_RE.match(p.stem)), reverse=True)
    todo = [p for p in paths if not audio_complete(read_json(p, {}))]
    print(f"دروس تحتاج تسجيلات: {', '.join(p.stem for p in todo) or 'لا شيء'}")
    ok = True
    for p in todo:
        ok = generate_audio(daily_cap, list(LEVEL_ORDER), p) and ok
    return ok
