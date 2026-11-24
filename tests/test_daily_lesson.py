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
    return [dl.NewsItem(id=i, source_ar="ناسا", title=f"Title {i}", summary="s",
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


class PipelineTests(unittest.TestCase):
    """يشغّل الخط كاملًا على نسخة مؤقتة من الموقع."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        shutil.copytree(ROOT / "site", self.tmp / "site")
        site = self.tmp / "site"
        self.patches = [
            mock.patch.object(dl, "SITE", site),
            mock.patch.object(dl, "LESSONS_DIR", site / "lessons"),
            mock.patch.object(dl, "SITE_AUDIO", site / "audio"),
            mock.patch.object(dl, "AUDIO_MANIFEST", site / "audio" / "manifest.json"),
            mock.patch.object(dl, "USAGE_PATH", self.tmp / "audio" / "usage.json"),
            mock.patch.object(dl, "AI_USAGE_PATH", self.tmp / "logs" / "ai-usage.json"),
        ]
        for p in self.patches:
            p.start()
        self.day = "2026-11-25"
        self.lesson_path = site / "lessons" / f"{self.day}.json"

    def tearDown(self):
        for p in self.patches:
            p.stop()
        shutil.rmtree(self.tmp)

    def run_cli(self, *args, env=None):
        out = io.StringIO()
        with mock.patch.dict(os.environ, env or {}, clear=True), redirect_stdout(out):
            code = dl.main(list(args) + ["--date", self.day])
        return code, out.getvalue()

    def fake_claude(self, answers):
        usage = {"input_tokens": 5000, "output_tokens": 4000, "model": "claude-opus-5-5", "request_id": "r"}
        return mock.patch.object(dl, "call_claude", side_effect=[(a, usage) for a in answers])

    def test_friday_and_saturday_are_review_days(self):
        before = (self.tmp / "site/lessons-data.js").read_text(encoding="utf-8")
        env = {"ANTHROPIC_API_KEY": "a", "ELEVENLABS_API_KEY": "e"}
        for day in ("2026-11-27", "2026-11-28"):  # الجمعة والسبت
            with mock.patch.object(dl, "fetch_news") as fetch, mock.patch.object(dl, "call_claude") as claude, \
                 mock.patch.object(dl.tts, "synthesize") as synth, mock.patch.dict(os.environ, env, clear=True), \
                 redirect_stdout(io.StringIO()) as out:
                code = dl.main(["run", "--date", day])
            self.assertEqual(code, 0)
            self.assertIn("يوم مراجعة", out.getvalue())
            fetch.assert_not_called(); claude.assert_not_called(); synth.assert_not_called()
            self.assertFalse((self.tmp / f"site/lessons/{day}.json").exists())
        self.assertEqual((self.tmp / "site/lessons-data.js").read_text(encoding="utf-8"), before)

    def test_no_key_changes_nothing(self):
        before = (self.tmp / "site/lessons-data.js").read_text(encoding="utf-8")
        with mock.patch.object(dl, "fetch_news") as fetch:
            code, out = self.run_cli("run")
        self.assertEqual(code, 0)
        fetch.assert_not_called()
        self.assertFalse(self.lesson_path.exists())
        self.assertEqual((self.tmp / "site/lessons-data.js").read_text(encoding="utf-8"), before)

    def test_full_run_with_daily_cap_and_no_regeneration(self):
        env = {"ANTHROPIC_API_KEY": "a", "ELEVENLABS_API_KEY": "e"}
        calls = []

        def synth(text, *a, **k):
            calls.append(text)
            return b"ID3audio"

        with mock.patch.object(dl, "fetch_news", return_value=news_items()), \
             self.fake_claude([{"bad": 1}, model_answer()]), \
             mock.patch.object(dl.tts, "remaining_characters", return_value=35000), \
             mock.patch.object(dl.tts, "synthesize", side_effect=synth):
            code, out = self.run_cli("run", env=env)
        self.assertEqual(code, 0, out)
        lesson = json.loads(self.lesson_path.read_text(encoding="utf-8"))
        self.assertEqual(len(calls), 26)  # 6 جمل + 20 كلمة
        self.assertTrue(all(lesson["audio"]["stories"]) and all(lesson["audio"]["words"]))
        used = json.loads((self.tmp / "audio/usage.json").read_text())
        self.assertEqual(sum(used.values()), dl.audio_chars(lesson["stories"], lesson["words"]))
        self.assertLessEqual(sum(used.values()), 1000)
        data = (self.tmp / "site/lessons-data.js").read_text(encoding="utf-8")
        self.assertIn(f'const lessonDate="{self.day}"', data)
        self.assertIn('"2026-11-18"', data)  # الدروس القديمة باقية في الأرشيف
        ai_log = json.loads((self.tmp / "logs/ai-usage.json").read_text())
        self.assertEqual(len(ai_log), 2)  # المحاولة المرفوضة تُسجَّل تكلفتها أيضًا

        # تشغيلة ثانية في اليوم نفسه: لا Claude ولا ElevenLabs
        with mock.patch.object(dl, "call_claude") as claude, \
             mock.patch.object(dl.tts, "synthesize") as synth2:
            code, _ = self.run_cli("run", env=env)
        self.assertEqual(code, 0)
        claude.assert_not_called()
        synth2.assert_not_called()

    def test_partial_audio_when_cap_is_low(self):
        (self.tmp / "audio").mkdir()
        today = dl.tts.local_date(dl.TIMEZONE)
        (self.tmp / "audio/usage.json").write_text(json.dumps({today: 700}))  # المتاح 300 فقط
        env = {"ANTHROPIC_API_KEY": "a", "ELEVENLABS_API_KEY": "e"}
        with mock.patch.object(dl, "fetch_news", return_value=news_items()), \
             self.fake_claude([model_answer()]), \
             mock.patch.object(dl.tts, "remaining_characters", return_value=35000), \
             mock.patch.object(dl.tts, "synthesize", return_value=b"ID3"):
            code, out = self.run_cli("run", env=env)
        self.assertEqual(code, 1)  # الصوت ناقص ← تُعلَّم التشغيلة كفاشلة للتنبيه
        lesson = json.loads(self.lesson_path.read_text(encoding="utf-8"))
        used = json.loads((self.tmp / "audio/usage.json").read_text())[today]
        self.assertLessEqual(used, 1000)
        self.assertIn(None, lesson["audio"]["stories"] + (lesson["audio"]["words"] or [None]))
        # الدرس منشور رغم نقص الصوت، والجمل الناقصة تعمل بصوت المتصفح
        self.assertIn(f'const lessonDate="{self.day}"', (self.tmp / "site/lessons-data.js").read_text(encoding="utf-8"))

    def test_insufficient_balance_generates_nothing(self):
        env = {"ANTHROPIC_API_KEY": "a", "ELEVENLABS_API_KEY": "e"}
        with mock.patch.object(dl, "fetch_news", return_value=news_items()), \
             self.fake_claude([model_answer()]), \
             mock.patch.object(dl.tts, "remaining_characters", return_value=100), \
             mock.patch.object(dl.tts, "synthesize") as synth:
            code, _ = self.run_cli("run", env=env)
        synth.assert_not_called()
        self.assertEqual(code, 1)

    def test_failed_lesson_keeps_last_valid(self):
        before = (self.tmp / "site/lessons-data.js").read_text(encoding="utf-8")
        bad = model_answer()
        bad["words"] = bad["words"][:5]
        with mock.patch.object(dl, "fetch_news", return_value=news_items()), \
             self.fake_claude([bad, bad, bad]), mock.patch.object(dl.time, "sleep"):
            code, _ = self.run_cli("run", env={"ANTHROPIC_API_KEY": "a"})
        self.assertEqual(code, 1)
        self.assertFalse(self.lesson_path.exists())
        self.assertEqual((self.tmp / "site/lessons-data.js").read_text(encoding="utf-8"), before)


if __name__ == "__main__":
    unittest.main()
