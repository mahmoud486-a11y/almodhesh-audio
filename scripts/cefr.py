"""فحوص مستوى CEFR وتمايز المستويات ودعم النص للأسئلة والحقائق — كلها محلية، بلا أي استدعاء API.

مبدأ العمل: لا يوجد مقياس آلي كامل لمستوى CEFR، لذلك تُجمَع عدة مؤشرات مستقلة، ويُرفض النص إذا خالف أيًّا منها:
  1. بنية الجمل: عدد الجمل، متوسط طول الجملة وأطولها.
  2. القابلية للقراءة: مقياس Flesch–Kincaid (مع متوسط مقاطع الكلمة).
  3. التعقيد النحوي: المبني للمجهول، المضارع التام، الجمل التابعة والموصولة، المصدر والمشتقات (-ing) في بداية العبارات.
  4. صعوبة المفردات: نسبة الكلمات الطويلة/متعددة المقاطع غير الشائعة، وقائمة الكلمات الأساسية المضمّنة (CORE_WORDS).
  5. التمايز: ترتيب المؤشرات بين المستويات (A < B < C) بفروق دنيا، وتشابه نصي أقصى بين مستويين.
  6. دعم الحقائق: لا أرقام ولا أسماء في النص خارج حقائق الخبر.
  7. دعم الأسئلة: كل كلمة جوهرية في السؤال وفي الإجابة الصحيحة موجودة في نص المستوى نفسه.

حدود هذه الفحوص (تُذكر بصراحة): قائمة الكلمات الأساسية صغيرة ومضمّنة، وليست قائمة CEFR رسمية؛ لذلك يقدّر فحص مفردات
الكلمات العشرين الصعوبة تقريبيًا (شيوع + طول + مقاطع). إن وُضع ملف data/cefr-words.tsv (كلمة<TAB>A1|A2|B1|B2|C1|C2) من قائمة
مفتوحة الترخيص مثل CEFR-J فإن الوحدة تستخدمه تلقائيًا فوق هذه الفحوص.
المرجع التعليمي: وصف المستويات في الإطار الأوروبي المرجعي المشترك للغات (مجلس أوروبا).
"""
from __future__ import annotations

import difflib
import re
from pathlib import Path

WORD_RE = re.compile(r"[A-Za-z][A-Za-z'’-]*")
SENT_RE = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9\"“])")
LEVEL_RANK = {"beginner": 0, "intermediate": 1, "advanced": 2}

# كلمات أساسية شائعة (مستوى A1–B1 تقريبًا): لا تُعدّ «صعبة» ولا تصلح مفردات لمستوى متقدم
CORE_WORDS = set("""
about above across act add afraid after again age ago agree air all allow almost alone along already also always among
and angry animal another answer any anyone apple arm around arrive art ask away baby back bad bag ball bank bed before
begin behind believe best better between big bike bird birthday black blue boat body book born both box boy bread break
bring brother build bus business busy buy call car card care carry case cat catch center change check child children
choose city class clean clear close clothes cold color come company continue cook cool cost country course cut dad dance
dark daughter day dead dear decide different difficult dinner do doctor dog door down draw dress drink drive during each
early earth easy eat egg end enough even evening every example expect eye face fall family far fast father feel few field
fill find fine finish fire first fish floor fly follow food foot for forget forward free friend front fruit full fun
future game garden get gift girl give glass go good great green ground group grow guess hair half hand happen happy hard
hat have head health hear heart heavy help here high hold holiday home hope horse hospital hot hotel hour house however
hundred hurry idea important inside interest island job join jump keep key kid kill kind king kitchen know lady lake
land language large last late laugh learn leave left leg lesson let letter life light like line list listen little live
long look lose lot love low lunch machine main make man many map market matter may mean meet member message middle mile
milk minute miss money month more morning mother mountain mouth move movie much music name near need never new news next
nice night noise north nose note nothing notice now number ocean offer office often old once only open order other
outside own page paper parent park part party pass past pay people person pick picture piece place plan plant play
please point police poor power practice present pretty price problem program pull put question quick quiet rain read
ready real reason remember rest rice rich ride right river road room round rule run sad safe same sand save say school
sea seat second see sell send sentence set several share sheep shirt shoe shop short show sick side sign simple sing
sister sit size skin sky sleep slow small smile snow some someone something sometimes son song soon sorry sound south
speak special spend sport spring stand star start state station stay step stop store story street strong student study
subject summer sun sure sweet swim table take talk tall taste tea teach teacher team tell test thank thing think thousand
time tired today together tomorrow tonight too top town toy train travel tree trip true try turn under understand until
use usual village visit voice wait walk wall want warm wash watch water way weather week welcome west wet white whole why
wide wife wind window winter wish woman wonder word work world worry write wrong year yellow young
restaurant restaurants cafe cafes menu menus calorie calories flight flights meeting content according taking
agreement airline airlines announce announced area attend available bank banks beautiful become behind benefit better
bridge budget build building capital century challenge chance choice city common community condition control cover
create culture daily danger decision describe develop dinner discuss discussion doctor dollar early economy education
effect effort election energy engine enough environment event exercise experience explain fact factory fair festival
figure final follow foreign future general government growth guide history hospital hotel human important include
increase information international issue journey leader local maybe meaning meeting member mention minister ministers
modern nation national natural normal officer official officials operation opinion pain patient peace period personal
plan police policy popular population possible post prepare president pressure private process produce product project
protect public quality reach recent record region report require research result return review rule safety science
season service services share simple society solution special speech sport stage standard station success support
system tax technology term thought tour trade traffic travel union university value various weather western worker
""".split())

