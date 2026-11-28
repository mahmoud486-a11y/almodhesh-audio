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
        self.assertEqual(len(changed), 8)  # ثماني كلمات فقط
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

    def test_beginner_words_are_new_and_audio_cleared(self):
        new, _ = rp.plan(self.lesson, self.payload)
        self.assertEqual(len(new["levels"]["beginner"]["words"]), 20)
        self.assertEqual(new["levels"]["beginner"]["audio"], {"stories": None, "words": None})


if __name__ == "__main__":
    unittest.main()
