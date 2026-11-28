"""بلاغ فشل النشر (GitHub Issue) يصل بالبريد: يذكر المالك بـ @ ويُسنَد إليه، فيصله إشعار حتى لو لم يكن «مراقبًا» للمستودع.
وضع --test يفتح بلاغ اختبار مجانيًا (دون Claude أو ElevenLabs) للتأكد من وصول البريد قبل الاعتماد عليه.
التشغيل في GitHub Actions بالمتغيرات: GH_TOKEN, OWNER, RUN_URL, DAY. لا يطبع أسرارًا."""
from __future__ import annotations

import argparse
import json
import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FAILURES = ROOT / "logs" / "validation-failures.json"


def reasons_text(path: Path = FAILURES, last: int = 12) -> str:
    rows = json.loads(path.read_text(encoding="utf-8"))[-last:] if path.exists() else []
    lines = [f"- {r['date']} | {r['step']} | {r['model']} | محاولة {r['attempt']} | {r['kind']}: " + "; ".join(r["reasons"])[:300]
             for r in rows]
    return "\n".join(lines) or "لا أسباب مسجَّلة (راجع سجل التشغيلة)"


def build(day: str, owner: str, run_url: str, test: bool, reasons: str) -> tuple[str, str]:
    mention = f"@{owner}\n\n" if owner else ""
    if test:
        return (f"🔔 المدهش: اختبار الإشعار {day}",
                f"{mention}هذا بلاغ اختباري مجاني (لا استدعاءات مدفوعة). إن وصلك بالبريد فإشعارات الفشل ستصلك.\n\nالتشغيلة: {run_url}")
    return (f"⚠️ المدهش: لم يُنشر درس {day}",
            f"{mention}لم يُنشر درس اليوم، ويبقى آخر درس صالح منشورًا. لم يُنسخ نص بين المستويات.\n\n"
            f"التشغيلة: {run_url}\n\nآخر أسباب الرفض المسجَّلة:\n{reasons}")


def run_gh(args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(["gh", *args], capture_output=True, text=True)


def notify(day: str, owner: str, run_url: str, test: bool, gh=run_gh, reasons: str | None = None) -> str:
    title, body = build(day, owner, run_url, test, reasons if reasons is not None else reasons_text())
    found = gh(["issue", "list", "--state", "open", "--search", f"in:title {title}", "--json", "number", "--jq", ".[0].number"])
    number = (found.stdout or "").strip()
    if number:
        gh(["issue", "comment", number, "--body", body])
        return f"comment #{number}"
    cmd = ["issue", "create", "--title", title, "--body", body]
    res = gh(cmd + (["--assignee", owner] if owner else []))
    if res.returncode != 0 and owner:  # الإسناد قد يفشل؛ الذكر بـ @ يكفي للإشعار
        res = gh(cmd)
    if res.returncode != 0:
        raise SystemExit(f"تعذر فتح البلاغ: {(res.stderr or '')[:300]}")
    return "created"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--test", action="store_true")
    a = ap.parse_args()
    print(notify(os.environ.get("DAY", ""), os.environ.get("OWNER", ""), os.environ.get("RUN_URL", ""), a.test))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
