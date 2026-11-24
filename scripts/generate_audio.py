#!/usr/bin/env python3
"""تحويل النصوص العربية في مجلد texts/ إلى ملفات MP3 عبر ElevenLabs.

- يقرأ مفتاح API من متغير البيئة ELEVENLABS_API_KEY فقط (لا يُكتب في الكود).
- يتخطى أي نص سبق توليده ولم يتغير (بالاعتماد على بصمة SHA-256 في audio/manifest.json)
  حتى لا يُستهلك الرصيد مرتين.
- وضع --dry-run لا يتصل بـ ElevenLabs إطلاقًا، ويعرض فقط ما سيتم توليده وعدد الأحرف.
- حدود أمان: --limit (عدد الملفات) و --max-chars (إجمالي الأحرف في التشغيلة الواحدة)
  و --daily-max-chars (إجمالي الأحرف في اليوم بحسب المنطقة الزمنية، يُسجَّل في audio/usage.json).
- --check-balance يفحص صلاحية المفتاح والرصيد فقط دون توليد أي صوت (لا يستهلك رصيدًا).

يعتمد على مكتبة بايثون القياسية فقط.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

API_BASE = "https://api.elevenlabs.io/v1"
DEFAULT_MODEL = "eleven_multilingual_v2"  # يدعم العربية
DEFAULT_VOICE_ID = "21m00Tcm4TlvDq8ikWAM"  # صوت جاهز من مكتبة ElevenLabs؛ غيّره عبر ELEVENLABS_VOICE_ID
DEFAULT_OUTPUT_FORMAT = "mp3_44100_128"
MAX_CHUNK_CHARS = 2500  # أقل بكثير من حد الطلب الواحد للنموذج، لثبات الجودة

ROOT = Path(__file__).resolve().parent.parent
TEXTS_DIR = ROOT / "texts"
AUDIO_DIR = ROOT / "audio"
MANIFEST_PATH = AUDIO_DIR / "manifest.json"
DEFAULT_TIMEZONE = "America/Toronto"
USAGE_HISTORY_DAYS = 90


@dataclass
class Job:
    source: Path
    output: Path
    text: str
    digest: str

    @property
    def chars(self) -> int:
        return len(self.text)


def read_text(path: Path) -> str:
    text = path.read_text(encoding="utf-8-sig")
    # توحيد المسافات مع الحفاظ على فواصل الفقرات
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def load_manifest(path: Path = MANIFEST_PATH) -> dict:
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return {}


def save_manifest(manifest: dict, path: Path = MANIFEST_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def load_usage(path: Path) -> dict:
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return {}


def save_usage(usage: dict, path: Path) -> None:
    keep = dict(sorted(usage.items())[-USAGE_HISTORY_DAYS:])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(keep, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def local_date(tz: str) -> str:
    return datetime.now(ZoneInfo(tz)).strftime("%Y-%m-%d")


def split_text(text: str, max_chars: int = MAX_CHUNK_CHARS) -> list[str]:
    """يقسم النص الطويل إلى أجزاء عند حدود الفقرات/الجمل العربية."""
    if len(text) <= max_chars:
        return [text]
    # حدود الجمل: . ! ? ؟ ؛ والسطر الجديد
    sentences = re.split(r"(?<=[.!?؟؛\n])\s+", text)
    chunks: list[str] = []
    current = ""
    for sentence in sentences:
        while len(sentence) > max_chars:  # جملة واحدة أطول من الحد: قصّ عند مسافة
            cut = sentence.rfind(" ", 0, max_chars)
            cut = cut if cut > 0 else max_chars
            if current:
                chunks.append(current.strip())
                current = ""
            chunks.append(sentence[:cut].strip())
            sentence = sentence[cut:].strip()
        if current and len(current) + 1 + len(sentence) > max_chars:
            chunks.append(current.strip())
            current = sentence
        else:
            current = f"{current} {sentence}" if current else sentence
    if current.strip():
        chunks.append(current.strip())
    return [c for c in chunks if c]


def collect_jobs(
    texts_dir: Path,
    audio_dir: Path,
    manifest: dict,
    only: str | None = None,
    force: bool = False,
) -> list[Job]:
    jobs: list[Job] = []
    for src in sorted(texts_dir.glob("*.txt")):
        if only and src.name != only and src.stem != only:
            continue
        text = read_text(src)
        if not text:
            continue
        digest = sha256(text)
        out = audio_dir / f"{src.stem}.mp3"
        entry = manifest.get(src.name, {})
        if not force and out.exists() and entry.get("sha256") == digest:
            continue  # مولَّد مسبقًا ولم يتغير
        jobs.append(Job(src, out, text, digest))
    return jobs


_REQUEST_ID = re.compile(
    r"""["']?\b(?:x-)?request[_-]?id["']?\s*[:=]\s*["']?[A-Za-z0-9_.-]+["']?,?\s*|\breq_[A-Za-z0-9]+""", re.I)