FUNCTION_LIKE = set("""a an the and or but so if as at by in on of to for from with into onto over under about after before than then
that this these those there here it its he she they we you i me him her them us his their our your my is are was were be
been being am do does did has have had will would can could shall should may might must not no yes very more most much
many some any all each both other such own same just also too only up down out off again""".split())

SUBORDINATORS = {"although", "though", "while", "whereas", "because", "since", "unless", "whether", "despite", "following",
                 "after", "before", "until", "once", "as", "if", "when", "which", "who", "whom", "whose", "where"}
PASSIVE_RE = re.compile(r"\b(?:is|are|was|were|be|been|being|will be|has been|have been|had been)\s+(?:\w+ly\s+)?(?:\w+ed|\w+en|made|done|held|set|sent|built|given|taken|known|shown|seen|told|paid|put|left|found)\b", re.I)
PERFECT_RE = re.compile(r"\b(?:has|have|had)\s+(?:\w+ly\s+)?(?:\w+ed|\w+en|been|made|done|held|set|sent|built|given|taken|shown|seen|told|paid|put|left|found|begun|become|gone|run|won|come)\b", re.I)
PARTICIPLE_RE = re.compile(r",\s+(?:\w+ing|\w+ed)\b")
INFINITIVE_MARKER_RE = re.compile(r"\b(?:expected|due|required|scheduled|slated|set|likely|obliged|planned|aims?|seeks?)\s+to\s+\w+", re.I)
NOUN_STYLE_RE = re.compile(r"\b\w+(?:tion|sion|ment|ness|ity|ance|ence)\b", re.I)

# حدود كل مستوى (تُضبط على نماذج مراجَعة بشريًا)
PROFILES = {
    "beginner": {"avg_sentence": (5, 11.5), "max_sentence": 17, "avg_syllables": (1.0, 1.55), "fk_grade": (0, 6.0),
                 "hard_ratio": (0.0, 0.10), "passive": (0, 0), "perfect": (0, 1), "subordinate": (0, 1),
                 "complexity_per_100": (0.0, 4.0)},
    "intermediate": {"avg_sentence": (11, 25), "max_sentence": 32, "avg_syllables": (1.35, 1.85), "fk_grade": (5.0, 14.0),
                     "hard_ratio": (0.0, 0.30), "passive": (0, 3), "perfect": (0, 3), "subordinate": (0, 5),
                     "complexity_per_100": (0.0, 20.0)},
    "advanced": {"avg_sentence": (19, 45), "max_sentence": 60, "avg_syllables": (1.38, 2.6), "fk_grade": (11.0, 30.0),
                 "hard_ratio": (0.0, 1.0), "passive": (0, 99), "perfect": (0, 99), "subordinate": (0, 99),
                 "complexity_per_100": (5.0, 99.0)},
}
# أقل فرق بين مستويين متتاليين (المستوى الأعلى أكبر من الأدنى بهذا الفرق على الأقل)
MIN_GAPS = {"avg_sentence": 2.0, "fk_grade": 1.0, "complexity_per_100": 0.5}
MAX_SIMILARITY = 0.80  # نسبة تشابه الأحرف القصوى بين نصَّي مستويين


