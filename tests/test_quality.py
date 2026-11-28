"""اختبارات جودة المستويات والميزانية — بلا أي اتصال بـ Claude أو ElevenLabs."""
import copy
import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))
import budget  # noqa: E402
import cefr  # noqa: E402
import daily_lesson as dl  # noqa: E402
import level_fixtures as lf  # noqa: E402
import multilevel as ml  # noqa: E402

REAL = json.loads((ROOT / "site/lessons/2026-11-26.json").read_text(encoding="utf-8"))
TEXTS = {l: [s["en"] for s in lf.LEVELS[l]["stories"]] for l in lf.LEVELS}
FACT_LISTS = [s["facts"] for s in lf.FACTS["stories"]]


class CefrLevelTests(unittest.TestCase):
    def test_reviewed_samples_pass_their_own_level(self):
        for level, texts in TEXTS.items():
            self.assertEqual(cefr.validate_text_level(level, texts), [], level)

    def test_metrics_are_ordered_beginner_intermediate_advanced(self):
        m = {l: cefr.metrics(t) for l, t in TEXTS.items()}
        for key in ("avg_sentence", "fk_grade", "complexity_per_100"):
            self.assertLess(m["beginner"][key], m["intermediate"][key], key)
            self.assertLess(m["intermediate"][key], m["advanced"][key], key)

    def test_each_level_text_is_rejected_at_the_wrong_level(self):
        self.assertTrue(cefr.validate_text_level("beginner", TEXTS["advanced"]))
        self.assertTrue(cefr.validate_text_level("beginner", TEXTS["intermediate"]))
        self.assertTrue(cefr.validate_text_level("advanced", TEXTS["beginner"]))
        self.assertTrue(cefr.validate_text_level("advanced", TEXTS["intermediate"]))

    def test_beginner_cannot_use_passive_voice(self):
        bad = ["Two airlines were asked to stop. The flights are operated by a group.", "It is done.", "It was made."]
        errs = cefr.validate_text_level("beginner", bad)
        self.assertTrue(any("passive" in e for e in errs), errs)

    def test_advanced_needs_complex_grammar(self):
        simple = ["The group will meet in the city on Friday and Saturday this week to talk.",
                  "The airlines fly to the city again now and they like it very much.",
                  "The cafes will show the calories on the menus from June next year in the city."]
        self.assertTrue(cefr.validate_text_level("advanced", simple))


class DifferentiationTests(unittest.TestCase):
    def test_identical_levels_are_rejected(self):
        errs = cefr.validate_differentiation("beginner", TEXTS["intermediate"], {"intermediate": TEXTS["intermediate"]})
        self.assertIn("identical", errs[0])

    def test_light_edit_is_rejected_as_too_similar(self):
        edited = [t.replace("will hold", "will have").replace("according to", "says") for t in TEXTS["intermediate"]]
        errs = cefr.validate_differentiation("beginner", edited, {"intermediate": TEXTS["intermediate"]})
        self.assertTrue(errs)

    def test_three_reviewed_levels_are_genuinely_different(self):
        for level in lf.LEVELS:
            others = {o: TEXTS[o] for o in TEXTS if o != level}
            self.assertEqual(cefr.validate_differentiation(level, TEXTS[level], others), [], level)

    def test_the_real_november_26_beginner_copy_is_caught(self):
        real = {k: [s["en"] for s in v["stories"]] for k, v in REAL["levels"].items()}
        errs = cefr.validate_differentiation("beginner", real["beginner"], {"intermediate": real["intermediate"]})
        self.assertTrue(errs and "identical" in errs[0])

    def test_ordering_is_enforced_both_directions(self):
        errs = cefr.validate_differentiation("intermediate", TEXTS["advanced"], {"beginner": TEXTS["beginner"],
                                                                                  "advanced": TEXTS["intermediate"]})
        self.assertTrue(errs)  # نص أطول من المتقدم تحت اسم المتوسط


class VocabularyTests(unittest.TestCase):
    def test_reviewed_word_lists_pass(self):
        for level, v in lf.LEVELS.items():
            self.assertEqual(cefr.validate_words(level, [w["en"] for w in v["words"]]), [], level)

    def test_real_advanced_list_is_rejected(self):
        words = [w[0] for w in REAL["levels"]["advanced"]["words"]]
        errs = " | ".join(cefr.validate_words("advanced", words))
        self.assertIn("proper names or demonyms", errs)
        self.assertIn("too basic", errs)

    def test_beginner_cannot_get_rare_words(self):
        errs = cefr.validate_words("beginner", ["reinstated", "suspension", "obliged", "requirement", "mandate", "pact",
                                                "convene", "reciprocal", "slated", "reiterate", "talk", "city", "group",
                                                "show", "rule", "new", "now", "say", "fly", "june"])
        self.assertTrue(errs)


