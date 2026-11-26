"""اختبارات خط الدرس اليومي — بلا اتصال بـ Claude أو ElevenLabs أو الإنترنت."""
import io
import json
import os
import shutil
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import build_site_data  # noqa: E402
import daily_lesson as dl  # noqa: E402

REAL_LESSON = json.loads((ROOT / "site/lessons/2026-11-21.json").read_text(encoding="utf-8"))


def news_items(n=15):
    now = datetime.now(timezone.utc)
    sources = ["ناسا", "بي بي سي", "الجزيرة الإنجليزية", "ذا ناشيونال"]
    return [dl.NewsItem(id=i, source_ar=sources[(i - 1) % 4], title=f"Title {i}", summary="s",
                        url=f"https://example.org/news/{i}", published=(now - timedelta(hours=i)).isoformat())
            for i in range(1, n + 1)]


MENA_LESSON = json.loads((ROOT / "site/lessons/2026-11-24.json").read_text(encoding="utf-8"))
# الخبر الخامس الأصلي عن السنغال (خارج المنطقة)؛ يُستبدل بخبر من المنطقة يحتوي الكلمتين نفسيهما
MENA_LESSON["stories"][4]["en"] = "A sports court in Morocco will rule on a football case next week."
MENA_LESSON["translations"].update({"morocco": "المغرب", "case": "قضية", "next": "القادم", "week": "أسبوع"})


def model_answer(base=MENA_LESSON):
    """رد نموذجي صالح مبني على درس 24 نوفمبر الحقيقي (أخبار الشرق الأوسط وشمال أفريقيا)."""
    trans = json.loads((ROOT / "site/lessons/_base-translations.json").read_text(encoding="utf-8"))
    trans.update(base.get("translations", {}))
    return {
        "archive_title": base["archive_title"],
        "stories": [{"news_id": i, "category": c, "country": "Egypt", "topic": s["topic"], "en": s["en"], "ar": s["ar"]}
                    for i, (s, c) in enumerate(zip(base["stories"], ["science", "economy", "health", "culture",
                                                                       "sport", "technology"]), 1)],
        "words": [{"en": w[0], "ar": w[1]} for w in base["words"]],
        "translations": [{"word": k, "ar": v} for k, v in trans.items()],
    }


class TokenTests(unittest.TestCase):
    def test_tokens_match_site_rule(self):
        self.assertEqual(dl.tokens("NASA's rover (Curiosity) saw Mars."), ["nasa's", "rover", "curiosity", "saw", "mars"])
        self.assertEqual(dl.tokens("Sand-filled toys, 2026: long-term."), ["sand-filled", "toys", "long-term"])
        self.assertEqual(dl.tokens("José — 24"), ["josé"])

    def test_arabic_dates(self):
        d = datetime(2026, 11, 21, tzinfo=ZoneInfo(dl.TIMEZONE))
        self.assertEqual(dl.arabic_long_date(d), REAL_LESSON["date"])
        self.assertEqual(dl.arabic_short_date(d), REAL_LESSON["archive_date"])


class FeedTests(unittest.TestCase):
    def test_rss_and_atom(self):
        rss = b"""<rss><channel><item><title>A &amp; B</title><link>https://a.org/1</link>
        <description>&lt;p&gt;Hello&lt;/p&gt;</description><pubDate>Tue, 24 Nov 2026 10:00:00 GMT</pubDate></item>
        <item><title>No date</title><link>https://a.org/2</link></item></channel></rss>"""
        items = dl.parse_feed(rss, "مصدر")
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["title"], "A & B")
        self.assertEqual(items[0]["summary"], "Hello")
        atom = b"""<feed xmlns="http://www.w3.org/2005/Atom"><entry><title>T</title>
        <link rel="alternate" href="https://b.org/x"/><updated>2026-11-24T09:00:00Z</updated>
        <summary>S</summary></entry></feed>"""
        items = dl.parse_feed(atom, "مصدر")
        self.assertEqual(items[0]["url"], "https://b.org/x")