def syllables(word: str) -> int:
    w = re.sub(r"[^a-z]", "", word.lower())
    if not w:
        return 1
    groups = re.findall(r"[aeiouy]+", w)
    n = len(groups)
    if w.endswith("e") and not w.endswith(("le", "ee", "ye")) and n > 1:
        n -= 1
    if w.endswith("es") or w.endswith("ed"):
        if n > 1 and not re.search(r"(?:t|d)ed$|(?:s|x|z|ch|sh|c|g)es$", w):
            n -= 1
    return max(1, n)


def sentences(text: str) -> list[str]:
    return [s for s in SENT_RE.split(text.strip()) if s.strip()]


def words_of(text: str) -> list[str]:
    return WORD_RE.findall(text)


def is_hard(word: str, proper: bool) -> bool:
    w = word.lower().strip("'’-")
    if proper or w in CORE_WORDS or w in FUNCTION_LIKE:
        return False
    return syllables(w) >= 3 or len(w) >= 9


def _is_proper(word: str, first: bool) -> bool:
    """اسم علم: كلمة بحرف كبير في وسط الجملة، أو في أولها إن لم تكن كلمة شائعة."""
    if not word[:1].isupper():
        return False
    return not first or word.lower() not in CORE_WORDS | FUNCTION_LIKE


def metrics(texts: list[str]) -> dict:
    sents = [s for t in texts for s in sentences(t)]
    all_toks = [(w, _is_proper(w, i == 0)) for s in sents for i, w in enumerate(words_of(s))]
    toks = [(w, p) for w, p in all_toks if not p] or all_toks  # الأسماء العلم لا تُحسب في صعوبة الكلمات
    n_words = max(1, len(toks))
    lengths = [len(words_of(s)) for s in sents] or [0]
    syll = sum(syllables(w) for w, _ in toks) / n_words
    avg_len = sum(lengths) / len(lengths)
    fk = 0.39 * avg_len + 11.8 * syll - 15.59
    joined = " ".join(texts)
    passive = len(PASSIVE_RE.findall(joined))
    perfect = len(PERFECT_RE.findall(joined))
    sub = sum(1 for w, _ in toks if w.lower() in SUBORDINATORS)
    part = len(PARTICIPLE_RE.findall(joined))
    inf = len(INFINITIVE_MARKER_RE.findall(joined))
    noun = len(NOUN_STYLE_RE.findall(joined))
    complexity = (passive * 2 + perfect + sub + part * 2 + inf * 2 + noun * 0.5) * 100 / n_words
    hard = sum(1 for w, p in toks if is_hard(w, p)) / n_words
    return {"sentences": len(sents), "avg_sentence": avg_len, "max_sentence": max(lengths), "avg_syllables": syll,
            "fk_grade": fk, "hard_ratio": hard, "passive": passive, "perfect": perfect, "subordinate": sub,
            "participles": part, "infinitives": inf, "complexity_per_100": complexity, "words": n_words}


def _range(name: str, value: float, lo: float, hi: float, level: str) -> str | None:
    if lo <= value <= hi:
        return None
    return f"CEFR {level}: {name} is {value:.2f}, expected {lo:g}–{hi:g}"


def validate_text_level(level: str, texts: list[str]) -> list[str]:
    """مؤشرات النص (الأخبار الثلاثة معًا) ضمن حدود المستوى."""
    prof, m, errors = PROFILES[level], metrics(texts), []
    for name in ("avg_sentence", "avg_syllables", "fk_grade", "hard_ratio", "passive", "perfect", "subordinate", "complexity_per_100"):
        lo, hi = prof[name]
        e = _range(name, m[name], lo, hi, level)
        if e:
            errors.append(e)
    if m["max_sentence"] > prof["max_sentence"]:
        errors.append(f"CEFR {level}: longest sentence has {m['max_sentence']} words, at most {prof['max_sentence']}")
    return errors


def similarity(a: list[str], b: list[str]) -> float:
    return difflib.SequenceMatcher(None, " ".join(a).lower(), " ".join(b).lower()).ratio()


