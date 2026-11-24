// اختبار الأسبوع: عشرة أسئلة من دروس الأيام الخمسة (الأحد–الخميس)، يُفتح يومي الجمعة والسبت.
// يُبنى من بيانات الدروس الموجودة في الصفحة (لا اتصال بأي خدمة، ولا تكلفة).
// يعتمد على متغيرات app.js العامة: lessons, lessonDate, lessonAudio, utter, stopPlayback, activeHumanAudio.
(function () {
  const DAYS = 5;
  const QUESTIONS = 10;
  const store = {
    get(k, d) { try { const v = localStorage.getItem(k); return v === null ? d : JSON.parse(v); } catch { return d; } },
    set(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch {} }
  };
  const shuffle = a => { a = [...a]; for (let i = a.length - 1; i > 0; i--) { const j = Math.floor(Math.random() * (i + 1)); [a[i], a[j]] = [a[j], a[i]]; } return a; };
  const pick = (arr, n, except) => shuffle([...new Set(arr)].filter(x => x !== except)).slice(0, n);
  const escapeRe = s => s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const MONTHS = ["يناير", "فبراير", "مارس", "أبريل", "مايو", "يونيو", "يوليو", "أغسطس", "سبتمبر", "أكتوبر", "نوفمبر", "ديسمبر"];
  const label = key => { const [, m, d] = key.split("-").map(Number); return `${d} ${MONTHS[m - 1]}`; };

  // دروس آخر 5 أيام حتى أحدث درس
  function weekKeys() {
    const end = new Date(lessonDate + "T12:00:00");
    const start = new Date(end); start.setDate(start.getDate() - (DAYS - 1));
    return Object.keys(lessons).filter(k => { const d = new Date(k + "T12:00:00"); return d >= start && d <= end; }).sort().reverse();
  }

  function buildQuestions(keys) {
    const words = [], stories = [];
    keys.forEach(key => {
      lessons[key].words.forEach(([en, ar]) => { if (en && ar && !/\s/.test(en.trim())) words.push({ en, ar, key }); });
      lessons[key].stories.forEach((s, i) => stories.push({ ...s, key, i }));
    });
    const meanings = words.map(w => w.ar), english = words.map(w => w.en);
    const wq = shuffle(words), qs = [];
    const from = key => `من درس ${label(key)}`;

    wq.slice(0, 4).forEach(w => qs.push({ kind: "معنى الكلمة", from: from(w.key),
      prompt: `ما معنى كلمة <b dir="ltr">${w.en}</b>؟`, options: shuffle([w.ar, ...pick(meanings, 3, w.ar)]), answer: w.ar }));
    wq.slice(4, 6).forEach(w => qs.push({ kind: "اختر الكلمة", from: from(w.key), ltr: true,
      prompt: `ما الكلمة الإنجليزية التي تعني «${w.ar}»؟`, options: shuffle([w.en, ...pick(english, 3, w.en)]), answer: w.en }));
    shuffle(stories).slice(0, 2).forEach(s => qs.push({ kind: "استماع", from: from(s.key), listen: s,
      prompt: "استمع إلى الجملة، ثم اختر ترجمتها الصحيحة.", options: shuffle([s.ar, ...pick(stories.map(x => x.ar), 3, s.ar)]), answer: s.ar }));
    const blanks = [];
    stories.forEach(s => wq.slice(6).forEach(w => {
      if (w.key !== s.key) return;
      const re = new RegExp(`(^|[^A-Za-zÀ-ÿ'-])(${escapeRe(w.en)})(?=[^A-Za-zÀ-ÿ'-]|$)`, "i");
      if (re.test(s.en)) blanks.push({ s, w, re });
    }));
    shuffle(blanks).filter((b, i, a) => a.findIndex(x => x.s === b.s) === i).slice(0, 2).forEach(({ s, w, re }) => qs.push({
      kind: "أكمل الجملة", from: from(s.key), ltr: true,
      prompt: `<span dir="ltr" class="quiz-sentence">${s.en.replace(re, (m, p) => `${p}_____`)}</span>`,
      options: shuffle([w.en, ...pick(english.filter(e => e.toLowerCase() !== w.en.toLowerCase()), 3)]), answer: w.en }));
    let extra = 6; // إن قلّت جمل الإكمال نكمل بأسئلة معنى
    while (qs.length < QUESTIONS && wq[extra]) { const w = wq[extra++];
      qs.push({ kind: "معنى الكلمة", from: from(w.key), prompt: `ما معنى كلمة <b dir="ltr">${w.en}</b>؟`,
        options: shuffle([w.ar, ...pick(meanings, 3, w.ar)]), answer: w.ar }); }
    return shuffle(qs).slice(0, QUESTIONS);
  }

  // تشغيل جملة من أي درس في الأسبوع: تسجيل ElevenLabs إن وُجد، وإلا صوت المتصفح
  function play(s) {
    stopPlayback();
    const url = lessonAudio[s.key]?.[s.i];
    if (!url) { speechSynthesis.speak(utter(s.en, 1)); return; }
    const audio = new Audio(url);
    activeHumanAudio = audio;
    audio.onended = () => { if (activeHumanAudio === audio) activeHumanAudio = null; };
    audio.onerror = () => { if (activeHumanAudio === audio) activeHumanAudio = null; speechSynthesis.speak(utter(s.en, 1)); };
    audio.play().catch(() => speechSynthesis.speak(utter(s.en, 1)));
  }

  let state = null;
  const keys = weekKeys();
  const bestKey = `quiz-week-best-${keys[keys.length - 1] || ""}-${lessonDate}`;
  // يُعرض في تبويب «الاختبار الأسبوعي» في الأعلى
  function section() {
    let el = document.getElementById("weeklyQuiz");
    if (!el) {
      el = document.createElement("div");
      el.id = "weeklyQuiz";
      el.className = "quiz weekly-view";
      document.getElementById("weekly").append(el);
    }
    return el;
  }
  function renderIntro() {
    const best = store.get(bestKey, null);
    const range = keys.length > 1 ? `${label(keys[keys.length - 1])} – ${label(keys[0])}` : label(keys[0]);
    section().innerHTML = `
      <div class="section-title"><p class="eyebrow">يوم المراجعة · دروس الأسبوع</p><h2>اختبار الأسبوع</h2></div>
      <article class="quiz-card">
        <p class="quiz-lead">عشرة أسئلة من دروس الأسبوع (${keys.length} ${keys.length > 2 && keys.length < 11 ? "دروس" : "درس"}، ${range}): معانٍ، استماع، وإكمال جمل.</p>
        ${best !== null ? `<p class="quiz-best">أفضل نتيجة لك هذا الأسبوع: <b>${best}/${QUESTIONS}</b></p>` : ""}
        <button type="button" class="quiz-start">${best !== null ? "↻ أعد اختبار الأسبوع" : "ابدأ اختبار الأسبوع"}</button>
      </article>`;
    section().querySelector(".quiz-start").onclick = start;
  }
  function start() { state = { qs: buildQuestions(keys), i: 0, score: 0 }; renderQuestion(); }
  function renderQuestion() {
    const q = state.qs[state.i];
    section().innerHTML = `
      <div class="section-title"><p class="eyebrow">اختبار الأسبوع · ${q.kind} · ${q.from}</p><h2>السؤال ${state.i + 1} من ${state.qs.length}</h2></div>
      <article class="quiz-card">
        <div class="quiz-progress"><span style="width:${(state.i / state.qs.length) * 100}%"></span></div>
        <p class="quiz-prompt">${q.prompt}</p>
        ${q.listen ? `<button type="button" class="quiz-listen">▶ استمع</button>` : ""}
        <div class="quiz-options">${q.options.map((o, k) => `<button type="button" class="quiz-option" data-k="${k}" ${q.ltr ? 'dir="ltr"' : ""}>${o}</button>`).join("")}</div>
        <p class="quiz-feedback" aria-live="polite"></p>
        <button type="button" class="quiz-next" hidden>${state.i + 1 < state.qs.length ? "السؤال التالي ←" : "النتيجة ←"}</button>
      </article>`;
    const el = section();
    if (q.listen) { el.querySelector(".quiz-listen").onclick = () => play(q.listen); play(q.listen); }
    el.querySelectorAll(".quiz-option").forEach(b => b.onclick = () => answer(b));
    el.querySelector(".quiz-next").onclick = () => { stopPlayback(); state.i++; state.i < state.qs.length ? renderQuestion() : finish(); };
  }
  function answer(btn) {
    const q = state.qs[state.i];
    const ok = q.options[+btn.dataset.k] === q.answer;
    if (ok) state.score++;
    section().querySelectorAll(".quiz-option").forEach(b => { b.disabled = true; if (q.options[+b.dataset.k] === q.answer) b.classList.add("correct"); });
    if (!ok) btn.classList.add("wrong");
    section().querySelector(".quiz-feedback").textContent = ok ? "✓ إجابة صحيحة!" : "✗ ليست هذه. الإجابة الصحيحة مظلّلة بالأخضر.";
    section().querySelector(".quiz-next").hidden = false;
  }
  function finish() {
    store.set(bestKey, Math.max(state.score, store.get(bestKey, 0)));
    window.dispatchEvent(new Event("almodhesh:quiz-done"));
    const pct = state.score / state.qs.length;
    const msg = pct === 1 ? "ممتاز! أتقنت كلمات الأسبوع 🎉" : pct >= 0.7 ? "أحسنت! مراجعتك قوية." : "راجع دروس الأرشيف ثم أعد المحاولة.";
    section().innerHTML = `
      <div class="section-title"><p class="eyebrow">اختبار الأسبوع</p><h2>النتيجة: ${state.score} من ${state.qs.length}</h2></div>
      <article class="quiz-card quiz-result">
        <p class="quiz-score">${msg}</p>
        <button type="button" class="quiz-start">↻ أعد اختبار الأسبوع</button>
      </article>`;
    section().querySelector(".quiz-start").onclick = start;
  }

  // يُفتح يومي الجمعة والسبت فقط؛ وفي بقية الأيام بطاقة صغيرة تذكّر بموعده
  const reviewDay = [5, 6].includes(new Date().getDay());
  function renderLocked() {
    section().innerHTML = `
      <div class="section-title"><p class="eyebrow">مراجعة نهاية الأسبوع</p><h2>اختبار الأسبوع</h2></div>
      <article class="quiz-card">
        <p class="quiz-lead">🔒 يُفتح يومي <b>الجمعة والسبت</b>: عشرة أسئلة تراجع دروس الأحد إلى الخميس.</p>
      </article>`;
  }
  if (keys.length) reviewDay ? renderIntro() : renderLocked();
})();