class ValidationTests(unittest.TestCase):
    def test_real_lesson_passes(self):
        self.assertEqual(dl.validate_lesson(model_answer(), news_items(), 1000, {}), [])

    def test_rejections(self):
        bad = model_answer()
        bad["stories"][0]["news_id"] = 999
        bad["stories"][1]["en"] = "Too short."
        bad["words"][0]["en"] = "notinsentences"
        errors = dl.validate_lesson(bad, news_items(), 1000, {})
        joined = " | ".join(errors)
        self.assertIn("news_id 999", joined)
        self.assertIn("story 2", joined)
        self.assertIn("notinsentences", joined)

    def test_mena_policy_enforced(self):
        bad = model_answer()
        bad["stories"][0]["country"] = "Canada"
        for s in bad["stories"][1:4]:
            s["category"] = "major event"
        joined = " | ".join(dl.validate_lesson(bad, news_items(), 1000, {}))
        self.assertIn("story 1: must be about a MENA country", joined)
        self.assertIn("at most 1 'major event'", joined)

    def test_story_must_name_a_mena_place(self):
        ans = model_answer()
        ans["stories"][0]["en"] = "A sports court will soon rule on whether Senegal must give up its Africa Cup title."
        ans["stories"][1]["en"] = "Oman's new financial center has registered its first companies before opening."
        joined = " | ".join(dl.validate_lesson(ans, news_items(), 1000, {}))
        self.assertIn("story 1: the English sentence must name", joined)
        self.assertNotIn("story 2: the English sentence must name", joined)

    def test_variety_enforced(self):
        bad = model_answer()
        for s in bad["stories"]:
            s["category"] = "economy"
        self.assertTrue(any("at least 4 different categories" in e for e in dl.validate_lesson(bad, news_items(), 1000, {})))

    def test_policy_fields_not_stored_in_lesson(self):
        lesson = dl.to_lesson(model_answer(), news_items(), datetime(2026, 11, 25, tzinfo=ZoneInfo(dl.TIMEZONE)))
        self.assertEqual(set(lesson["stories"][0]), {"topic", "en", "ar", "source", "url"})

    def test_budget_enforced(self):
        errors = dl.validate_lesson(model_answer(), news_items(), 500, {})
        self.assertTrue(any("at most 500" in e for e in errors))

    def test_urls_come_from_feed_not_model(self):
        items = news_items()
        lesson = dl.to_lesson(model_answer(), items, datetime(2026, 11, 25, tzinfo=ZoneInfo(dl.TIMEZONE)))
        self.assertEqual([s["url"] for s in lesson["stories"]], [items[i].url for i in range(6)])
        self.assertTrue(all(" · " in s["source"] for s in lesson["stories"]))
        self.assertEqual(lesson["date"], "الأربعاء، 25 نوفمبر 2026")


import multilevel as ml  # noqa: E402

ML_COUNTRIES = ["Egypt", "Morocco", "Oman"]
ML_POOL = ("students teachers schools doctors hospitals farmers workers markets prices factories engineers "
           "scientists researchers players coaches artists museums festivals tourists hotels airports trains "
           "banks companies startups phones computers robots satellites rockets clinics vaccines patients "
           "rivers forests deserts beaches gardens parks bridges roads ports ships trucks buses libraries "
           "universities classes exams lessons books films songs dancers singers writers").split()
ML_WORDS_PER_SENTENCE = {"beginner": 8, "intermediate": 11, "advanced": 20}


def ml_facts_answer():
    cats = ["politics", "economy", "health"]
    return {"archive_title": "سياسة، اقتصاد وصحة",
            "stories": [{"news_id": i + 1, "category": cats[i], "country": c, "topic": f"عنوان {i + 1}",
                         "facts": [f"{c} opened a new project.", "The project started this week."]}
                        for i, c in enumerate(ML_COUNTRIES)]}


