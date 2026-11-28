"""بيانات اختبار واقعية: الأخبار الثلاثة نفسها (درس 26 نوفمبر) بالمستويات الثلاثة، مراجَعة بالفحوص الآلية.

تُستخدم في الاختبارات وفي إصلاح مستوى المبتدئ لذلك اليوم (الأقسام الإنجليزية والعربية كتبها مراجِع بشري/Claude هنا،
فلا يلزم أي استدعاء مدفوع لتوليدها). كل المستويات تمر بـ multilevel.validate_level كما هو.
"""
import re

FACTS = {
    "archive_title": "سياسة، اقتصاد وصحة",
    "stories": [
        {"news_id": 1, "category": "politics", "country": "Saudi Arabia", "topic": "دفاع مشترك ثلاثي",
         "facts": ["Saudi Arabia, Turkey and Pakistan will hold a meeting in Islamabad on their mutual defense agreement.",
                   "The meeting is scheduled for Friday and Saturday, according to two Pakistani sources.",
                   "The foreign ministers of Saudi Arabia and Turkey are arriving in Pakistan to attend the meeting."]},
        {"news_id": 2, "category": "economy", "country": "United Arab Emirates", "topic": "رحلات إلى دبي",
         "facts": ["Lufthansa Group and Air France have resumed flights to Dubai.",
                   "Dubai is a city in the United Arab Emirates."]},
        {"news_id": 3, "category": "health", "country": "United Arab Emirates", "topic": "السعرات في أبوظبي",
         "facts": ["Restaurants and cafes in Abu Dhabi will display calorie counts on their menus.",
                   "The calorie count requirement will start from June 2027."]},
    ],
}

_W = lambda pairs: [{"en": e, "ar": a} for e, a in pairs]