def sanitize(message: str) -> str:
    """يحذف معرّفات الطلبات من رسائل الأخطاء قبل طباعتها في السجلات العامة."""
    return _REQUEST_ID.sub("", str(message))


def _error_detail(raw: str) -> str:
    """يختصر رد الخطأ إلى الحالة والرسالة فقط (دون معرّف الطلب أو أي بيانات حساب)."""
    try:
        data = json.loads(raw)
        d = data.get("detail", data) if isinstance(data, dict) else data
        if isinstance(d, dict):
            return f"{d.get('status') or d.get('code') or ''}: {d.get('message', '')}".strip(": ")
    except (ValueError, AttributeError):
        pass
    return sanitize(raw)


def api_request(
    method: str,
    path: str,
    api_key: str,
    body: dict | None = None,
    query: str = "",
    timeout: int = 180,
) -> bytes:
    url = f"{API_BASE}{path}{query}"
    data = json.dumps(body).encode("utf-8") if body is not None else None
    headers = {"xi-api-key": api_key, "Accept": "*/*"}
    if data is not None:
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    last_err: Exception | None = None
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.read()
        except urllib.error.HTTPError as e:
            detail = _error_detail(e.read().decode("utf-8", "replace"))[:300]
            # 429/5xx قابلة لإعادة المحاولة؛ غيرها (401، 402، 422...) خطأ نهائي
            if e.code == 429 or e.code >= 500:
                last_err = RuntimeError(f"HTTP {e.code}: {detail}")
                time.sleep(2 ** attempt * 3)
                continue
            raise RuntimeError(f"HTTP {e.code}: {detail}") from None
        except urllib.error.URLError as e:
            last_err = e
            time.sleep(2 ** attempt * 3)
    raise RuntimeError(sanitize(f"فشل الطلب بعد عدة محاولات: {last_err}"))


def remaining_characters(api_key: str) -> int | None:
    """يقرأ الرصيد المتبقي (لا يستهلك رصيدًا).

    يحتاج المفتاح إلى صلاحية User → Read (user_read). يعيد None إن تعذّرت القراءة.
    """
    try:
        info = json.loads(api_request("GET", "/user/subscription", api_key, timeout=30))
        return int(info["character_limit"]) - int(info["character_count"])
    except Exception as e:  # noqa: BLE001
        msg = str(e)
        if "missing_permissions" in msg or "HTTP 401" in msg:
            print("تنبيه: المفتاح لا يملك صلاحية قراءة الرصيد (User → Read / user_read).")
        else:
            print(f"تنبيه: تعذر قراءة الرصيد المتبقي ({sanitize(msg)[:200]}).")
        return None