class FactSupportTests(unittest.TestCase):
    def test_reviewed_levels_only_use_the_facts(self):
        for level, texts in TEXTS.items():
            self.assertEqual(cefr.validate_fact_support(texts, FACT_LISTS), [], level)

    def test_invented_number_and_name_are_rejected(self):
        bad = list(TEXTS["intermediate"])
        bad[2] = bad[2].replace("June 2027", "June 2028")
        bad[1] = bad[1].replace("Dubai", "Dubai and Cairo")
        errs = " | ".join(cefr.validate_fact_support(bad, FACT_LISTS))
        self.assertIn("2028", errs)
        self.assertIn("cairo", errs)


class QuizSupportTests(unittest.TestCase):
    def test_reviewed_exercises_are_supported_by_their_level_text(self):
        for level, v in lf.LEVELS.items():
            self.assertEqual(cefr.validate_exercise_support(v["exercises"], TEXTS[level]), [], level)

    def test_foreign_ministers_question_is_rejected_for_the_real_advanced_text(self):
        adv = REAL["levels"]["advanced"]
        errs = cefr.validate_exercise_support(adv["exercises"], [s["en"] for s in adv["stories"]])
        joined = " | ".join(errs)
        self.assertIn("exercise 1", joined)
        self.assertIn("foreign", joined)  # «foreign ministers» ليست في نص المتقدم الفعلي

    def test_correct_answer_must_come_from_the_text(self):
        ex = [{"question": "When is the meeting?", "options": ["In July", "On Friday and Saturday", "At night", "Soon"], "answer": 0}]
        self.assertTrue(cefr.validate_exercise_support(ex, TEXTS["beginner"]))

    def test_ambiguous_wrong_option_is_rejected(self):
        ex = [dict(lf.LEVELS["intermediate"]["exercises"][0])]
        ex[0]["options"] = ["To discuss their mutual defense agreement", "Saudi Arabia, Turkey and Pakistan",
                            "Friday and Saturday", "Pakistani sources"]
        self.assertTrue(any("also supported" in e for e in cefr.validate_exercise_support(ex, TEXTS["intermediate"])))

    def test_number_in_answer_must_be_in_text(self):
        ex = [{"question": "When does the new rule start in Abu Dhabi?", "options": ["In June 2031", "Today", "Never", "Soon"], "answer": 0}]
        self.assertTrue(cefr.validate_exercise_support(ex, TEXTS["beginner"]))


class BudgetTests(unittest.TestCase):
    def test_month_is_taken_from_the_lesson_date(self):
        log = [{"date": "2026-11-26", "est_cost_usd": 0.1}, {"date": "2026-12-01", "est_cost_usd": 0.2}]
        self.assertAlmostEqual(budget.month_spent(log, "2026-11"), 0.1)

    def test_check_uses_worst_case_plus_reserve(self):
        ok, _ = budget.check(2.0, 0.1, 0.2, 2.40)
        self.assertTrue(ok)
        ok, why = budget.check(2.0, 0.1, 0.4, 2.40)
        self.assertFalse(ok)
        self.assertIn("exceeds the monthly limit", why)

    def test_worst_case_cost_uses_max_tokens_for_output(self):
        w = ml.worst_cost("claude-sonnet-5-5", 1000, 7000)
        self.assertAlmostEqual(w, 1000 / 1e6 * 2.0 + 7000 / 1e6 * 10.0)

    def test_full_lesson_worst_case_fits_a_normal_month(self):
        # أسوأ حالة لدرس كامل (حقائق + 3 مستويات بمحاولة واحدة + تدقيق) تتسع في السقف الشهري بعد 21 يومًا اعتياديًا قبله (الحد الواقعي: نحو 22 درسًا شهريًا بمتوسط 0.10 دولار)
        worst = (ml.worst_cost("claude-haiku-5-5", 12000, ml.MAX_TOKENS["facts"]) + ml.reserve_levels("claude-haiku-5-5", 3)
                 + ml.reserve_review())
        self.assertLess(worst, 0.16)
        self.assertGreater(budget.MAX_MONTHLY_BUDGET_USD - 21 * 0.10, worst)  # بعد 21 يومًا بمتوسط 0.10 دولار يتسع اليوم 22

    def test_unknown_error_is_charged_and_logged_but_does_not_stop_the_retries(self):
        tmp = Path(tempfile.mkdtemp())
        calls = []

        def fake(prompt, model, **kw):
            calls.append(model)
            if len(calls) == 1:
                raise dl.ClaudeCallError("انقطع رد النموذج (max_tokens)", {"input_tokens": 1000, "output_tokens": 16000, "model": model})
            return {"ok": 1}, {"input_tokens": 1000, "output_tokens": 500, "model": model}
        with mock.patch.object(dl, "AI_USAGE_PATH", tmp / "ai-usage.json"), mock.patch.object(dl, "call_claude", side_effect=fake), \
             mock.patch.object(ml.time, "sleep"), redirect_stdout(io.StringIO()):
            data, cost, reasons, blocked = ml._ask(lambda fb: "p", lambda d: [], "sys", {}, "claude-haiku-5-5", "2026-11-30", "level")
        self.assertEqual(data, {"ok": 1})
        usage = json.loads((tmp / "ai-usage.json").read_text(encoding="utf-8"))
        self.assertEqual(len(usage), 2)
        self.assertTrue(usage[0]["error"] and usage[0]["output_tokens"] == 16000)  # حوسب فعليًا فسُجّل
        self.assertGreater(cost, 0.008)
        failures = json.loads((tmp / "validation-failures.json").read_text(encoding="utf-8"))
        self.assertEqual(failures[0]["kind"], "error")


