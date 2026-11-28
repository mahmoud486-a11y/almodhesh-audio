"""محاكاة شهر كامل (23 درسًا) دون أي اتصال: تستخدم حارس الميزانية الحقيقي و _ask و generate_level و دفتر التشغيلات الحقيقيين،
وتستبدل فقط الاتصال بـ Claude بتكاليف مولَّدة عشوائيًا (مضبوطة على الاستهلاك المقيس في logs/ai-usage.json).
تشمل: رفض محاولات Haiku، Sonnet الاحتياطي، التدقيق العربي التكيفي (medium ثم high لبعض العناصر)، أخطاء API،
تجاوز max_tokens، وموت المُشغِّل/إلغاء سير العمل (يضيع سجل اليوم فيحتسبه الدفتر بالاحتياطي).

الاستخدام: python3 tools/simulate_month.py [--runs 300] [--seed 1]
"""
from __future__ import annotations

import argparse
import contextlib
import datetime as _d
import io
import random
import statistics
import sys
import tempfile
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import budget  # noqa: E402
import daily_lesson as dl  # noqa: E402
import ledger  # noqa: E402
import multilevel as ml  # noqa: E402

DAYS = 23  # أحد–خميس في ديسمبر 2026
SCENARIOS = {  # احتمال رفض محاولة Haiku لمستوى، ورفض Sonnet، وخطأ API، وتجاوز max_tokens، وفشل التدقيق، وتعليم عناصر للمراجعة العميقة
    "متفائل": dict(p_haiku=0.10, p_sonnet=0.20, p_err=0.01, p_trunc=0.01, p_review=0.03, p_escalate=0.15),
    "واقعي":  dict(p_haiku=0.30, p_sonnet=0.30, p_err=0.02, p_trunc=0.03, p_review=0.05, p_escalate=0.30),
    "متشائم": dict(p_haiku=0.50, p_sonnet=0.40, p_err=0.04, p_trunc=0.05, p_review=0.10, p_escalate=0.50),
}


def simulate(sc: dict, rng: random.Random, die: float = 0.0, review_effort: str = "medium") -> dict:
    tmp = Path(tempfile.mkdtemp())
    clock = {"day": _d.date(2026, 12, 1), "model": "", "step": ""}

    def fake_call(prompt, model, system=None, schema=None, effort="medium", max_tokens=16000):
        label = clock["step"]
        if "sonnet" in model and label.endswith("fallback"):
            usage = {"input_tokens": rng.randint(2500, 4000), "output_tokens": rng.randint(4500, 7000), "model": model}
        elif label == "review":
            out = (rng.randint(1500, 3500) if effort == "medium" else rng.randint(3000, 6000))
            usage = {"input_tokens": rng.randint(13000, 19000), "output_tokens": out, "model": model}
        elif label == "review-deep":
            usage = {"input_tokens": rng.randint(2500, 5000), "output_tokens": rng.randint(2000, 4000), "model": model}
        elif label == "facts":
            usage = {"input_tokens": rng.randint(9000, 12000), "output_tokens": rng.randint(2500, 4000), "model": model}
        else:
            usage = {"input_tokens": rng.randint(1500, 2200), "output_tokens": rng.randint(9000, 15600), "model": model}
        r = rng.random()
        if r < sc["p_err"]:
            raise RuntimeError("simulated API error")
        if r < sc["p_err"] + sc["p_trunc"]:
            usage["output_tokens"] = max_tokens
            raise dl.ClaudeCallError("max_tokens", usage)
        return {}, usage

    def fake_validate_level(data, level, known, budget_chars, others=None, facts=None):
        sonnet = "sonnet" in clock["model"]
        return ["x"] if rng.random() < (sc["p_sonnet"] if sonnet else sc["p_haiku"]) else []

    real_ask = ml._ask

    def tracking_ask(prompt_fn, validate_fn, system, schema, model, key, label, **kw):
        clock["step"], clock["model"] = label, model
        return real_ask(prompt_fn, validate_fn, system, schema, model, key, label, **kw)

    patches = [mock.patch.object(dl, "AI_USAGE_PATH", tmp / "ai-usage.json"),
               mock.patch.object(dl, "call_claude", fake_call), mock.patch.object(ml, "validate_level", fake_validate_level),
               mock.patch.object(ml, "validate_facts", lambda d, items: []), mock.patch.object(ml.time, "sleep", lambda s: None),
               mock.patch.object(ml, "_ask", tracking_ask),
               mock.patch.object(budget, "utc_now", lambda: _d.datetime.combine(clock["day"], _d.time(10), tzinfo=_d.timezone.utc)),
               mock.patch.dict("os.environ", {"GITHUB_RUN_ID": "1", "GITHUB_RUN_ATTEMPT": "1"})]
    for p in patches:
        p.start()
    ml.failures_path = lambda: dl.AI_USAGE_PATH.with_name("validation-failures.json")
    done = blocked_budget = blocked_quality = deaths = 0
    true_total = 0.0
    try:
        days = [_d.date(2026, 12, 1) + _d.timedelta(days=i) for i in range(31)]
        sun_thu = [d for d in days if d.weekday() in (6, 0, 1, 2, 3)][:DAYS]
        for n, day in enumerate(sun_thu):
            clock["day"] = day
            with mock.patch.dict("os.environ", {"GITHUB_RUN_ID": str(n + 1)}):
                ledger.begin(day.isoformat())  # الكتابة المسبقة (وتحتسب أي تشغيلة منقطعة سابقة)
                snapshot = dl.read_json(dl.AI_USAGE_PATH, [])
                outcome = _lesson(day.isoformat(), rng, sc)
                after = dl.read_json(dl.AI_USAGE_PATH, [])
                true_total += sum(e["est_cost_usd"] for e in after[len(snapshot):])
                if rng.random() < die:  # مات المُشغِّل/أُلغي: ضاع سجل اليوم ولم يُغلَق الدفتر
                    dl.write_json(dl.AI_USAGE_PATH, snapshot)
                    deaths += 1
                else:
                    ledger.end()
            done += outcome == "ok"
            blocked_budget += outcome == "budget"
            blocked_quality += outcome == "quality"
        recorded = budget.month_spent(dl.read_json(dl.AI_USAGE_PATH, []), "2026-12")
    finally:
        for p in reversed(patches):
            p.stop()
    return {"done": done, "budget": blocked_budget, "quality": blocked_quality, "spent": true_total,
            "recorded": recorded, "deaths": deaths}