def ml_level_answer(level):
    n = ML_WORDS_PER_SENTENCE[level]
    stories, used = [], []
    for i, c in enumerate(ML_COUNTRIES):
        chunk = [ML_POOL[(i * n + k) % len(ML_POOL)] for k in range(n)]
        used += chunk
        lv_ar = {"beginner": "المبتدئ", "intermediate": "المتوسط", "advanced": "المتقدم"}[level]
        stories.append({"en": f"{c} {level} " + " ".join(chunk) + ".", "ar": f"جملة عربية {i + 1} للمستوى {lv_ar}"})
    words = list(dict.fromkeys(used))[:20]
    gloss = [{"word": w, "ar": "ترجمة"} for w in dict.fromkeys(used + [c.lower() for c in ML_COUNTRIES] + [level])]
    exercises = [{"question": f"What happened in {c}?", "question_ar": "ماذا حدث؟",
                  "options": ["A project", "A storm", "A match", "A film"], "answer": 0} for c in ML_COUNTRIES[:3]]
    return {"stories": stories, "words": [{"en": w, "ar": "معنى"} for w in words],
            "translations": gloss, "exercises": exercises}


class MultiLevelValidationTests(unittest.TestCase):
    def test_fixture_levels_are_valid(self):
        self.assertEqual(ml.validate_facts(ml_facts_answer(), news_items()), [])
        for level in ml.LEVEL_ORDER:
            self.assertEqual(ml.validate_level(ml_level_answer(level), level, {}, ml.LEVELS[level]["audio_max"]), [], level)

    def test_lengths_are_level_specific(self):
        adv = ml_level_answer("advanced")
        errs = ml.validate_level(adv, "beginner", {}, None)  # جمل المتقدم أطول من حد المبتدئ
        self.assertTrue(any("English must be 30-130" in e for e in errs))
        beg = ml_level_answer("beginner")
        self.assertTrue(any("English must be 90-230" in e for e in ml.validate_level(beg, "advanced", {}, None)))

    def test_function_words_are_rejected(self):
        bad = ml_level_answer("beginner")
        bad["stories"][0]["en"] = bad["stories"][0]["en"].replace("Egypt beginner", "Egypt as beginner")
        bad["words"][0] = {"en": "as", "ar": "بينما"}
        self.assertTrue(any("'as' is a function word" in e for e in ml.validate_level(bad, "beginner", {}, None)))

    def test_exercises_are_checked(self):
        bad = ml_level_answer("intermediate")
        bad["exercises"][0]["options"] = ["A", "A", "B", "C"]
        bad["exercises"][1]["answer"] = 7
        bad["exercises"] = bad["exercises"][:2]
        joined = " | ".join(ml.validate_level(bad, "intermediate", {}, None))
        self.assertIn("exactly 3 exercises", joined)
        self.assertIn("4 distinct options", joined)
        self.assertIn("answer must be 0-3", joined)

    def test_facts_policy(self):
        bad = ml_facts_answer()
        bad["stories"][0]["country"] = "Canada"
        bad["stories"][1]["facts"] = ["Senegal won a match.", "Fans were happy."]
        bad["stories"][2]["category"] = "economy"  # خبران اقتصاديان ولا خبر صحي
        joined = " | ".join(ml.validate_facts(bad, news_items()))
        self.assertIn("exactly one politics, one economy and one health", joined)
        self.assertIn("story 1: must be about a MENA country", joined)
        self.assertIn("story 2: the facts must name", joined)

    def test_story_order_is_politics_economy_health(self):
        facts = ml_facts_answer()
        facts["stories"].reverse()
        self.assertEqual(ml.validate_facts(facts, news_items()), [])  # أي ترتيب مقبول في الرد...

        def fake(p, m, system=None, schema=None, effort="medium"):
            u = {"input_tokens": 1, "output_tokens": 1, "model": "claude-haiku-5-5"}
            if schema is ml.REVIEW_SCHEMA:
                return {"corrections": []}, u
            if schema is ml.FACTS_SCHEMA:
                return facts, u
            return ml_level_answer(next(l for l in ml.LEVEL_ORDER if f"Level: {l} (" in system)), u
        with mock.patch.object(dl, "fetch_news", return_value=news_items()), mock.patch.object(dl, "call_claude", side_effect=fake), \
             mock.patch.object(dl, "LESSONS_DIR", Path(tempfile.mkdtemp())), \
             mock.patch.object(dl, "AI_USAGE_PATH", Path(tempfile.mkdtemp()) / "a.json"), \
             mock.patch.object(dl, "known_translations", return_value={}), redirect_stdout(io.StringIO()):
            lesson = ml.prepare(datetime(2026, 11, 25, tzinfo=ZoneInfo(dl.TIMEZONE)), "claude-haiku-5-5", 1900,
                                list(ml.LEVEL_ORDER), [])
        self.assertEqual([f["category"] for f in lesson["facts"]], ["politics", "economy", "health"])  # ...ويُرتَّب في الدرس

    def test_three_stories_and_source_diversity(self):
        ok = ml_facts_answer()
        self.assertEqual(len(ok["stories"]), 3)
        self.assertEqual(ml.validate_facts(ok, news_items()), [])
        four = ml_facts_answer()
        four["stories"].append(dict(four["stories"][0], news_id=9))
        self.assertTrue(any("exactly 3 stories" in e for e in ml.validate_facts(four, news_items())))
        same = ml_facts_answer()
        for st, nid in zip(same["stories"], [1, 5, 9]):  # كلها من المصدر نفسه
            st["news_id"] = nid
        self.assertTrue(any("at least 2 different sources" in e for e in ml.validate_facts(same, news_items())))

    def test_audio_budget_only_for_audio_levels(self):
        adv = ml_level_answer("advanced")
        self.assertTrue(any("must be at most 300" in e for e in ml.validate_level(adv, "advanced", {}, 300)))
        self.assertFalse(any("must be at most" in e for e in ml.validate_level(adv, "advanced", {}, None)))


