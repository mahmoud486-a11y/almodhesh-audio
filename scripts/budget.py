"""حارس ميزانية Claude الشهرية: يُفحص قبل كل استدعاء، بأسوأ تكلفة ممكنة للمدخلات والمخرجات.

القاعدة: الإنفاق المسجَّل هذا الشهر + أسوأ تكلفة لهذا الاستدعاء + أسوأ تكلفة للخطوات الإلزامية التي ستأتي بعده
(بقية المستويات والتدقيق اللغوي) يجب ألا يتجاوز السقف. وإلا لا يُرسَل الطلب أصلًا.

- السقف 2.40 دولار شهريًا؛ ويمكن خفضه بالمتغير CLAUDE_MONTHLY_BUDGET_USD لكن لا يمكن رفعه فوق 2.40.
- أسوأ تكلفة = (أقصى مدخلات مقدَّرة بتحفظ) × سعر الإدخال + max_tokens × سعر الإخراج (الإخراج لا يتجاوز max_tokens أبدًا).
- كل طلب يُسجَّل في logs/ai-usage.json بتكلفته الفعلية، بما فيه المرفوض والفاشل، وبتاريخ وقته الفعلي (UTC)؛
  فإصلاح درس قديم يُحسب في شهر إجرائه لا شهر الدرس. انتهاء المهلة (طلب قد يكون وصل) يُحتسب بأسوأ تكلفة.
"""
from __future__ import annotations

import math
import os
from datetime import datetime, timezone

MAX_MONTHLY_BUDGET_USD = 2.40
CHARS_PER_TOKEN = 2.0  # تقدير متحفظ: المُجزّئ الحديث يعطي رموزًا أكثر بنحو 30%، والعربية أكثر كلفة من الإنجليزية
# تسعير Haiku 5.5 يتضاعف لكل الطلب إن زاد طول المدخلات عن 100 ألف رمز (صفحة الأسعار الرسمية، تحققت منها 2026-11-27)
LONG_CONTEXT = {"claude-haiku-5-5": (100_000, 0.50, 2.50)}


class BudgetExceeded(RuntimeError):
    """لا يتسع السقف الشهري للطلب القادم (أو للخطوات الإلزامية التي تليه)."""


def monthly_limit() -> float:
    raw = os.environ.get("CLAUDE_MONTHLY_BUDGET_USD", "").strip()
    try:
        value = float(raw) if raw else MAX_MONTHLY_BUDGET_USD
    except ValueError:
        value = MAX_MONTHLY_BUDGET_USD
    return min(MAX_MONTHLY_BUDGET_USD, value) if value > 0 else MAX_MONTHLY_BUDGET_USD


def estimate_input_tokens(*texts: str) -> int:
    return math.ceil(sum(len(t or "") for t in texts) / CHARS_PER_TOKEN) + 50


def cost_of(prices: dict, model: str, input_tokens: int, output_tokens: int, default_model: str) -> float:
    inp, out = prices.get(model, prices[default_model])
    threshold = LONG_CONTEXT.get(model)
    if threshold and input_tokens > threshold[0]:
        inp, out = threshold[1], threshold[2]
    return input_tokens / 1e6 * inp + output_tokens / 1e6 * out


def utc_now() -> datetime:
    """وقت الفوترة الفعلي (UTC). دالة منفصلة كي يمكن تثبيتها في الاختبارات والمحاكاة."""
    return datetime.now(timezone.utc)


def billing_month(now: datetime | None = None) -> str:
    return (now or utc_now()).strftime("%Y-%m")


def entry_month(e: dict) -> str:
    """شهر الطلب بتاريخ الاستهلاك الفعلي (حقل at)، لا بتاريخ الدرس؛ والسجلات القديمة بلا at تعود لتاريخ الدرس."""
    return str(e.get("at") or e.get("date") or "")[:7]


def month_spent(log: list[dict], month: str) -> float:
    """مجموع التكلفة المسجّلة في شهر الفوترة (month بصيغة YYYY-MM) بحسب تاريخ الاستهلاك الفعلي."""
    return sum(float(e.get("est_cost_usd", 0)) for e in log if entry_month(e) == month)


def check(spent: float, worst_call: float, reserve_after: float, limit: float | None = None) -> tuple[bool, str]:
    limit = monthly_limit() if limit is None else limit
    need = spent + worst_call + reserve_after
    if need <= limit + 1e-12:
        return True, ""
    return False, (f"budget: spent ${spent:.4f} + this call (worst case) ${worst_call:.4f} + mandatory later steps "
                   f"${reserve_after:.4f} = ${need:.4f} exceeds the monthly limit ${limit:.2f}")