def validate_differentiation(level: str, texts: list[str], others: dict[str, list[str]]) -> list[str]:
    """النص يختلف فعلًا عن نصوص المستويات الأخرى: ترتيب المؤشرات بفروق دنيا، وتشابه نصي أقصى."""
    errors, mine = [], metrics(texts)
    for other, other_texts in others.items():
        if other == level:
            continue
        if texts == other_texts:
            errors.append(f"the {level} stories are identical to the {other} stories")
            continue
        sim = similarity(texts, other_texts)
        if sim > MAX_SIMILARITY:
            errors.append(f"the {level} stories are {sim:.0%} similar to the {other} stories (at most {MAX_SIMILARITY:.0%}); "
                          "rewrite them with different sentence structure and vocabulary")
        theirs = metrics(other_texts)
        higher = LEVEL_RANK[level] > LEVEL_RANK[other]
        for name, gap in MIN_GAPS.items():
            diff = mine[name] - theirs[name]
            if higher and diff < gap:
                errors.append(f"{name} of {level} ({mine[name]:.2f}) must be at least {gap:g} higher than {other} ({theirs[name]:.2f})")
            if not higher and -diff < gap:
                errors.append(f"{name} of {level} ({mine[name]:.2f}) must be at least {gap:g} lower than {other} ({theirs[name]:.2f})")
    return errors


# ---- مفردات المستوى (العشرون كلمة)
_WORDLIST: dict[str, str] | None = None


def external_wordlist() -> dict[str, str]:
    global _WORDLIST
    if _WORDLIST is None:
        _WORDLIST = {}
        path = Path(__file__).resolve().parent.parent / "data" / "cefr-words.tsv"
        if path.exists():
            for line in path.read_text(encoding="utf-8").splitlines():
                parts = line.split("\t")
                if len(parts) >= 2 and parts[1].strip().upper() in ("A1", "A2", "B1", "B2", "C1", "C2"):
                    _WORDLIST[parts[0].strip().lower()] = parts[1].strip().upper()
    return _WORDLIST


def word_difficulty(word: str) -> int:
    """0 أساسية، 1 متوسطة، 2 متقدمة (تقدير: قائمة الكلمات الأساسية + الطول + المقاطع + اللاحقات)."""
    w = word.lower().strip("'’-")
    ext = external_wordlist().get(w)
    if ext:
        return {"A1": 0, "A2": 0, "B1": 1, "B2": 1, "C1": 2, "C2": 2}[ext]
    if w in CORE_WORDS:
        return 0
    n = syllables(w)
    if n >= 3 or len(w) >= 9:
        return 2
    if n == 2 or len(w) >= 6:
        return 1
    return 0


def validate_words(level: str, words: list[str]) -> list[str]:
    """الكلمات العشرون مناسبة للمستوى (تقريبيًا)، وليست أسماء علم."""
    errors = []
    proper = [w for w in words if w[:1].isupper()]
    if proper:
        errors.append(f"vocabulary words must not be proper names or demonyms: {', '.join(proper)}")
    d = [word_difficulty(w) for w in words]
    n = max(1, len(d))
    basic, advanced = d.count(0) / n, d.count(2) / n
    if level == "beginner":
        if advanced > 0.15:
            hard = [w for w, x in zip(words, d) if x == 2]
            errors.append(f"CEFR beginner: too many difficult words ({', '.join(hard)}); choose common everyday words")
    elif level == "intermediate":
        if advanced > 0.40:
            errors.append("CEFR intermediate: too many advanced words; choose common news and work vocabulary")
        if basic > 0.70:
            errors.append("CEFR intermediate: too many very basic words; choose B1–B2 vocabulary")
    else:
        if basic > 0.35:
            easy = [w for w, x in zip(words, d) if x == 0]
            errors.append(f"CEFR advanced: {len(easy)} of 20 words are too basic for C1–C2 ({', '.join(easy)}); "
                          "choose precise, formal or academic words")
    return errors


# ---- دعم الحقائق: لا أرقام ولا أسماء خارج حقائق الخبر
def _stem(word: str) -> str:
    return re.sub(r"[^a-z]", "", word.lower())[:5]


def _names(text: str) -> set[str]:
    out = set()
    for s in sentences(text):
        for i, w in enumerate(words_of(s)):
            if w[:1].isupper() and (i > 0 or w.lower() not in FUNCTION_LIKE | {"two", "three", "four"}):
                out.add(w.lower())
    return out