class PipelineTests(unittest.TestCase):
    """يشغّل الخط كاملًا على نسخة مؤقتة من الموقع، مع ردود Claude و ElevenLabs محاكاة."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        shutil.copytree(ROOT / "site", self.tmp / "site")
        site = self.tmp / "site"
        self.site = site
        self.patches = [
            mock.patch.object(dl, "SITE", site),
            mock.patch.object(dl, "LESSONS_DIR", site / "lessons"),
            mock.patch.object(dl, "SITE_AUDIO", site / "audio"),
            mock.patch.object(dl, "AUDIO_MANIFEST", site / "audio" / "manifest.json"),
            mock.patch.object(dl, "USAGE_PATH", self.tmp / "audio" / "usage.json"),
            mock.patch.object(dl, "AI_USAGE_PATH", self.tmp / "logs" / "ai-usage.json"),
            mock.patch.object(ml.time, "sleep"),
        ]
        for p in self.patches:
            p.start()
        self.day = "2027-01-05"  # تاريخ مستقبلي بلا درس (درس 25 نوفمبر صار حقيقيًا في الموقع)
        self.lesson_path = site / "lessons" / f"{self.day}.json"
        self.calls = []

    def tearDown(self):
        for p in self.patches:
            p.stop()
        shutil.rmtree(self.tmp)

    def run_cli(self, *args, env=None):
        out = io.StringIO()
        with mock.patch.dict(os.environ, env or {}, clear=True), redirect_stdout(out):
            code = dl.main(list(args) + ["--date", self.day])
        return code, out.getvalue()

    def claude(self, bad_levels=(), bad_facts=False, review=None):
        """Claude محاكى: يميّز طلب الحقائق وطلب كل مستوى وطلب التدقيق، ويسجّل الطلبات."""
        usage = {"input_tokens": 4000, "output_tokens": 3000, "model": "claude-haiku-5-5"}
        self.review_models = []
        answers = list(review or [])

        def fake(prompt, model, system=None, schema=None, effort="medium"):
            if schema is ml.REVIEW_SCHEMA:
                self.calls.append("review")
                self.review_models.append((model, effort))
                return (answers.pop(0) if answers else {"corrections": []}), {**usage, "model": model}
            if schema is ml.FACTS_SCHEMA:
                self.calls.append("facts")
                return ({"bad": 1} if bad_facts else ml_facts_answer()), usage
            level = next(l for l in ml.LEVEL_ORDER if f"Level: {l} (" in system)
            self.calls.append(level)
            return ({"stories": []} if level in bad_levels else ml_level_answer(level)), usage
        return mock.patch.object(dl, "call_claude", side_effect=fake)

    def tts(self, balance=35000):
        self.spoken = []

        def synth(text, *a, **k):
            self.spoken.append(text)
            return b"ID3audio"
        return (mock.patch.object(dl.tts, "remaining_characters", return_value=balance),
                mock.patch.object(dl.tts, "synthesize", side_effect=synth))

    def full_run(self, env_extra=None, **claude_kw):
        env = {"ANTHROPIC_API_KEY": "a", "ELEVENLABS_API_KEY": "e", **(env_extra or {})}
        bal, syn = self.tts()
        with mock.patch.object(dl, "fetch_news", return_value=news_items()), self.claude(**claude_kw), bal, syn:
            return self.run_cli("run", env=env)

    def data(self, level):
        return (self.site / f"lessons-data-{level}.js").read_text(encoding="utf-8")

    def test_three_levels_one_fetch_shared_facts_and_sources(self):
        with mock.patch.object(dl, "fetch_news", return_value=news_items()) as fetch, self.claude(), \
             mock.patch.object(dl.tts, "remaining_characters", return_value=35000), \
             mock.patch.object(dl.tts, "synthesize", return_value=b"ID3"):
            code, out = self.run_cli("run", env={"ANTHROPIC_API_KEY": "a", "ELEVENLABS_API_KEY": "e"})
        self.assertEqual(code, 0, out)
        fetch.assert_called_once()  # الأخبار تُجلب مرة واحدة
        self.assertEqual(self.calls, ["facts", "intermediate", "beginner", "advanced", "review"])
        lesson = json.loads(self.lesson_path.read_text(encoding="utf-8"))
        self.assertEqual(set(lesson["levels"]), set(ml.LEVEL_ORDER))
        for level in ml.LEVEL_ORDER:
            v = lesson["levels"][level]
            self.assertEqual(len(v["stories"]), 3)
            self.assertEqual(len(v["words"]), 20)
            self.assertEqual(len(v["exercises"]), 3)
            self.assertNotIn("same_as", v)
            self.assertIn(f"{level} ", self.data(level))
        urls = {l: [s["url"] for s in lesson["levels"][l]["stories"]] for l in ml.LEVEL_ORDER}
        self.assertEqual(urls["beginner"], urls["advanced"])  # المصادر نفسها في كل المستويات
        self.assertEqual(urls["beginner"], [i.url for i in news_items()[:3]])
        self.assertIn('"2026-11-18"', self.data("beginner"))  # الأرشيف القديم باقٍ في كل مستوى

    def test_elevenlabs_for_all_levels_within_cap(self):
        code, _ = self.full_run()
        self.assertEqual(code, 0)
        lesson = json.loads(self.lesson_path.read_text(encoding="utf-8"))
        self.assertNotIn("pending_audio", lesson)
        for level in ml.LEVEL_ORDER:
            audio = lesson["levels"][level]["audio"]
            self.assertEqual(len(audio["stories"]), 3)
            for k in ("stories", "words", "stories_ar"):
                self.assertTrue(all(audio[k]), (level, k))  # كل تسجيل موجود؛ لا شيء بصوت المتصفح
            self.assertTrue(all(p.endswith("-ar.mp3") for p in audio["stories_ar"]))
        used = sum(json.loads((self.tmp / "audio/usage.json").read_text()).values())
        self.assertLessEqual(used, dl.DAILY_MAX_CHARS)
        arabic = [t for t in self.spoken if dl.ARABIC.search(t)]
        self.assertEqual(len(arabic), 9)  # 3 أخبار × 3 مستويات، كل ترجمة تُسجَّل مرة واحدة
        self.assertEqual(len(self.spoken), len(set(self.spoken)))  # لا نص يُسجَّل مرتين
        self.assertIn("const lessonArabicAudio=", self.data("advanced"))
        self.assertIn("-ar.mp3", self.data("advanced").split("const lessonArabicAudio=")[1])

    def test_voices_english_unchanged_arabic_selected_same_model(self):
        calls = []

        def synth(text, key, voice, model, fmt):
            calls.append((dl.ARABIC.search(text) is not None, voice, model, fmt))
            return b"ID3"
        env = {"ANTHROPIC_API_KEY": "a", "ELEVENLABS_API_KEY": "e"}
        with mock.patch.object(dl, "fetch_news", return_value=news_items()), self.claude(), \
             mock.patch.object(dl.tts, "remaining_characters", return_value=35000), \
             mock.patch.object(dl.tts, "synthesize", side_effect=synth):
            code, _ = self.run_cli("run", env=env)
        self.assertEqual(code, 0)
        english = {(v, m, f) for is_ar, v, m, f in calls if not is_ar}
        arabic = {(v, m, f) for is_ar, v, m, f in calls if is_ar}
        self.assertEqual(english, {("21m00Tcm4TlvDq8ikWAM", "eleven_multilingual_v2", "mp3_44100_128")})  # كما هو تمامًا
        self.assertEqual(arabic, {("fkqevZRU7Xj52dY1CTkq", "eleven_multilingual_v2", "mp3_44100_128")})

    def test_arabic_review_uses_strongest_model_and_is_applied(self):
        fixes = {"corrections": [
            {"id": "s:beginner:0", "ar": "جملة عربية مصححة , وواضحة", "issue": "grammar"},
            {"id": "w:advanced:0", "ar": "طلاب", "issue": "meaning"},
            {"id": "g:intermediate:egypt", "ar": "مصر", "issue": "spelling"},
            {"id": "topic:1", "ar": "عنوان مصحح", "issue": "style"},
        ]}
        code, out = self.full_run(review=[fixes])
        self.assertEqual(code, 0, out)
        self.assertEqual(self.review_models, [("claude-sonnet-5-5", "high")])
        lesson = json.loads(self.lesson_path.read_text(encoding="utf-8"))
        self.assertEqual(lesson["levels"]["beginner"]["stories"][0]["ar"], "جملة عربية مصححة، وواضحة")  # فاصلة عربية
        self.assertEqual(lesson["levels"]["advanced"]["words"][0][1], "طلاب")
        self.assertEqual(lesson["levels"]["intermediate"]["translations"]["egypt"], "مصر")
        self.assertTrue(all(lesson["levels"][l]["stories"][1]["topic"] == "عنوان مصحح" for l in ml.LEVEL_ORDER))
        self.assertEqual(lesson["review"]["corrections"], 4)
        self.assertNotIn("pending_review", lesson)
        # التسجيل العربي يُصنع من النص بعد التدقيق
        self.assertIn("جملة عربية مصححة، وواضحة", self.spoken)

    def test_review_rejects_changed_numbers(self):
        items = {"s:beginner:0": {"en": "Saudi Arabia approved a $371bn budget.", "ar": "..."}}
        bad = {"corrections": [{"id": "s:beginner:0", "ar": "وافقت السعودية على ميزانية بقيمة 317 مليار دولار.", "issue": "x"}]}
        self.assertTrue(any("keep every number" in e for e in ml.validate_review(bad, items)))
        good = {"corrections": [{"id": "s:beginner:0", "ar": "وافقت السعودية على ميزانية بقيمة ٣٧١ مليار دولار.", "issue": "x"}]}
        self.assertEqual(ml.validate_review(good, items), [])

    def test_failed_review_blocks_recording_and_publishing_then_resumes(self):
        before = self.data("intermediate")
        bad = {"corrections": [{"id": "nope", "ar": "x", "issue": "x"}]}
        code, _ = self.full_run(review=[bad, bad, bad])
        self.assertEqual(code, 1)
        lesson = json.loads(self.lesson_path.read_text(encoding="utf-8"))
        self.assertTrue(lesson["pending_review"])
        self.assertEqual(self.spoken, [])  # لا تسجيل قبل اكتمال التدقيق
        self.assertEqual(self.data("intermediate"), before)  # ولا نشر
        self.calls.clear()
        code, _ = self.full_run()
        self.assertEqual(code, 0)
        self.assertEqual(self.calls, ["review"])  # استكمال التدقيق فقط، دون إعادة كتابة الدرس
        self.assertIn(f'const lessonDate="{self.day}"', self.data("intermediate"))

    def test_new_lessons_stay_readable_by_previous_code(self):
        self.full_run()
        lesson = json.loads(self.lesson_path.read_text(encoding="utf-8"))
        mid = lesson["levels"]["intermediate"]
        for k in ("stories", "words", "translations", "audio"):
            self.assertEqual(lesson[k], mid[k], k)
        # النسخة السابقة من build_site_data كانت تقرأ هذه الحقول فقط
        legacy = {k: lesson[k] for k in ("key", "date", "archive_date", "archive_title", "stories", "words", "audio")}
        js = build_site_data.render([legacy], {})
        self.assertIn(mid["stories"][0]["en"], js)

    def test_no_regeneration_on_second_run(self):
        self.full_run()
        self.calls.clear()
        code, out = self.full_run()
        self.assertEqual(code, 0)
        self.assertEqual(self.calls, [])
        self.assertEqual(self.spoken, [])

    def test_disabled_level_reuses_intermediate_text_and_audio(self):
        code, _ = self.full_run({"LESSON_LEVELS": "intermediate"})
        self.assertEqual(code, 0)
        self.assertEqual(self.calls, ["facts", "intermediate", "review"])
        lesson = json.loads(self.lesson_path.read_text(encoding="utf-8"))
        self.assertEqual(lesson["levels"]["beginner"]["same_as"], "intermediate")
        self.assertLessEqual(len(self.spoken), 23 + 3)  # لا تسجيل مكرر: المستويات المنسوخة تعيد استخدام تسجيلات المتوسط (والعربية)
        self.assertEqual(lesson["levels"]["beginner"]["audio"], lesson["levels"]["intermediate"]["audio"])

    def test_failed_level_falls_back_without_losing_the_day(self):
        code, _ = self.full_run(bad_levels=("advanced",))
        self.assertEqual(code, 0)
        self.assertEqual(self.calls.count("advanced"), 3)
        lesson = json.loads(self.lesson_path.read_text(encoding="utf-8"))
        self.assertEqual(lesson["levels"]["advanced"]["same_as"], "intermediate")
        self.assertNotIn("same_as", lesson["levels"]["beginner"])

    def test_failed_facts_keep_last_valid_lesson(self):
        before = {l: self.data(l) for l in ml.LEVEL_ORDER}
        code, _ = self.full_run(bad_facts=True)
        self.assertEqual(code, 1)
        self.assertEqual(self.calls, ["facts"] * 3)
        self.assertFalse(self.lesson_path.exists())
        self.assertEqual({l: self.data(l) for l in ml.LEVEL_ORDER}, before)

    def test_incomplete_audio_is_held_back_then_published_next_run(self):
        (self.tmp / "audio").mkdir()
        today = dl.tts.local_date(dl.TIMEZONE)
        (self.tmp / "audio/usage.json").write_text(json.dumps({today: dl.DAILY_MAX_CHARS - 600}))
        before = self.data("intermediate")
        code, _ = self.full_run()
        self.assertEqual(code, 1)
        self.assertLessEqual(json.loads((self.tmp / "audio/usage.json").read_text())[today], dl.DAILY_MAX_CHARS)
        lesson = json.loads(self.lesson_path.read_text(encoding="utf-8"))
        self.assertTrue(lesson["pending_audio"])  # محفوظ لكنه غير منشور: لا صوت متصفح ولا درس ناقص
        self.assertEqual(self.data("intermediate"), before)
        # اليوم التالي (حد جديد): تُستكمل التسجيلات دون أي طلب Claude جديد، ثم يُنشر
        (self.tmp / "audio/usage.json").write_text(json.dumps({today: 0}))
        self.calls.clear()
        code, _ = self.full_run()
        self.assertEqual(code, 0)
        self.assertEqual(self.calls, [])
        self.assertNotIn("pending_audio", json.loads(self.lesson_path.read_text(encoding="utf-8")))
        self.assertIn(f'const lessonDate="{self.day}"', self.data("intermediate"))

    def test_insufficient_balance_generates_nothing(self):
        env = {"ANTHROPIC_API_KEY": "a", "ELEVENLABS_API_KEY": "e"}
        with mock.patch.object(dl, "fetch_news", return_value=news_items()), self.claude(), \
             mock.patch.object(dl.tts, "remaining_characters", return_value=100), \
             mock.patch.object(dl.tts, "synthesize") as synth:
            code, _ = self.run_cli("run", env=env)
        synth.assert_not_called()
        self.assertEqual(code, 1)
        self.assertTrue(json.loads(self.lesson_path.read_text(encoding="utf-8"))["pending_audio"])
        self.assertNotIn(f'"{self.day}"', self.data("intermediate"))  # يبقى آخر درس مكتمل منشورًا

    def test_friday_and_saturday_are_review_days(self):
        before = self.data("intermediate")
        for day in ("2026-11-27", "2026-11-28"):
            self.day = day
            with mock.patch.object(dl, "fetch_news") as fetch, self.claude():
                code, out = self.run_cli("run", env={"ANTHROPIC_API_KEY": "a", "ELEVENLABS_API_KEY": "e"})
            self.assertEqual(code, 0)
            self.assertIn("يوم مراجعة", out)
            fetch.assert_not_called()
        self.assertEqual(self.calls, [])
        self.assertEqual(self.data("intermediate"), before)

    def test_backfill_records_old_lessons_without_audio(self):
        bal, syn = self.tts()
        with bal, syn, mock.patch.dict(os.environ, {"ELEVENLABS_API_KEY": "e"}, clear=True), \
             mock.patch.object(dl, "DAILY_MAX_CHARS", 5000), redirect_stdout(io.StringIO()):
            code = dl.main(["backfill", "--daily-max-chars", "5000"])
        self.assertEqual(code, 0)
        for key in ("2026-11-18", "2026-11-19", "2026-11-20"):
            lesson = json.loads((self.site / f"lessons/{key}.json").read_text(encoding="utf-8"))
            self.assertTrue(all(lesson["audio"]["stories"]) and all(lesson["audio"]["words"]), key)
        self.assertNotIn("2026-11-21/news", " ".join(self.spoken))  # الدروس المسجّلة سابقًا لا يُعاد تسجيلها
        self.assertIn('"2026-11-18":[', self.data("intermediate").split("const lessonAudio=")[1])

    def test_no_key_changes_nothing(self):
        before = self.data("intermediate")
        with mock.patch.object(dl, "fetch_news") as fetch:
            code, _ = self.run_cli("run")
        self.assertEqual(code, 0)
        fetch.assert_not_called()
        self.assertEqual(self.data("intermediate"), before)


if __name__ == "__main__":
    unittest.main()
