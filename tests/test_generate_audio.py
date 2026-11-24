"""اختبارات لا تتصل بـ ElevenLabs ولا تستهلك أي رصيد."""
import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import generate_audio as ga  # noqa: E402


class SplitTextTests(unittest.TestCase):
    def test_short_text_single_chunk(self):
        self.assertEqual(ga.split_text("مرحبا بكم."), ["مرحبا بكم."])

    def test_long_text_split_on_sentences(self):
        sentence = "هذه جملة عربية للاختبار؟ "
        text = sentence * 200
        chunks = ga.split_text(text, max_chars=300)
        self.assertGreater(len(chunks), 1)
        self.assertTrue(all(len(c) <= 300 for c in chunks))
        self.assertEqual(" ".join(chunks).split(), text.split())

    def test_very_long_sentence_is_cut(self):
        text = "كلمة " * 500
        chunks = ga.split_text(text, max_chars=100)
        self.assertTrue(all(len(c) <= 100 for c in chunks))
        self.assertEqual(" ".join(chunks).split(), text.split())


class PipelineTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.texts = root / "texts"
        self.audio = root / "audio"
        self.texts.mkdir()
        (self.texts / "a.txt").write_text("النص الأول.", encoding="utf-8")
        (self.texts / "b.txt").write_text("النص الثاني أطول قليلًا.", encoding="utf-8")

    def tearDown(self):
        self.tmp.cleanup()

    def run_main(self, *extra, env=None):
        argv = ["--texts-dir", str(self.texts), "--audio-dir", str(self.audio), *extra]
        out = io.StringIO()
        with mock.patch.dict("os.environ", env or {}, clear=True), redirect_stdout(out):
            code = ga.main(argv)
        return code, out.getvalue()

    def test_dry_run_makes_no_api_calls(self):
        with mock.patch.object(ga, "api_request") as api:
            code, out = self.run_main("--dry-run")
        self.assertEqual(code, 0)
        api.assert_not_called()
        self.assertIn("a.txt", out)
        self.assertFalse(self.audio.exists())

    def test_missing_key_fails_without_calls(self):
        with mock.patch.object(ga, "api_request") as api:
            code, _ = self.run_main()
        self.assertEqual(code, 2)
        api.assert_not_called()

    def test_generates_then_skips_unchanged(self):
        def fake(method, path, key, body=None, query="", timeout=180):
            if path == "/user/subscription":
                return json.dumps({"character_limit": 1000, "character_count": 0}).encode()
            return b"ID3fake-mp3"

        env = {"ELEVENLABS_API_KEY": "test-key"}
        with mock.patch.object(ga, "api_request", side_effect=fake) as api:
            code, _ = self.run_main("--limit", "1", env=env)
        self.assertEqual(code, 0)
        self.assertTrue((self.audio / "a.mp3").exists())
        self.assertFalse((self.audio / "b.mp3").exists())
        tts_calls = [c for c in api.call_args_list if c.args[1].startswith("/text-to-speech/")]
        self.assertEqual(len(tts_calls), 1)

        # التشغيلة الثانية: a.txt لم يتغير فيُتخطى، ويُولَّد b.txt فقط
        with mock.patch.object(ga, "api_request", side_effect=fake) as api:
            code, out = self.run_main(env=env)
        tts_calls = [c for c in api.call_args_list if c.args[1].startswith("/text-to-speech/")]
        self.assertEqual(len(tts_calls), 1)
        self.assertNotIn("a.txt ->", out)
        self.assertTrue((self.audio / "b.mp3").exists())

        # التشغيلة الثالثة: لا شيء جديد، لا اتصالات إطلاقًا
        with mock.patch.object(ga, "api_request", side_effect=fake) as api:
            code, _ = self.run_main(env=env)
        api.assert_not_called()

    def test_insufficient_balance_aborts(self):
        def fake(method, path, key, body=None, query="", timeout=180):
            if path == "/user/subscription":
                return json.dumps({"character_limit": 10, "character_count": 5}).encode()
            raise AssertionError("must not call TTS")

        with mock.patch.object(ga, "api_request", side_effect=fake):
            code, _ = self.run_main(env={"ELEVENLABS_API_KEY": "k"})
        self.assertEqual(code, 3)

    def _fake(self, limit=100000, used=0, sub_error=None):
        def fake(method, path, key, body=None, query="", timeout=180):
            if path == "/user/subscription":
                if sub_error:
                    raise RuntimeError(sub_error)
                return json.dumps({"character_limit": limit, "character_count": used}).encode()
            return b"ID3fake-mp3"
        return fake

    def test_daily_cap_across_runs(self):
        env = {"ELEVENLABS_API_KEY": "k"}
        a, b = len("النص الأول."), len("النص الثاني أطول قليلًا.")
        cap = str(a + 3)  # يكفي الأول فقط
        with mock.patch.object(ga, "api_request", side_effect=self._fake()):
            code, _ = self.run_main("--daily-max-chars", cap, env=env)
        self.assertEqual(code, 0)
        self.assertTrue((self.audio / "a.mp3").exists())
        self.assertFalse((self.audio / "b.mp3").exists())
        usage = json.loads((self.audio / "usage.json").read_text())
        self.assertEqual(list(usage.values()), [a])
        # تشغيلة ثانية في اليوم نفسه: المتاح 3 أحرف فقط، فلا توليد
        with mock.patch.object(ga, "api_request", side_effect=self._fake()) as api:
            code, _ = self.run_main("--daily-max-chars", cap, env=env)
        tts = [c for c in api.call_args_list if c.args[1].startswith("/text-to-speech/")]
        self.assertEqual(tts, [])
        self.assertFalse((self.audio / "b.mp3").exists())
        # يوم جديد: يُولَّد الثاني
        with mock.patch.object(ga, "local_date", return_value="2999-01-01"), \
             mock.patch.object(ga, "api_request", side_effect=self._fake()):
            self.run_main("--daily-max-chars", str(b), env=env)
        self.assertTrue((self.audio / "b.mp3").exists())

    def test_require_balance_check_stops_without_permission(self):
        err = 'HTTP 401: {"detail":{"status":"missing_permissions"}}'
        with mock.patch.object(ga, "api_request", side_effect=self._fake(sub_error=err)) as api:
            code, _ = self.run_main("--require-balance-check", env={"ELEVENLABS_API_KEY": "k"})
        self.assertEqual(code, 4)
        self.assertEqual(len(api.call_args_list), 1)  # فحص الرصيد فقط
        self.assertFalse(self.audio.exists())

    def test_check_balance_mode_never_calls_tts(self):
        with mock.patch.object(ga, "api_request", side_effect=self._fake(limit=500, used=100)) as api:
            code, out = self.run_main("--check-balance", env={"ELEVENLABS_API_KEY": "k"})
        self.assertEqual(code, 0)
        self.assertIn("400", out)
        self.assertEqual([c.args[1] for c in api.call_args_list], ["/user/subscription"])


    def test_max_chars_limit(self):
        code, out = self.run_main("--dry-run", "--max-chars", "15")
        self.assertIn("a.txt ->", out)
        self.assertNotIn("b.txt ->", out)


if __name__ == "__main__":
    unittest.main()
