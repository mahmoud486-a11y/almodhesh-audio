"""التحقق من حارس الميزانية: التسعير، إعادة ضبط الشهر، التزامن، حفظ السجلات عند الفشل، الإشعار، ومحاكاة شهر."""
import contextlib
import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tools"))
import budget  # noqa: E402
import daily_lesson as dl  # noqa: E402
import multilevel as ml  # noqa: E402
import notify_failure as nf  # noqa: E402

WORKFLOW = yaml.safe_load((ROOT / ".github" / "workflows" / "daily-lesson.yml").read_text(encoding="utf-8"))
STEPS = {s.get("name"): s for s in WORKFLOW["jobs"]["lesson"]["steps"]}


class Isolated(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.patches = [mock.patch.object(dl, "AI_USAGE_PATH", self.tmp / "ai-usage.json"),
                        mock.patch.object(ml.time, "sleep", lambda s: None)]
        for p in self.patches:
            p.start()
        self.addCleanup(lambda: [p.stop() for p in self.patches])

    def ask(self, key, label="facts", model="claude-haiku-5-5", max_tokens=6000, reserve_after=0.0):
        with contextlib.redirect_stdout(io.StringIO()):
            return ml._ask(lambda fb: "x" * 4000, lambda d: [], "s" * 1000, {}, model, key, label,
                           max_tokens=max_tokens, reserve_after=reserve_after)


class Pricing(unittest.TestCase):
    def test_prices_match_official_page(self):  # platform.claude.com/docs/en/about-claude/pricing (2026-11-27)
        self.assertEqual(dl.MODEL_PRICES["claude-haiku-5-5"], (0.10, 0.50))
        self.assertEqual(dl.MODEL_PRICES["claude-sonnet-5-5"], (2.00, 10.00))
        self.assertEqual(dl.MODEL_PRICES["claude-opus-5-5"], (4.00, 20.00))

    def test_haiku_long_context_is_five_times(self):
        c = lambda n: budget.cost_of(dl.MODEL_PRICES, "claude-haiku-5-5", n, 1000, dl.DEFAULT_LESSON_MODEL)
        self.assertAlmostEqual(c(100_000), 100_000 / 1e6 * 0.10 + 1000 / 1e6 * 0.50)
        self.assertAlmostEqual(c(100_001), 100_001 / 1e6 * 0.50 + 1000 / 1e6 * 2.50)

    def test_unknown_model_priced_as_default_not_free(self):
        self.assertGreater(budget.cost_of(dl.MODEL_PRICES, "future-model", 1000, 1000, dl.DEFAULT_LESSON_MODEL), 0)

    def test_worst_case_lesson_reservation_is_modest(self):
        total = ml.worst_cost("claude-haiku-5-5", 12000, ml.MAX_TOKENS["facts"]) + ml.reserve_levels("claude-haiku-5-5", 3) + ml.reserve_review()
        self.assertLess(total, 0.17)  # احتياطي أسوأ حالة لدرس كامل، لا يوقف الدرس إلا في آخر الشهر


class MonthlyReset(Isolated):
    def test_new_month_starts_from_zero_even_if_last_month_was_full(self):
        dl.write_json(dl.AI_USAGE_PATH, [{"date": "2026-11-30", "est_cost_usd": 2.39}])
        u = {"input_tokens": 1000, "output_tokens": 500, "model": "claude-haiku-5-5"}
        with mock.patch.object(dl, "call_claude", lambda *a, **k: ({"ok": 1}, u)):
            data, cost, reasons, blocked = self.ask("2026-12-01")  # أول يوم من الشهر الجديد
        self.assertFalse(blocked)
        self.assertIsNotNone(data)

    def test_same_month_full_blocks(self):
        dl.write_json(dl.AI_USAGE_PATH, [{"date": "2026-12-03", "est_cost_usd": 2.399}])
        data, cost, reasons, blocked = self.ask("2026-12-10")
        self.assertTrue(blocked)

    def test_month_spent_uses_lesson_date_prefix(self):
        log = [{"date": "2026-11-30", "est_cost_usd": 1}, {"date": "2026-12-01", "est_cost_usd": 2}]
        self.assertEqual(budget.month_spent(log, "2026-11"), 1)
        self.assertEqual(budget.month_spent(log, "2026-12"), 2)


class Recording(Isolated):
    def run_with(self, behaviour):
        calls = []
        def fake(prompt, model, system=None, schema=None, effort="medium", max_tokens=16000):
            calls.append(model)
            return behaviour(len(calls), model)
        with mock.patch.object(dl, "call_claude", fake):
            return self.ask("2026-12-02")

    def test_every_kind_of_request_is_recorded(self):
        u = {"input_tokens": 1000, "output_tokens": 500, "model": "claude-haiku-5-5"}
        def behaviour(n, model):
            if n == 1: raise dl.ClaudeCallError("refused", u)
            if n == 2: raise RuntimeError("network")
            return {"ok": 1}, u
        data, cost, _, _ = self.run_with(behaviour)
        log = dl.read_json(dl.AI_USAGE_PATH, [])
        self.assertEqual(len(log), 3)  # الرفض + الخطأ + الناجح، كلها مسجّلة
        self.assertAlmostEqual(cost, sum(e["est_cost_usd"] for e in log), places=4)
        self.assertTrue(all(e["est_cost_usd"] > 0 for e in log))

    def test_usage_is_on_disk_before_a_crash_later_in_the_lesson(self):
        u = {"input_tokens": 1000, "output_tokens": 500, "model": "claude-haiku-5-5"}
        self.run_with(lambda n, m: ({"ok": 1}, u))
        with self.assertRaises(RuntimeError):  # سقوط سير العمل بعد الاستدعاء الأول
            raise RuntimeError("runner died")
        self.assertEqual(len(dl.read_json(dl.AI_USAGE_PATH, [])), 1)  # السجل كُتب فور الاستدعاء


class Concurrency(Isolated):
    def test_second_run_sees_first_runs_spend(self):
        dl.write_json(dl.AI_USAGE_PATH, [{"date": "2026-12-04", "est_cost_usd": 2.398}])  # كتبته تشغيلة أخرى للتو
        _, _, _, blocked = self.ask("2026-12-04")
        self.assertTrue(blocked)  # يُعاد قراءة السجل قبل كل طلب

    def test_workflow_serialises_runs_without_cancelling(self):
        self.assertEqual(WORKFLOW["concurrency"]["group"], "elevenlabs")
        self.assertIs(WORKFLOW["concurrency"]["cancel-in-progress"], False)


class WorkflowKeepsRecords(unittest.TestCase):
    def test_commit_step_runs_on_failure_and_cancel(self):
        cond = STEPS["Commit lesson, audio and logs"]["if"]
        self.assertIn("always()", cond)
        self.assertNotIn("!cancelled()", cond)

    def test_logs_uploaded_if_push_fails(self):
        s = STEPS["Keep usage logs if commit failed"]
        self.assertIn("commit.outcome == 'failure'", s["if"])
        self.assertIn("logs/", s["with"]["path"])

    def test_failure_issue_covers_failure_and_cancel_and_has_test_mode(self):
        self.assertIn("cancelled()", STEPS["Open failure issue (email notification)"]["if"])
        self.assertIn("notify-test", STEPS["Notification test issue"]["if"])
        self.assertIn("notify-test", WORKFLOW[True]["workflow_dispatch"]["inputs"]["mode"]["options"])

    def test_notify_test_mode_makes_no_paid_calls(self):
        run = STEPS["Run"]["run"]
        case = run.split("notify-test)")[1].split(";;")[0]
        self.assertNotIn("python", case)
        self.assertNotIn("daily_lesson", case)


class Notification(unittest.TestCase):
    def fake_gh(self, existing="", fail_assign=False):
        calls = []
        def gh(args):
            calls.append(args)
            if args[:2] == ["issue", "list"]:
                return subprocess.CompletedProcess(args, 0, existing, "")
            if "--assignee" in args and fail_assign:
                return subprocess.CompletedProcess(args, 1, "", "not a collaborator")
            return subprocess.CompletedProcess(args, 0, "", "")
        return gh, calls

    def test_new_issue_mentions_and_assigns_owner_with_reasons(self):
        gh, calls = self.fake_gh()
        self.assertEqual(nf.notify("2026-12-01", "owner1", "https://run", False, gh, "- reason one"), "created")
        create = calls[-1]
        self.assertIn("--assignee", create)
        self.assertEqual(create[create.index("--assignee") + 1], "owner1")
        body = create[create.index("--body") + 1]
        self.assertIn("@owner1", body)
        self.assertIn("reason one", body)

    def test_assign_failure_falls_back_but_still_mentions(self):
        gh, calls = self.fake_gh(fail_assign=True)
        self.assertEqual(nf.notify("2026-12-01", "owner1", "u", False, gh, "r"), "created")
        self.assertNotIn("--assignee", calls[-1])
        self.assertIn("@owner1", calls[-1][calls[-1].index("--body") + 1])

    def test_existing_issue_gets_comment(self):
        gh, calls = self.fake_gh(existing="7")
        self.assertEqual(nf.notify("2026-12-01", "o", "u", False, gh, "r"), "comment #7")
        self.assertEqual(calls[-1][:3], ["issue", "comment", "7"])

    def test_test_mode_title_and_no_failure_text(self):
        title, body = nf.build("2026-12-01", "o", "u", True, "x")
        self.assertIn("اختبار", title)
        self.assertNotIn("لم يُنشر", body)

    def test_token_never_printed(self):
        title, body = nf.build("d", "o", "u", False, "r")
        self.assertNotIn("ghp_", body + title)


class MonthSimulation(unittest.TestCase):
    def test_realistic_month_never_exceeds_cap_and_completes_most_lessons(self):
        import random
        import simulate_month as sm
        with mock.patch.object(ml, "failures_path", lambda: dl.AI_USAGE_PATH.with_name("validation-failures.json")):
            real_mod = (dl.AI_USAGE_PATH, ml.validate_facts)
            try:
                with contextlib.redirect_stdout(io.StringIO()):
                    res = [sm.simulate(sm.SCENARIOS["واقعي"], random.Random(i)) for i in range(40)]
            finally:
                dl.AI_USAGE_PATH, ml.validate_facts = real_mod
        self.assertLessEqual(max(r["spent"] for r in res), budget.MAX_MONTHLY_BUDGET_USD)
        self.assertGreaterEqual(sum(r["done"] for r in res) / len(res), 14)


if __name__ == "__main__":
    unittest.main()