def validate_fact_support(texts: list[str], facts: list[list[str]]) -> list[str]:
    """كل رقم واسم علم في نص الخبر يجب أن يرد في حقائقه (مع قبول المشتق: Saudi/Turkish/Pakistani)."""
    errors = []
    for n, (text, fs) in enumerate(zip(texts, facts), 1):
        src = " ".join(fs)
        src_nums = set(re.findall(r"\d[\d,.]*", src.replace(",", "")))
        for num in re.findall(r"\d[\d,.]*", text.replace(",", "")):
            if num.strip(".") not in {x.strip(".") for x in src_nums}:
                errors.append(f"story {n}: the number {num} is not in the facts")
        src_stems = {_stem(w) for w in words_of(src)}
        src_stems |= {w[:4] for w in (_stem(x) for x in words_of(src)) if len(w) >= 4}
        for name in sorted(_names(text)):
            st = _stem(name)
            if st not in src_stems and st[:4] not in {s[:4] for s in src_stems}:
                errors.append(f"story {n}: the name {name!r} is not in the facts; do not add information")
    return errors


# ---- دعم الأسئلة: كل إجابة مدعومة بنص المستوى
GENERIC_QUESTION_WORDS = set("""what why how who whom when where which does do did will would can could is are was were be
been has have had mean means meaning most likely best main according text story article idea sentence word phrase
context inferred infer suggest suggests implied imply happen happened happens say says said about of the a an to in on
for from with by at as that this these those it its they them their according first second third following true
correct statement reason purpose result""".split())


def _content_stems(text: str) -> list[str]:
    return [_stem(w) for w in words_of(text) if w.lower() not in GENERIC_QUESTION_WORDS and w.lower() not in FUNCTION_LIKE
            and len(w) > 2 and _stem(w)]


def _missing_words(text: str, have: set[str]) -> list[str]:
    seen, out = set(), []
    for w in words_of(text):
        st = _stem(w)
        if (w.lower() not in GENERIC_QUESTION_WORDS and w.lower() not in FUNCTION_LIKE and len(w) > 2 and st
                and st not in have and st not in seen):
            seen.add(st)
            out.append(w)
    return out


def validate_exercise_support(exercises: list[dict], texts: list[str]) -> list[str]:
    """السؤال والإجابة الصحيحة يعتمدان على نص المستوى نفسه (لا على الحقائق ولا على معلومة خارجية)."""
    errors = []
    corpus = " ".join(texts)
    have = {_stem(w) for w in words_of(corpus)}
    digits = set(re.findall(r"\d+", corpus))
    for n, e in enumerate(exercises, 1):
        q, opts, ans = e.get("question", ""), e.get("options", []), e.get("answer")
        if not isinstance(ans, int) or not 0 <= ans < len(opts):
            continue  # يُبلَّغ عنه في فحوص البنية
        quoted = re.findall(r"['\"“‘]([^'\"”’]+)['\"”’]", q)
        meaning_q = bool(re.search(r"\bmean(s|ing)?\b", q, re.I)) and bool(quoted)
        q_missing = _missing_words(q, have)
        if meaning_q:
            q_missing = [w for w in q_missing if not any(_stem(w) == _stem(x) for x in quoted)]
            for x in quoted:
                if _stem(x) not in have:
                    errors.append(f"exercise {n}: the word '{x}' in the question does not appear in the stories")
        if len(q_missing) > 1:
            errors.append(f"exercise {n}: the question uses words that are not in the lesson text ({', '.join(q_missing)}); "
                          "ask only about what the stories say")
        correct = opts[ans]
        if not meaning_q:
            toks = _content_stems(correct)
            nums = set(re.findall(r"\d+", correct))
            supported = [s for s in toks if s in have]
            if nums and not nums <= digits:
                errors.append(f"exercise {n}: the correct answer {correct!r} contains a number that is not in the stories")
            elif toks and len(supported) / len(toks) < 0.6:
                errors.append(f"exercise {n}: the correct answer {correct!r} is not supported by the lesson text")
        for k, o in enumerate(opts):
            if k == ans:
                continue
            toks = _content_stems(o)
            if toks and all(s in have for s in toks) and len(toks) >= 2 and not meaning_q:
                errors.append(f"exercise {n}: the wrong option {o!r} is also supported by the text (ambiguous)")
    return errors
