# almodhesh-audio

أتمتة تحويل النصوص العربية إلى ملفات صوتية MP3 باستخدام ElevenLabs و GitHub Actions.

## هيكل المشروع

| المسار | الوصف |
|---|---|
| `texts/` | ضع هنا النصوص العربية، كل نص في ملف `.txt` (ترميز UTF-8) |
| `audio/` | ملفات MP3 الناتجة + `manifest.json` (سجل ما تم توليده) |
| `scripts/generate_audio.py` | سكربت التحويل (بايثون، بدون مكتبات خارجية) |
| `tests/` | اختبارات لا تتصل بـ ElevenLabs ولا تستهلك رصيدًا |
| `.github/workflows/generate-audio.yml` | سير العمل في GitHub Actions |

## الأمان وحماية الرصيد

- المفتاح يُقرأ فقط من السر `ELEVENLABS_API_KEY` في GitHub Secrets، ولا يُكتب في أي ملف.
- التشغيل اليدوي يبدأ افتراضيًا بوضع **التجربة (dry-run)**: لا اتصال بـ ElevenLabs ولا استهلاك.
- النص الذي وُلِّد سابقًا ولم يتغير يُتخطى تلقائيًا (بصمة SHA-256 في `audio/manifest.json`).
- حدود افتراضية للتشغيل اليدوي: ملف واحد و500 حرف كحد أقصى.
- قبل التوليد يُفحص الرصيد المتبقي، وتُلغى التشغيلة إن لم يكفِ.
- **الجدولة اليومية معطّلة** حتى تتم الموافقة عليها.

## التشغيل اليدوي (الاختبار)

1. افتح تبويب **Actions** ثم **Generate Arabic audio (ElevenLabs)** ثم **Run workflow**.
2. أول تشغيلة: اترك `dry_run` مفعّلًا لترى ما سيُولَّد وعدد الأحرف.
3. ثاني تشغيلة: ألغِ `dry_run` لتوليد ملف الاختبار `texts/001-test.txt` (81 حرفًا تقريبًا).
   يظهر الملف الناتج في أسفل صفحة التشغيلة ضمن **Artifacts**.
4. لحفظ ملفات MP3 داخل المستودع فعّل خيار `commit`.
   (بدون `commit` لا يُحفظ سجل التوليد، فقد يُعاد توليد الملف نفسه في تشغيلة لاحقة.)

## الإعدادات الاختيارية (Repository variables)

من **Settings ← Secrets and variables ← Actions ← Variables**:

- `ELEVENLABS_VOICE_ID`: معرّف الصوت (الافتراضي صوت جاهز من مكتبة ElevenLabs).
- `ELEVENLABS_MODEL_ID`: النموذج (الافتراضي `eleven_multilingual_v2` الداعم للعربية).

## تفعيل الجدولة اليومية (بعد الموافقة فقط)

في `.github/workflows/generate-audio.yml` أزل علامة `#` من سطري `schedule` و `cron`.
التشغيل المجدول يولّد كل النصوص الجديدة (حتى 10 ملفات و10,000 حرف يوميًا) ويحفظها في المستودع.

## التشغيل المحلي

```bash
python3 scripts/generate_audio.py --dry-run
python3 -m unittest discover -s tests -v
```
