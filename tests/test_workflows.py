"""دفع فرع الميزة أو فتح Pull Request لا يجوز أن ينشر الموقع ولا أن يُشغّل استدعاءات مدفوعة."""
import unittest
from pathlib import Path

import yaml

WF = Path(__file__).resolve().parent.parent / ".github" / "workflows"


def load(name):
    d = yaml.safe_load((WF / name).read_text(encoding="utf-8"))
    d["on"] = d.pop(True, d.get("on"))  # PyYAML يقرأ المفتاح on كـ True
    return d


class DeployGuards(unittest.TestCase):
    def test_only_deploy_pages_reacts_to_push_and_it_deploys_only_from_default_branch(self):
        pushers = [p.name for p in WF.glob("*.yml") if "push" in (load(p.name)["on"] or {})]
        self.assertEqual(pushers, ["deploy-pages.yml"])
        wf = load("deploy-pages.yml")
        self.assertIn("github.event.repository.default_branch", wf["jobs"]["build"]["if"])
        self.assertEqual(wf["jobs"]["deploy"]["needs"], "build")  # build متخطّى = deploy متخطّى
        self.assertNotIn("always()", str(wf["jobs"]["deploy"].get("if", "")))

    def test_build_always_checks_out_default_branch_not_the_pushed_one(self):
        steps = load("deploy-pages.yml")["jobs"]["build"]["steps"]
        checkout = next(s for s in steps if str(s.get("uses", "")).startswith("actions/checkout"))
        self.assertEqual(checkout["with"]["ref"], "${{ github.event.repository.default_branch }}")

    def test_no_workflow_runs_on_pull_request(self):
        for p in WF.glob("*.yml"):
            self.assertNotIn("pull_request", load(p.name)["on"] or {}, p.name)
            self.assertNotIn("pull_request_target", load(p.name)["on"] or {}, p.name)

    def test_paid_workflows_run_only_on_schedule_or_manual_dispatch(self):
        triggers = set(load("daily-lesson.yml")["on"])
        self.assertEqual(triggers, {"workflow_dispatch", "schedule"})  # الجدولة تعمل من الفرع الافتراضي فقط


if __name__ == "__main__":
    unittest.main()