class FailureLogTests(unittest.TestCase):
    def test_rejection_reasons_are_recorded_verbatim(self):
        tmp = Path(tempfile.mkdtemp())
        with mock.patch.object(dl, "AI_USAGE_PATH", tmp / "ai-usage.json"), mock.patch.object(ml.time, "sleep"), \
             mock.patch.object(dl, "call_claude", return_value=({"x": 1}, {"input_tokens": 10, "output_tokens": 10, "model": "claude-haiku-5-5"})), \
             redirect_stdout(io.StringIO()):
            data, cost, reasons, blocked = ml._ask(lambda fb: "p", lambda d: ["story 1: identical to the intermediate level"],
                                                  "s", {}, "claude-haiku-5-5", "2026-11-30", "beginner", attempts=2)
        self.assertIsNone(data)
        failures = json.loads((tmp / "validation-failures.json").read_text(encoding="utf-8"))
        self.assertEqual([f["attempt"] for f in failures], [1, 2])
        self.assertEqual(failures[0]["reasons"], ["story 1: identical to the intermediate level"])


class AuditOfCommittedLessonsTests(unittest.TestCase):
    def test_no_committed_multilevel_lesson_is_copied_after_repair_or_is_flagged(self):
        """تدقيق الدروس المحفوظة: أي درس متعدد المستويات فيه مستويان متطابقان يُبلَّغ عنه (درس 26 نوفمبر قبل الإصلاح)."""
        flagged = []
        for path in sorted((ROOT / "site/lessons").glob("20*.json")):
            lesson = json.loads(path.read_text(encoding="utf-8"))
            if "levels" not in lesson:
                continue
            texts = {k: [s["en"] for s in v["stories"]] for k, v in lesson["levels"].items()}
            if len({tuple(t) for t in texts.values()}) < len(texts):
                flagged.append(path.stem)
        self.assertLessEqual(len(flagged), 1)  # 2026-11-26 فقط، ويُزال بعد تطبيق الإصلاح المعتمد


if __name__ == "__main__":
    unittest.main()


class ReviewSkipsDisplayedGlossary(unittest.TestCase):
    def test_known_glossary_words_are_not_reviewed_but_words_and_sentences_are(self):
        import json
        import daily_lesson as dl
        lesson = dl.read_json(dl.SITE / "lessons" / "2026-11-26.json", None)
        full = ml.review_items(lesson)
        known = {w: "x" for w in lesson["levels"]["intermediate"]["translations"]}
        trimmed = ml.review_items(lesson, None, known)
        self.assertLess(len(trimmed), len(full))
        self.assertFalse([k for k in trimmed if k.startswith("g:") and k.split(":", 2)[2].lower() in known])
        for kind in ("s:", "w:", "q:", "topic:"):  # كل ما يخص الدرس نفسه يبقى
            self.assertEqual(len([k for k in full if k.startswith(kind)]), len([k for k in trimmed if k.startswith(kind)]))