def _lesson(key: str, rng: random.Random, sc: dict) -> str:
    order = sorted(ml.LEVEL_ORDER, key=lambda l: l != ml.DEFAULT_LEVEL)
    model = dl.DEFAULT_LESSON_MODEL
    facts, cost, reasons, blocked = ml._ask(
        lambda fb: "x" * 20000, lambda d: [], "s" * 3000, {}, model, key, "facts", max_tokens=ml.MAX_TOKENS["facts"],
        reserve_after=ml.reserve_levels(model, len(order)) + ml.reserve_review())
    if facts is None:
        return "budget" if blocked else "quality"
    done = {}
    for n, level in enumerate(order):
        after = ml.reserve_levels(model, len(order) - n - 1) + ml.reserve_review()
        data, c, used = ml.generate_level(level, {"stories": []}, [], dict(done), {}, key, model, after)
        if data is None:
            blocked_here = any(r["kind"] == "budget" for r in dl.read_json(ml.failures_path(), []) if r["date"] == key)
            return "budget" if blocked_here else "quality"
        done[level] = {"words": [], "stories": []}
    data, c, reasons, blocked = ml._ask(
        lambda fb: "x" * 38000, lambda d: [] if rng.random() > sc["p_review"] else ["x"], "r" * 3000, {},
        ml.review_model(), key, "review", effort=ml.REVIEW_EFFORT, max_tokens=ml.MAX_TOKENS["review"])
    if data is None:
        return "budget" if blocked else "quality"
    if rng.random() < sc["p_escalate"]:  # مراجعة عميقة اختيارية: إن لم تتسع الميزانية يبقى الدرس بنتيجة التدقيق الأساسي
        ml._ask(lambda fb: "x" * 6000, lambda d: [], "r" * 3000, {}, ml.review_model(), key, "review-deep",
                effort=ml.DEEP_EFFORT, max_tokens=ml.MAX_TOKENS["review_deep"], attempts=2)
    return "ok"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", type=int, default=300)
    ap.add_argument("--seed", type=int, default=1)
    args = ap.parse_args()
    print(f"محاكاة {args.runs} شهرًا × {DAYS} درسًا (سقف ${budget.monthly_limit():.2f})")
    for name, sc in SCENARIOS.items():
        rng = random.Random(args.seed)
        with contextlib.redirect_stdout(io.StringIO()):
            res = [simulate(sc, rng) for _ in range(args.runs)]
        d = [r["done"] for r in res]
        print(f"- {name}: دروس مكتملة متوسط {statistics.mean(d):.1f} (أدنى {min(d)}، وسيط {statistics.median(d)}، أعلى {max(d)}); "
              f"موقوفة بالميزانية {statistics.mean(r['budget'] for r in res):.1f}، "
              f"موقوفة بالجودة {statistics.mean(r['quality'] for r in res):.1f}؛ "
              f"الإنفاق المتوسط ${statistics.mean(r['spent'] for r in res):.2f}، الأقصى ${max(r['spent'] for r in res):.3f}")
    print("\nالسيناريو الواقعي مع موت المُشغِّل/إلغاء في 10% من الأيام (يضيع سجل اليوم ويحتسبه الدفتر بالاحتياطي):")
    rng = random.Random(args.seed)
    with contextlib.redirect_stdout(io.StringIO()):
        res = [simulate(SCENARIOS["واقعي"], rng, die=0.10) for _ in range(args.runs)]
    over = sum(1 for r in res if r["spent"] > budget.monthly_limit())
    print(f"- دروس مكتملة متوسط {statistics.mean(r['done'] for r in res):.1f}؛ الإنفاق الفعلي الأقصى ${max(r['spent'] for r in res):.3f}؛ "
          f"شهور تجاوزت 2.40: {over} من {args.runs}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