def synthesize(text: str, api_key: str, voice_id: str, model_id: str, output_format: str) -> bytes:
    chunks = split_text(text)
    audio = bytearray()
    for i, chunk in enumerate(chunks):
        body = {
            "text": chunk,
            "model_id": model_id,
            "voice_settings": {"stability": 0.5, "similarity_boost": 0.75},
        }
        # سياق الأجزاء المجاورة لتحسين اتصال النطق (لا يُحتسب ضمن الأحرف المولّدة)
        if i > 0:
            body["previous_text"] = chunks[i - 1][-300:]
        if i < len(chunks) - 1:
            body["next_text"] = chunks[i + 1][:300]
        audio += api_request(
            "POST",
            f"/text-to-speech/{voice_id}",
            api_key,
            body=body,
            query=f"?output_format={output_format}",
        )
    return bytes(audio)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="تحويل النصوص العربية إلى MP3 عبر ElevenLabs")
    p.add_argument("--dry-run", action="store_true", help="عرض ما سيُولَّد دون الاتصال بـ ElevenLabs")
    p.add_argument("--limit", type=int, default=0, help="أقصى عدد ملفات في التشغيلة (0 = بلا حد)")
    p.add_argument("--max-chars", type=int, default=0, help="أقصى مجموع أحرف في التشغيلة (0 = بلا حد)")
    p.add_argument("--file", default=None, help="توليد ملف واحد فقط (الاسم مع .txt أو بدونه)")
    p.add_argument("--force", action="store_true", help="إعادة التوليد حتى لو لم يتغير النص")
    p.add_argument("--daily-max-chars", type=int, default=0, help="أقصى أحرف في اليوم المحلي (0 = بلا حد)")
    p.add_argument("--timezone", default=DEFAULT_TIMEZONE, help="المنطقة الزمنية لحساب اليوم")
    p.add_argument("--require-balance-check", action="store_true",
                   help="الإيقاف إن تعذر التحقق من الرصيد (بدل المتابعة)")
    p.add_argument("--check-balance", action="store_true",
                   help="فحص المفتاح والرصيد فقط دون توليد (لا يستهلك رصيدًا)")
    p.add_argument("--texts-dir", type=Path, default=TEXTS_DIR)
    p.add_argument("--audio-dir", type=Path, default=AUDIO_DIR)
    args = p.parse_args(argv)

    if args.check_balance:
        api_key = os.environ.get("ELEVENLABS_API_KEY", "").strip()
        if not api_key:
            print("خطأ: متغير البيئة ELEVENLABS_API_KEY غير مضبوط.", file=sys.stderr)
            return 2
        remaining = remaining_characters(api_key)
        if remaining is None:
            return 4
        # لا يُطبع رقم الرصيد لأن سجلات التشغيل قد تكون عامة
        enough = "يكفي" if remaining >= max(args.daily_max_chars, 1000) else "لا يكفي"
        print(f"المفتاح يعمل وصلاحية قراءة الرصيد متوفرة. الرصيد {enough} لحد يومي واحد.")
        return 0

    usage_path = args.audio_dir / "usage.json"
    usage = load_usage(usage_path)
    today = local_date(args.timezone)
    if args.daily_max_chars > 0:
        used_today = int(usage.get(today, 0))
        available_today = max(0, args.daily_max_chars - used_today)
        print(f"اليوم ({today}، {args.timezone}): استُخدم {used_today} من {args.daily_max_chars} حرف، "
              f"المتاح {available_today}")
        args.max_chars = (min(args.max_chars, available_today) if args.max_chars > 0
                          else available_today)
        if available_today == 0:
            print("تم بلوغ الحد اليومي. لا توليد اليوم.")
            return 0

    manifest_path = args.audio_dir / "manifest.json"
    manifest = load_manifest(manifest_path)
    jobs = collect_jobs(args.texts_dir, args.audio_dir, manifest, args.file, args.force)

    if args.file and not jobs:
        print(f"لا يوجد شيء لتوليده للملف '{args.file}' (غير موجود أو مولَّد مسبقًا).")
    if args.limit > 0:
        jobs = jobs[: args.limit]
    if args.max_chars > 0 or args.daily_max_chars > 0:
        selected, total = [], 0
        for job in jobs:
            if total + job.chars > args.max_chars:
                print(f"تخطي {job.source.name} ({job.chars} حرف): يتجاوز حد --max-chars={args.max_chars}")
                continue
            selected.append(job)
            total += job.chars
        jobs = selected

    total_chars = sum(j.chars for j in jobs)
    print(f"الملفات المطلوب توليدها: {len(jobs)} | مجموع الأحرف (تقدير الرصيد): {total_chars}")
    for job in jobs:
        print(f"  - {job.source.name} -> {job.output.name} ({job.chars} حرف، {len(split_text(job.text))} جزء)")

    if not jobs:
        print("لا يوجد عمل جديد. لم يُستهلك أي رصيد.")
        return 0
    if args.dry_run:
        print("وضع التجربة (dry-run): لم يتم الاتصال بـ ElevenLabs ولم يُستهلك أي رصيد.")
        return 0

    api_key = os.environ.get("ELEVENLABS_API_KEY", "").strip()
    if not api_key:
        print("خطأ: متغير البيئة ELEVENLABS_API_KEY غير مضبوط.", file=sys.stderr)
        return 2
    voice_id = os.environ.get("ELEVENLABS_VOICE_ID", "").strip() or DEFAULT_VOICE_ID
    model_id = os.environ.get("ELEVENLABS_MODEL_ID", "").strip() or DEFAULT_MODEL
    output_format = os.environ.get("ELEVENLABS_OUTPUT_FORMAT", "").strip() or DEFAULT_OUTPUT_FORMAT

    remaining = remaining_characters(api_key)
    if remaining is None and args.require_balance_check:
        print("خطأ: تعذر التحقق من الرصيد، أُلغيت التشغيلة دون استهلاك.", file=sys.stderr)
        return 4
    if remaining is not None:
        if remaining >= total_chars:
            print("الرصيد كافٍ لهذه التشغيلة.")
        else:
            print("خطأ: الرصيد غير كافٍ لهذه التشغيلة. أُلغيت دون استهلاك.", file=sys.stderr)
            return 3

    args.audio_dir.mkdir(parents=True, exist_ok=True)
    failures = 0
    for job in jobs:
        print(f"توليد {job.output.name} ...")
        try:
            audio = synthesize(job.text, api_key, voice_id, model_id, output_format)
        except RuntimeError as e:
            failures += 1
            print(f"  فشل: {sanitize(e)}", file=sys.stderr)
            if "HTTP 401" in str(e) or "quota_exceeded" in str(e):
                print("  إيقاف بقية الملفات (مفتاح غير صالح أو نفاد الرصيد).", file=sys.stderr)
                break
            continue
        job.output.write_bytes(audio)
        manifest[job.source.name] = {
            "sha256": job.digest,
            "output": job.output.name,
            "chars": job.chars,
            "voice_id": voice_id,
            "model_id": model_id,
            "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
        save_manifest(manifest, manifest_path)  # حفظ بعد كل ملف حتى لا يضيع ما تم
        usage[today] = int(usage.get(today, 0)) + job.chars
        save_usage(usage, usage_path)
        print(f"  تم: {job.output} ({len(audio) // 1024} KB)")

    print(f"انتهى: {len(jobs) - failures} نجح، {failures} فشل.")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
