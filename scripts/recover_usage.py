"""دمج سجل استهلاك ضائع (من artifact «usage-logs-…» الذي يرفعه سير العمل عند فشل الدفع) في سجل المستودع.
يضيف الطلبات غير الموجودة (بحسب run_id + الوقت + الخطوة + المحاولة)، ويزيل غرامة «unreconciled» لتلك التشغيلة
لأن الاستهلاك الحقيقي صار معروفًا. لا يحذف شيئًا آخر.

الاستخدام: python3 scripts/recover_usage.py <مجلد logs المُنزَّل> [--dry-run]"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import daily_lesson as dl  # noqa: E402


def entry_key(e: dict):
    return (e.get("run_id"), e.get("at"), e.get("step"), e.get("attempt"), e.get("model"))


def merge(current: list[dict], recovered: list[dict]) -> tuple[list[dict], int, int]:
    have = {entry_key(e) for e in current}
    added = [e for e in recovered if entry_key(e) not in have and not e.get("unreconciled")]
    runs = {e.get("run_id") for e in added if e.get("run_id")}
    kept = [e for e in current if not (e.get("unreconciled") and e.get("run_id") in runs)]
    removed = len(current) - len(kept)
    merged = sorted(kept + added, key=lambda e: e.get("at") or "")
    return merged, len(added), removed


def main(argv: list[str]) -> int:
    if not argv:
        print(__doc__)
        return 2
    src = Path(argv[0]) / "ai-usage.json"
    recovered = json.loads(src.read_text(encoding="utf-8"))
    merged, added, removed = merge(dl.read_json(dl.AI_USAGE_PATH, []), recovered)
    print(f"أُضيف {added} طلبًا، وأُزيلت {removed} غرامة غير مطابقة.")
    if "--dry-run" not in argv:
        dl.write_json(dl.AI_USAGE_PATH, merged[-2000:])
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
