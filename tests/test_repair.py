import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import daily_lesson as dl  # noqa: E402
import multilevel as ml  # noqa: E402
import repair_2026_11_26 as rp  # noqa: E402


class RepairTests(unittest.TestCase):
    def setUp(self):
        self.lesson = dl.read_json(dl.SITE / "lessons" / "2026-11-26.json", None)
        self.payload = json.loads(rp.PAYLOAD.read_text(encoding="utf-8"))

    def test_plan_valid_and_only_targets_change(self):
        new, errors = rp.plan(self.lesson, self.payload)
        self.assertEqual(errors, [])
        b, i = new["levels"]["beginner"], new["levels"]["intermediate"]
        self.assertNotIn("same_as", b)
        self.assertNotEqual([s["en"] for s in b["stories"]], [s["en"] for s in i["stories"]])
        self.assertEqual([s["url"] for s in b["stories"]], [s["url"] for s in i["stories"]])
        self.assertEqual(new["levels"]["intermediate"], self.lesson["levels"]["intermediate"])
        old_adv, new_adv = self.lesson["levels"]["advanced"], new["levels"]["advanced"]
        self.assertEqual(old_adv["stories"], new_adv["stories"])  # نص الأخبار كما هو
        self.assertEqual(old_adv["audio"]["stories"], new_adv["audio"]["stories"])  # صوت الأخبار كما هو
        self.assertEqual(old_adv["audio"].get("stories_ar"), new_adv["audio"].get("stories_ar"))
        changed = [i for i, (a, b) in enumerate(zip(old_adv["words"], new_adv["words"])) if a != b]
        self.assertEqual(len(changed), 10)  # عشر كلمات فقط
        for i, (a, b) in enumerate(zip(old_adv["audio"]["words"], new_adv["audio"]["words"])):
            self.assertEqual(b, None if i in changed else a)
        self.assertEqual(old_adv["exercises"][1], new_adv["exercises"][1])
        self.assertNotEqual(old_adv["exercises"][0], new_adv["exercises"][0])
        self.assertNotEqual(old_adv["exercises"][2], new_adv["exercises"][2])

    def test_dry_run_writes_nothing(self):
        path = dl.SITE / "lessons" / "2026-11-26.json"
        before = path.read_bytes()
        self.assertEqual(rp.main.__module__, "repair_2026_11_26")
        rp.sys.argv = ["x"]
        rp.main()
        self.assertEqual(before, path.read_bytes())

    def test_every_new_word_has_example_and_review_covers_only_changed_items(self):
        import repair_2026_11_26 as r
        new, _ = rp.plan(self.lesson, self.payload)
        adv = new["levels"]["advanced"]
        self.assertEqual(set(adv["examples"]), {v[0] for v in self.payload["advanced_vocab"]["replace"].values()})
        ids = r.review_ids(new)
        self.assertIn("x:advanced:ratify", ids)
        self.assertIn("q:advanced:0", ids)
        self.assertNotIn("q:advanced:1", ids)  # لم يتغير
        self.assertFalse([i for i in ids if i.startswith("s:advanced")])  # نص الأخبار لا يُراجَع ولا يتغير
        self.assertFalse([i for i in ids if ":intermediate" in i])

    def test_beginner_words_are_new_and_audio_cleared(self):
        new, _ = rp.plan(self.lesson, self.payload)
        self.assertEqual(len(new["levels"]["beginner"]["words"]), 20)
        self.assertEqual(new["levels"]["beginner"]["audio"], {"stories": None, "words": None})


class ApplyFinishTests(unittest.TestCase):
    """--apply --finish في مجلد مؤقت: التدقيق للعناصر الجديدة فقط، والتسجيل للناقص فقط، ولا تكرار عند إعادة التشغيل."""

    def setUp(self):
        import shutil
        import tempfile
        from unittest import mock
        self.mock = mock
        self.tmp = Path(tempfile.mkdtemp())
        (self.tmp / "lessons").mkdir()
        shutil.copy(dl.SITE / "lessons" / "2026-11-26.json", self.tmp / "lessons" / "2026-11-26.json")
        self.patches = [mock.patch.object(dl, "SITE", self.tmp), mock.patch.object(dl, "LESSONS_DIR", self.tmp / "lessons"),
                        mock.patch.object(dl, "AI_USAGE_PATH", self.tmp / "ai-usage.json")]
        for p in self.patches:
            p.start()
        self.addCleanup(lambda: [p.stop() for p in self.patches])

    def run_main(self, *argv):
        calls = {"review": [], "audio": []}

        def fake_review(lesson, path, levels=None, only=None):
            calls["review"].append(set(only))
            return True
        with self.mock.patch.object(ml, "run_review", fake_review), \
             self.mock.patch.object(ml, "generate_audio", lambda cap, lv, path=None: calls["audio"].append(lv) or True), \
             self.mock.patch.object(dl.build_site_data, "build", lambda *a, **k: "2026-11-26"), \
             self.mock.patch.object(rp.sys, "argv", ["x", *argv]):
            code = rp.main()
        return code, calls

    def test_apply_finish_then_rerun_is_a_noop_for_review(self):
        code, calls = self.run_main("--apply", "--finish")
        self.assertEqual(code, 0)
        self.assertEqual(len(calls["review"]), 1)
        self.assertTrue(any(i.startswith("w:advanced:") for i in calls["review"][0]))
        self.assertEqual(calls["audio"], [["beginner", "advanced"]])
        saved = json.loads((self.tmp / "lessons" / "2026-11-26.json").read_text(encoding="utf-8"))
        self.assertEqual(saved["levels"]["beginner"]["generated_by"], "repair-2026-11-26")
        code, calls = self.run_main("--apply", "--finish")  # إعادة التشغيل: لا تدقيق مكرر (لا تكلفة)
        self.assertEqual((code, calls["review"]), (0, []))

    def test_apply_without_finish_makes_no_paid_step(self):
        code, calls = self.run_main("--apply")
        self.assertEqual((code, calls), (0, {"review": [], "audio": []}))


if __name__ == "__main__":
    unittest.main()
