"""محاكاة شهر كامل (23 درسًا) دون أي اتصال: تستخدم حارس الميزانية الحقيقي و _ask و generate_level الحقيقيين،
وتستبدل فقط الاتصال بـ Claude بتكاليف مولَّدة عشوائيًا مضبوطة على الاستهلاك المقيس في logs/ai-usage.json.

الاستخدام: python3 tools/simulate_month.py [--runs 300] [--seed 1]
"""
from __future__ import annotations

import argparse
import contextlib
import io
import random
import statistics
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import daily_lesson as dl  # noqa: E402
import multilevel as ml  # noqa: E402

DAYS = 23  # أحد–خميس في ديسمبر 2026
SCENARIOS = {  # احتمال رفض محاولة Haiku لمستوى (التحقق الجديد أشد من القديم)، ورفض Sonnet، وخطأ API، وتجاوز max_tokens
    "متفائل":  dict(p_haiku=0.10, p_sonnet=0.20, p_err=0.01, p_trunc=0.01, p_review=0.03),
    "واقعي":   dict(p_haiku=0.30, p_sonnet=0.30, p_err=0.02, p_trunc=0.03, p_review=0.05),
    "متشائم":  dict(p_haiku=0.50, p_sonnet=0.40, p_err=0.04, p_trunc=0.05, p_review=0.10),
}


def simulate(sc: dict, rng: random.Random, workflow_fail: float = 0.0, lose_records: bool = False) -> dict:
    tmp = Path(tempfile.mkdtemp())
    dl.AI_USAGE_PATH = tmp / "ai-usage.json"
    state = {"step": ""}

    def fake_call(prompt, model, system=None, schema=None, effort="medium", max_tokens=16000):
        label = state["step"]
        if "sonnet" in model and label.endswith("fallback"):
            usage = {"input_tokens": rng.randint(2500, 4000), "output_tokens": rng.randint(4500, 7000), "model": model}
        elif label == "review":
            usage = {"input_tokens": rng.randint(14000, 20000), "output_tokens": rng.randint(3000, 6000), "model": model}
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
        sonnet = "sonnet" in state.get("model", "")
        return ["x"] if rng.random() < (sc["p_sonnet"] if sonnet else sc["p_haiku"]) else []

    orig = (dl.call_claude, ml.validate_level, ml.time.sleep)
    dl.call_claude, ml.validate_level, ml.time.sleep = fake_call, fake_validate_level, lambda s: None
    real_ask = ml._ask

    def tracking_ask(prompt_fn, validate_fn, system, schema, model, key, label, **kw):
        state["step"], state["model"] = label, model
        return real_ask(prompt_fn, validate_fn, system, schema, model, key, label, **kw)

    ml._ask = tracking_ask
    done = blocked_budget = blocked_quality = lost = 0
    true_total = 0.0
    try:
        import datetime as _d
        base = _d.date(2026, 12, 1)
        days = [base + _d.timedelta(days=i) for i in range(31)]
        sun_thu = [d for d in days if d.weekday() in (6, 0, 1, 2, 3)][:DAYS]  # الأحد=6
        for day in sun_thu:
            key = day.isoformat()
            snapshot = dl.read_json(dl.AI_USAGE_PATH, [])
            ok = _lesson(key, rng, sc)
            after_log = dl.read_json(dl.AI_USAGE_PATH, [])
            true_total += sum(e["est_cost_usd"] for e in after_log[len(snapshot):])
            if lose_records and rng.random() < workflow_fail:  # فشل سير العمل يُضيّع سجل اليوم (إن لم يُحفظ)
                dl.write_json(dl.AI_USAGE_PATH, snapshot)
                lost += 1
            if ok == "ok":
                done += 1
            elif ok == "budget":
                blocked_budget += 1
            else:
                blocked_quality += 1
        total = ml.budget.month_spent(dl.read_json(dl.AI_USAGE_PATH, []), "2026-12")
    finally:
        dl.call_claude, ml.validate_level, ml.time.sleep = orig
        ml._ask = real_ask
    return {"done": done, "budget": blocked_budget, "quality": blocked_quality, "spent": true_total, "recorded": total, "lost": lost}


def _lesson(key: str, rng: random.Random, sc: dict) -> str:
    order = sorted(ml.LEVEL_ORDER, key=lambda l: l != ml.DEFAULT_LEVEL)
    model = dl.DEFAULT_LESSON_MODEL
    ml.validate_facts = lambda d, items: []
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
            return "budget" if any(r["kind"] == "budget" for r in dl.read_json(ml.failures_path(), []) if r["date"] == key) else "quality"
        done[level] = {"words": [], "stories": []}
    data, c, reasons, blocked = ml._ask(
        lambda fb: "x" * 50000, lambda d: [] if rng.random() > sc["p_review"] else ["x"], "r" * 3000, {},
        ml.review_model(), key, "review", effort="high", max_tokens=ml.MAX_TOKENS["review"])
    return "ok" if data is not None else ("budget" if blocked else "quality")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", type=int, default=300)
    ap.add_argument("--seed", type=int, default=1)
    args = ap.parse_args()
    ml.failures_path = lambda: dl.AI_USAGE_PATH.with_name("validation-failures.json")
    print(f"محاكاة {args.runs} شهرًا × {DAYS} درسًا (سقف ${ml.budget.monthly_limit():.2f})")
    for name, sc in SCENARIOS.items():
        rng = random.Random(args.seed)
        with contextlib.redirect_stdout(io.StringIO()):
            res = [simulate(sc, rng) for _ in range(args.runs)]
        d = [r["done"] for r in res]
        print(f"- {name}: دروس مكتملة متوسط {statistics.mean(d):.1f} (أدنى {min(d)}، وسيط {statistics.median(d)}، أعلى {max(d)}); "
              f"موقوفة بالميزانية {statistics.mean(r['budget'] for r in res):.1f}، "
              f"موقوفة بالجودة {statistics.mean(r['quality'] for r in res):.1f}؛ "
              f"الإنفاق المتوسط ${statistics.mean(r['spent'] for r in res):.2f}، الأقصى ${max(r['spent'] for r in res):.3f}")
    print("\nلو ضاع سجل الاستهلاك في 10% من أيام الفشل (سير العمل القديم عند الإلغاء):")
    rng = random.Random(args.seed)
    with contextlib.redirect_stdout(io.StringIO()):
        res = [simulate(SCENARIOS["واقعي"], rng, workflow_fail=0.10, lose_records=True) for _ in range(args.runs)]
    over = sum(1 for r in res if r["spent"] > ml.budget.monthly_limit())
    print(f"- الإنفاق الفعلي الأقصى ${max(r['spent'] for r in res):.3f}؛ شهور تجاوزت 2.40: {over} من {args.runs}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
