"""دفتر التشغيلات: يضمن ألا يضيع أي استهلاك لـ Claude حتى لو مات المُشغِّل أو أُلغي سير العمل أو فشل الدفع.

الفكرة (كتابة مسبقة): قبل أي طلب مدفوع تُسجَّل التشغيلة «بدأت» في logs/run-ledger.json وتُدفع إلى المستودع، مع
احتياطي (سقفه 0.35 دولار وبحد ما تبقى من الشهر). عند انتهاء التشغيلة بسلام تُغلَق. فإن وجدت التشغيلة التالية دفترًا «بدأ» ولم يُغلَق
(انقطاع مفاجئ، أو فُقد سجلها)، تحتسب في ميزانية الشهر الفرق بين الاحتياطي وما سُجِّل فعلًا لتلك التشغيلة، بتاريخ
بدايتها. ولا تُرسَل أي طلبات قبل نجاح هذه الخطوة. استرجاع السجل الضائع: scripts/recover_usage.py.

الاستخدام: python3 scripts/ledger.py begin | end
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import budget  # noqa: E402
import daily_lesson as dl  # noqa: E402

STAMP = "%Y-%m-%dT%H:%M:%SZ"


def ledger_path() -> Path:
    return dl.AI_USAGE_PATH.with_name("run-ledger.json")


def run_id() -> str:
    rid = os.environ.get("GITHUB_RUN_ID", "").strip()
    return f"{rid}-{os.environ.get('GITHUB_RUN_ATTEMPT', '1')}" if rid else "local"


def lesson_reserve() -> float:
    """أسوأ تكلفة لدرس كامل بلا إعادات (الحقائق + 3 مستويات + التدقيق) — نفس تقديرات حارس الميزانية."""
    import multilevel as ml
    model = os.environ.get("LESSON_MODEL", "").strip() or dl.DEFAULT_LESSON_MODEL
    first = ml.worst_cost(model, 14000, ml.MAX_TOKENS["facts"])
    return round(first + ml.reserve_levels(model, 3) + ml.reserve_review(), 5)


RUN_RESERVE_CAP = 0.35  # أقصى ما تُحتسب به تشغيلة منقطعة: نحو ثلاثة أضعاف الدرس العادي (يغطي إعادات المحاولة وSonnet والمراجعة العميقة)


def run_reserve(now=None) -> float:
    """احتياطي التشغيلة: أسوأ مسار متوقع لدرس بإعاداته، ولا يتجاوز ما تبقى من ميزانية الشهر (الحارس يمنع أي طلب بعده)."""
    spent = budget.month_spent(dl.read_json(dl.AI_USAGE_PATH, []), budget.billing_month(now))
    return round(max(0.0, min(RUN_RESERVE_CAP, budget.monthly_limit() - spent)), 5)


def reconcile(now=None) -> float:
    """يحتسب تشغيلة سابقة لم تُغلق. يعيد المبلغ المضاف للميزانية (0 إن لا شيء)."""
    led = dl.read_json(ledger_path(), None)
    if not led or led.get("status") != "started" or led.get("run_id") == run_id():
        return 0.0
    log = dl.read_json(dl.AI_USAGE_PATH, [])
    recorded = sum(float(e.get("est_cost_usd", 0)) for e in log if e.get("run_id") == led["run_id"])
    penalty = round(max(0.0, float(led.get("reserved", 0)) - recorded), 5)
    if penalty > 0:
        log.append({"date": led.get("date", ""), "attempt": 0, "step": "unreconciled", "model": "n/a",
                    "input_tokens": 0, "output_tokens": 0, "est_cost_usd": penalty,
                    "at": led.get("started_at", (now or budget.utc_now()).strftime(STAMP)),
                    "run_id": led["run_id"], "unreconciled": True})
        dl.write_json(dl.AI_USAGE_PATH, log[-2000:])
    led["status"] = "reconciled"
    led["penalty_usd"] = penalty
    dl.write_json(ledger_path(), led)
    return penalty


def begin(date: str, now=None) -> float:
    penalty = reconcile(now)
    dl.write_json(ledger_path(), {"run_id": run_id(), "date": date, "status": "started",
                                  "reserved": run_reserve(now),
                                  "started_at": (now or budget.utc_now()).strftime(STAMP)})
    return penalty


def end(now=None) -> None:
    led = dl.read_json(ledger_path(), None)
    if led and led.get("status") == "started" and led.get("run_id") == run_id():
        led["status"] = "closed"
        led["closed_at"] = (now or budget.utc_now()).strftime(STAMP)
        dl.write_json(ledger_path(), led)


def main(argv=None) -> int:
    cmd = (argv or sys.argv[1:] or [""])[0]
    if cmd == "begin":
        day = dl.now_local().strftime("%Y-%m-%d")
        penalty = begin(day)
        print(f"دفتر التشغيلات: بدأت {run_id()} (احتياطي ${run_reserve():.4f})؛ غرامة تشغيلة سابقة غير مغلقة: ${penalty:.4f}")
        return 0
    if cmd == "end":
        end()
        return 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
