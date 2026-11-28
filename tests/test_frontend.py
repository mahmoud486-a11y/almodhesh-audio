"""اختبارات الواجهة (تحديث الدرس الجديد، ونتائج المراجعة الأسبوعية لكل مستوى) عبر node بلا متصفح ولا شبكة."""
import json
import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


@unittest.skipUnless(shutil.which("node"), "node غير متوفر")
class FrontendTests(unittest.TestCase):
    def test_update_check_and_weekly_scores(self):
        out = subprocess.run(["node", str(ROOT / "tests" / "frontend_checks.js")], capture_output=True, text=True, timeout=60)
        self.assertEqual(out.returncode, 0, out.stderr)
        results = json.loads(out.stdout.strip().splitlines()[-1])
        failed = [r for r in results if not r["ok"]]
        self.assertEqual(failed, [], failed)
        self.assertGreaterEqual(len(results), 12)

    def test_files_are_wired_into_the_site(self):
        index = (ROOT / "site/index.html").read_text(encoding="utf-8")
        sw = (ROOT / "site/sw.js").read_text(encoding="utf-8")
        self.assertIn('<script src="update.js"></script>', index)
        self.assertIn('"update.js"', sw)
        self.assertEqual(json.loads((ROOT / "site/latest.json").read_text())["lesson"], "2026-11-26")

    def test_update_script_never_calls_paid_services(self):
        js = (ROOT / "site/update.js").read_text(encoding="utf-8")
        for bad in ("anthropic", "elevenlabs", "api.", "https://", "http://"):
            self.assertNotIn(bad, js.lower())
        self.assertNotIn("speechSynthesis", js)


if __name__ == "__main__":
    unittest.main()
