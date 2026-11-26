// اختبار اليوم + سلسلة الأيام المتتالية 🔥
// يُبنى بالكامل من بيانات الدرس الموجودة في الصفحة (لا اتصال بأي خدمة، ولا تكلفة).
// يعتمد على متغيرات app.js العامة: activeKey, activeStories, activeWords, playStory, stopPlayback.
(function () {
  const QUESTIONS = 5;
  const store = {
    get(k, d) { try { const v = localStorage.getItem(k); return v === null ? d : JSON.parse(v); } catch { return d; } },
    set(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch {} }
  };
  const $ = s => document.querySelector(s);
  const shuffle = a => { a = [...a]; for (let i = a.length - 1; i > 0; i--) { const j = Math.floor(Math.random() * (i + 1)); [a[i], a[j]] = [a[j], a[i]]; } return a; };
  const pick = (arr, n, except) => shuffle(arr.filter(x => x !== except)).slice(0, n);
  const today = () => { const d = new Date(); return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`; };
  const escapeRe = s => s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  // أسئلة فهم الخبر (في الدروس متعددة المستويات فقط): سؤالان إضافيان
  const exercises = () => ((typeof lessons !== "undefined" && lessons[activeKey]) || {}).exercises || [];
  const total = () => QUESTIONS + Math.min(2, exercises().length);
  const bestKey = () => `quiz-best-${activeKey}` + (exercises().length && window.almodheshLevel ? `-${window.almodheshLevel}` : "");

  // ---------- السلسلة 🔥: أيام متتالية أُكمل فيها اختبار
  function streakInfo() {
    const days = new Set(store.get("quiz-days", []));
    let n = 0;
    const d = new Date();
    if (!days.has(today())) d.setDate(d.getDate() - 1); // لم يُختبر اليوم بعد: السلسلة حتى الأمس ما زالت قائمة
    for (;;) {
      const k = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
      if (!days.has(k)) break;
      n++; d.setDate(d.getDate() - 1);
    }
    return { n, doneToday: days.has(today()) };
  }
  function markToday() {
    const days = store.get("quiz-days", []);
    if (!days.includes(today())) { days.push(today()); store.set("quiz-days", days.slice(-400)); }
  }
  function renderStreak() {
    let el = $("#streakStat");
    if (!el) {
      el = document.createElement("span");
      el.id = "streakStat";
      $(".stats").append(el);
    }
    const { n } = streakInfo();
    el.innerHTML = `🔥 سلسلة الأيام: <b>${n}</b>`;
  }

  // ---------- بناء الأسئلة من الدرس النشط
  function buildQuestions() {
    const words = activeWords.filter(w => w[0] && w[1] && !/\s/.test(w[0].trim()));
    const stories = activeStories;
    const meanings = [...new Set(words.map(w => w[1]))];
    const english = [...new Set(words.map(w => w[0]))];
    const qs = [];
    const wordQ = shuffle(words);

    // سؤالان: معنى الكلمة بالعربية
    wordQ.slice(0, 2).forEach(([en, ar]) => qs.push({
      kind: "معنى الكلمة", prompt: `ما معنى كلمة <b dir="ltr">${en}</b>؟`,
      options: shuffle([ar, ...pick(meanings, 3, ar)]), answer: ar
    }));
    // سؤال: الكلمة الإنجليزية المقابلة
    const [en3, ar3] = wordQ[2];
    qs.push({
      kind: "اختر الكلمة", prompt: `ما الكلمة الإنجليزية التي تعني «${ar3}»؟`,
      options: shuffle([en3, ...pick(english, 3, en3)]), answer: en3, ltr: true
    });
    // سؤال استماع: أي ترجمة تطابق الجملة المسموعة
    const si = Math.floor(Math.random() * stories.length);
    qs.push({
      kind: "استماع", prompt: "استمع إلى الجملة، ثم اختر ترجمتها الصحيحة.", listen: si,
      options: shuffle([stories[si].ar, ...(() => { const ans = stories[si].ar, same = pick(stories.map(s => s.ar), 3, ans);
        // درس بأقل من أربعة أخبار: تُكمَّل الخيارات بترجمات من دروس سابقة
        const others = Object.keys(lessons).filter(k => k !== activeKey).flatMap(k => lessons[k].stories.map(s => s.ar));
        return [...same, ...pick(others.filter(a => !same.includes(a)), 3 - same.length, ans)]; })()]), answer: stories[si].ar
    });
    // سؤال: أكمل الفراغ
    const blanks = [];
    stories.forEach(s => wordQ.slice(3).forEach(([en]) => {
      const re = new RegExp(`(^|[^A-Za-zÀ-ÿ'-])(${escapeRe(en)})(?=[^A-Za-zÀ-ÿ'-]|$)`, "i");
      if (re.test(s.en)) blanks.push({ s, en, re });
    }));
    if (blanks.length) {
      const b = blanks[Math.floor(Math.random() * blanks.length)];
      const shown = b.s.en.replace(b.re, (m, p) => `${p}_____`);
      qs.push({
        kind: "أكمل الجملة", prompt: `<span dir="ltr" class="quiz-sentence">${shown}</span>`,
        options: shuffle([b.en, ...pick(english.filter(e => e.toLowerCase() !== b.en.toLowerCase()), 3)]), answer: b.en, ltr: true
      });
    } else {
      const [en5, ar5] = wordQ[3];
      qs.push({ kind: "معنى الكلمة", prompt: `ما معنى كلمة <b dir="ltr">${en5}</b>؟`,
        options: shuffle([ar5, ...pick(meanings, 3, ar5)]), answer: ar5 });
    }
    const out = qs.slice(0, QUESTIONS);
    shuffle(exercises()).slice(0, 2).forEach(e => out.push({
      kind: "فهم الخبر", ltr: true,
      prompt: `<span dir="ltr" class="quiz-sentence">${e.question}</span><span class="quiz-q-ar">${e.question_ar}</span>`,
      options: shuffle(e.options), answer: e.options[e.answer]
    }));
    return out;
  }

  // ---------- واجهة الاختبار
  let state = null;
  function section() {
    let el = $("#dailyQuiz");
    if (!el) {
      el = document.createElement("section");
      el.id = "dailyQuiz";
      el.className = "quiz";
      $(".sentence-summary").after(el);
    }
    return el;
  }
  function renderIntro() {
    const best = store.get(bestKey(), null);
    const { doneToday } = streakInfo();
    section().innerHTML = `
      <div class="section-title"><p class="eyebrow">تمرين قصير</p><h2>اختبار اليوم</h2></div>
      <article class="quiz-card">
        <p class="quiz-lead">${exercises().length ? "سبعة أسئلة من أخبار هذا الدرس وكلماته: معنى، استماع، إكمال جملة، وفهم الخبر." : "خمسة أسئلة من أخبار هذا الدرس وكلماته: معنى، استماع، وإكمال جملة."}</p>
        ${best !== null ? `<p class="quiz-best">أفضل نتيجة لك في هذا الدرس: <b>${best}/${total()}</b></p>` : ""}
        <button type="button" class="quiz-start">${best !== null ? "↻ أعد الاختبار" : "ابدأ الاختبار"}</button>
        ${doneToday ? "" : `<p class="quiz-hint">🔥 أكمل اختبارًا اليوم لتحافظ على سلسلتك.</p>`}
      </article>`;
    section().querySelector(".quiz-start").onclick = start;
  }
  function start() {
    state = { qs: buildQuestions(), i: 0, score: 0 };
    renderQuestion();
  }
  function renderQuestion() {
    const q = state.qs[state.i];
    section().innerHTML = `
      <div class="section-title"><p class="eyebrow">اختبار اليوم · ${q.kind}</p><h2>السؤال ${state.i + 1} من ${state.qs.length}</h2></div>
      <article class="quiz-card">
        <div class="quiz-progress"><span style="width:${(state.i / state.qs.length) * 100}%"></span></div>
        <p class="quiz-prompt">${q.prompt}</p>
        ${q.listen !== undefined ? `<button type="button" class="quiz-listen">▶ استمع</button>` : ""}
        <div class="quiz-options">${q.options.map((o, k) => `<button type="button" class="quiz-option" data-k="${k}" ${q.ltr ? 'dir="ltr"' : ""}>${o}</button>`).join("")}</div>
        <p class="quiz-feedback" aria-live="polite"></p>
        <button type="button" class="quiz-next" hidden>${state.i + 1 < state.qs.length ? "السؤال التالي ←" : "النتيجة ←"}</button>
      </article>`;
    const card = section();
    if (q.listen !== undefined) {
      card.querySelector(".quiz-listen").onclick = () => playStory(q.listen, 1, 1);
      playStory(q.listen, 1, 1);
    }
    card.querySelectorAll(".quiz-option").forEach(b => b.onclick = () => answer(b));
    card.querySelector(".quiz-next").onclick = () => { stopPlayback(); state.i++; state.i < state.qs.length ? renderQuestion() : finish(); };
  }
  function answer(btn) {
    const q = state.qs[state.i];
    const chosen = q.options[+btn.dataset.k];
    const ok = chosen === q.answer;
    if (ok) state.score++;
    section().querySelectorAll(".quiz-option").forEach(b => {
      b.disabled = true;
      if (q.options[+b.dataset.k] === q.answer) b.classList.add("correct");
    });
    if (!ok) btn.classList.add("wrong");
    section().querySelector(".quiz-feedback").textContent = ok ? "✓ إجابة صحيحة!" : "✗ ليست هذه. الإجابة الصحيحة مظلّلة بالأخضر.";
    section().querySelector(".quiz-next").hidden = false;
  }
  function finish() {
    const key = bestKey();
    store.set(key, Math.max(state.score, store.get(key, 0)));
    markToday();
    renderStreak();
    const { n } = streakInfo();
    const msg = state.score === state.qs.length ? "ممتاز! علامة كاملة 🎉" : state.score >= 3 ? "أحسنت! استمر هكذا." : "بداية جيدة؛ راجع الكلمات ثم أعد المحاولة.";
    section().innerHTML = `
      <div class="section-title"><p class="eyebrow">اختبار اليوم</p><h2>النتيجة: ${state.score} من ${state.qs.length}</h2></div>
      <article class="quiz-card quiz-result">
        <p class="quiz-score">${msg}</p>
        <p class="quiz-streak">🔥 سلسلة أيامك المتتالية: <b>${n}</b></p>
        <button type="button" class="quiz-start">↻ أعد الاختبار</button>
      </article>`;
    section().querySelector(".quiz-start").onclick = start;
  }

  // عند فتح درس من الأرشيف يُبنى اختبار ذلك الدرس
  const originalLoadLesson = loadLesson;
  // الجمعة والسبت يوما مراجعة: يظهر اختبار الأسبوع بدل اختبار اليوم
  const reviewDay = [5, 6].includes(new Date().getDay());
  loadLesson = function (key) { originalLoadLesson(key); state = null; if (!reviewDay) renderIntro(); };
  // إكمال اختبار الأسبوع يُحسب في السلسلة 🔥 أيضًا
  window.addEventListener("almodhesh:quiz-done", () => { markToday(); renderStreak(); });

  renderStreak();
  if (!reviewDay) renderIntro();
})();