LEVELS = {
    "beginner": {
        "stories": [
            {"en": "Saudi Arabia, Turkey and Pakistan will have a meeting in Islamabad. They will talk about their defense "
                   "agreement. The meeting is on Friday and Saturday. Two Pakistani sources say this.",
             "ar": "ستعقد السعودية وتركيا وباكستان اجتماعاً في إسلام آباد. سيتحدثون عن اتفاقية الدفاع بينهم. "
                   "الاجتماع يومي الجمعة والسبت. يقول مصدران باكستانيان ذلك."},
            {"en": "Two airlines, Lufthansa Group and Air France, now fly to Dubai again. Dubai is a city in the United Arab Emirates.",
             "ar": "شركتا طيران، هما مجموعة لوفتهانزا وإير فرانس، تطيران إلى دبي من جديد الآن. دبي مدينة في الإمارات العربية المتحدة."},
            {"en": "Restaurants and cafes in Abu Dhabi must show the calories on their menus. The new rule starts in June 2027.",
             "ar": "يجب على المطاعم والمقاهي في أبوظبي أن تعرض السعرات الحرارية على قوائمها. تبدأ القاعدة الجديدة في يونيو 2027."},
        ],
        "words": _W([("talk", "يتحدث"), ("friday", "الجمعة"), ("saturday", "السبت"), ("fly", "يطير"), ("say", "يقول"),
                     ("now", "الآن"), ("group", "مجموعة"), ("show", "يعرض"), ("calories", "السعرات الحرارية"),
                     ("starts", "يبدأ"), ("june", "يونيو"), ("two", "اثنان"), ("new", "جديد"), ("rule", "قاعدة"),
                     ("meeting", "اجتماع"), ("agreement", "اتفاقية"), ("city", "مدينة"), ("restaurants", "مطاعم"),
                     ("cafes", "مقاهٍ"), ("airlines", "شركات طيران")]),
        "exercises": [
            {"question": "When is the meeting?", "question_ar": "متى الاجتماع؟",
             "options": ["On Friday and Saturday", "On Monday and Tuesday", "Every morning", "Next year"], "answer": 0},
            {"question": "Which two airlines fly to Dubai again?", "question_ar": "ما شركتا الطيران اللتان تطيران إلى دبي من جديد؟",
             "options": ["Lufthansa Group and Air France", "Qatar Airways and Etihad", "Emirates and Qatar Airways", "KLM and Delta"],
             "answer": 0},
            {"question": "When does the new rule start in Abu Dhabi?", "question_ar": "متى تبدأ القاعدة الجديدة في أبوظبي؟",
             "options": ["In June 2027", "In March 2026", "Next week", "Today"], "answer": 0},
        ],
        "glossary_ar": {
            "saudi": "السعودية", "arabia": "العربية", "turkey": "تركيا", "and": "و", "pakistan": "باكستان", "will": "سوف",
            "have": "يملك / يعقد", "a": "أداة تنكير", "meeting": "اجتماع", "in": "في", "islamabad": "إسلام آباد", "they": "هم",
            "talk": "يتحدث", "about": "عن", "their": "الخاص بهم", "defense": "الدفاع", "agreement": "اتفاقية", "the": "أداة تعريف",
            "is": "يكون", "on": "في / على", "friday": "الجمعة", "saturday": "السبت", "two": "اثنان", "pakistani": "باكستاني",
            "sources": "مصادر", "say": "يقول", "this": "هذا", "airlines": "شركات طيران", "lufthansa": "لوفتهانزا",
            "group": "مجموعة", "air": "إير", "france": "فرانس", "now": "الآن", "fly": "يطير", "to": "إلى", "dubai": "دبي",
            "again": "من جديد", "city": "مدينة", "united": "المتحدة", "arab": "العربية", "emirates": "الإمارات",
            "restaurants": "مطاعم", "cafes": "مقاهٍ", "abu": "أبو", "dhabi": "ظبي", "must": "يجب", "show": "يعرض",
            "calories": "السعرات الحرارية", "menus": "قوائم الطعام", "new": "جديد", "rule": "قاعدة", "starts": "يبدأ",
            "june": "يونيو",
        },
    },
    "intermediate": {
        "stories": [
            {"en": "Saudi Arabia, Turkey and Pakistan will hold a two-day meeting in Islamabad on Friday and Saturday to discuss "
                   "their mutual defense agreement, according to Pakistani sources.",
             "ar": "ستعقد السعودية وتركيا وباكستان اجتماعاً لمدة يومين في إسلام آباد يومي الجمعة والسبت لمناقشة اتفاقية "
                   "الدفاع المشترك بينها، بحسب مصادر باكستانية."},
            {"en": "Lufthansa Group and Air France have resumed flights to Dubai, a city in the United Arab Emirates.",
             "ar": "استأنفت مجموعة لوفتهانزا وإير فرانس رحلاتهما إلى دبي، وهي مدينة في الإمارات العربية المتحدة."},
            {"en": "Restaurants and cafes in Abu Dhabi will have to display calorie counts on their menus starting in June 2027.",
             "ar": "سيتعين على المطاعم والمقاهي في أبوظبي عرض السعرات الحرارية على قوائمها ابتداءً من يونيو 2027."},
        ],
        "words": _W([("hold", "يعقد"), ("two-day", "لمدة يومين"), ("discuss", "يناقش"), ("mutual", "مشترك"),
                     ("defense", "الدفاع"), ("according", "بحسب"), ("sources", "مصادر"), ("resumed", "استأنف"),
                     ("flights", "رحلات جوية"), ("display", "يعرض"), ("calorie", "سعر حراري"), ("counts", "أرقام"),
                     ("menus", "قوائم الطعام"), ("starting", "ابتداءً من"), ("meeting", "اجتماع"), ("agreement", "اتفاقية"),
                     ("city", "مدينة"), ("restaurants", "مطاعم"), ("cafes", "مقاهٍ"), ("group", "مجموعة")]),
        "exercises": [
            {"question": "Why will Saudi Arabia, Turkey and Pakistan meet in Islamabad?",
             "question_ar": "لماذا ستجتمع السعودية وتركيا وباكستان في إسلام آباد؟",
             "options": ["To discuss their mutual defense agreement", "To sell new airplanes", "To open new restaurants",
                         "To plan a football match"], "answer": 0},
            {"question": "Which companies have resumed flights to Dubai?", "question_ar": "ما الشركتان اللتان استأنفتا الرحلات إلى دبي؟",
             "options": ["Lufthansa Group and Air France", "Qatar Airways and Etihad", "Saudia and Turkish Airlines",
                         "Emirates and flydubai"], "answer": 0},
            {"question": "What must restaurants and cafes in Abu Dhabi display from June 2027?",
             "question_ar": "ماذا يجب أن تعرض المطاعم والمقاهي في أبوظبي ابتداءً من يونيو 2027؟",
             "options": ["Calorie counts on their menus", "Their staff names", "The price of every drink", "The number of customers"],
             "answer": 0},
        ],
    },
    "advanced": {
        "stories": [
            {"en": "Saudi Arabia, Turkey and Pakistan are scheduled to convene in Islamabad on Friday and Saturday to review their "
                   "mutual defense pact, with the Saudi and Turkish foreign ministers expected to attend, two Pakistani sources said.",
             "ar": "من المقرر أن تجتمع السعودية وتركيا وباكستان في إسلام آباد يومي الجمعة والسبت لمراجعة اتفاقية الدفاع "
                   "المشترك بينها، على أن يحضر وزيرا خارجية السعودية وتركيا، بحسب مصدرين باكستانيين."},
            {"en": "Lufthansa Group and Air France have reinstated their routes to Dubai, in the United Arab Emirates, "
                   "following a suspension of services.",
             "ar": "أعادت مجموعة لوفتهانزا وإير فرانس خطوطهما إلى دبي في الإمارات العربية المتحدة بعد توقف خدماتهما."},
            {"en": "Restaurants and cafes in Abu Dhabi will be obliged to display calorie information on their menus, with the "
                   "requirement taking effect in June 2027.",
             "ar": "ستُلزم المطاعم والمقاهي في أبوظبي بعرض معلومات السعرات الحرارية على قوائمها، على أن يبدأ سريان هذا "
                   "الإلزام في يونيو 2027."},
        ],
        "words": _W([("convene", "يجتمع"), ("defense", "الدفاع"), ("display", "يعرض"), ("expected", "متوقَّع"),
                     ("following", "بعد"), ("mutual", "مشترك"), ("obliged", "مُلزَم"), ("reinstated", "أعاد"),
                     ("requirement", "إلزام"), ("routes", "خطوط"), ("sources", "مصادر"), ("suspension", "تعليق"),
                     ("scheduled", "مقرر"), ("pact", "معاهدة"), ("effect", "سريان"), ("review", "يراجع"),
                     ("attend", "يحضر"), ("information", "معلومات"), ("ministers", "وزراء"), ("services", "خدمات")]),
        "exercises": [
            {"question": "Why are Saudi Arabia, Turkey and Pakistan scheduled to convene in Islamabad?",
             "question_ar": "لماذا من المقرر أن تجتمع السعودية وتركيا وباكستان في إسلام آباد؟",
             "options": ["To review their mutual defense pact", "To sign a trade deal", "To open a new airline",
                         "To discuss calorie rules"], "answer": 0},
            {"question": "What does 'reinstated' mean in the second story?", "question_ar": "ماذا تعني كلمة «reinstated» في الخبر الثاني؟",
             "options": ["Brought back into service", "Permanently cancelled", "Moved to another city", "Reduced in price"],
             "answer": 0},
            {"question": "What will restaurants and cafes in Abu Dhabi be obliged to display?",
             "question_ar": "ماذا ستُلزم المطاعم والمقاهي في أبوظبي بعرضه؟",
             "options": ["Calorie information on their menus", "Staff names on their doors", "Prices in two languages",
                         "Photos of every meal"], "answer": 0},
        ],
    },
}


def tokens_of(text):
    return list(dict.fromkeys(re.findall(r"[a-z][a-z'’-]*", text.lower())))


def level_answer(level, gloss_ar="ترجمة"):
    """رد Claude كما يصل من الواجهة (بنية LEVEL_SCHEMA)، مع قاموس كلمات كامل لكل كلمة في النصوص."""
    v = LEVELS[level]
    gloss = {t: v.get("glossary_ar", {}).get(t, gloss_ar) for t in tokens_of(" ".join(s["en"] for s in v["stories"]))}
    return {"stories": [dict(s) for s in v["stories"]], "words": [dict(w) for w in v["words"]],
            "translations": [{"word": k, "ar": a} for k, a in gloss.items()],
            "exercises": [dict(e, options=list(e["options"])) for e in v["exercises"]]}
