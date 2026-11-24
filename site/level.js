// مستوى اللغة: يحمّل بيانات المستوى المحفوظ قبل app.js، ويضيف أزرار المستويات الثلاثة.
// المحتوى مُولَّد مسبقًا ومحفوظ في الموقع؛ تغيير المستوى لا يستدعي أي خدمة ولا يكلّف شيئًا.
(function () {
  const LEVELS = {
    beginner: { ar: "مبتدئ", en: "Beginner", cefr: "A1–A2" },
    intermediate: { ar: "متوسط", en: "Intermediate", cefr: "B1–B2" },
    advanced: { ar: "متقدم", en: "Advanced", cefr: "C1–C2" }
  };
  const get = (s, k) => { try { return s.getItem(k); } catch { return null; } };
  const set = (s, k, v) => { try { s.setItem(k, v); } catch {} };
  let level = get(localStorage, "almodhesh-level");
  if (!LEVELS[level]) level = "intermediate";
  window.almodheshLevel = level;
  // تحميل متزامن لبيانات المستوى حتى تكون جاهزة قبل app.js
  document.write('<script src="lessons-data-' + level + '.js"><\/script>');

  document.addEventListener("DOMContentLoaded", () => {
    const bar = document.createElement("div");
    bar.className = "level-switch";
    bar.setAttribute("role", "group");
    bar.setAttribute("aria-label", "مستوى اللغة");
    bar.innerHTML = Object.entries(LEVELS).map(([k, v]) =>
      `<button type="button" class="level-btn" data-level="${k}" aria-pressed="${k === level}">${v.ar}<small>${v.en} · ${v.cefr}</small></button>`
    ).join("");
    document.querySelector("main").prepend(bar);
    bar.querySelectorAll(".level-btn").forEach(b => b.onclick = () => {
      if (b.dataset.level === level) return;
      set(localStorage, "almodhesh-level", b.dataset.level);
      const view = document.querySelector(".nav.active");
      if (view) set(sessionStorage, "almodhesh-view", view.dataset.view);
      location.reload();
    });

    // دروس الأخبار الأربعة: تعديل الرقم في النصوص الموجودة فقط (ستة ← أربعة)، ومطابقة أزرار أرقام الأخبار
    const NUM = { 3: ["ثلاثة", "الثلاثة"], 4: ["أربعة", "الأربعة"], 5: ["خمسة", "الخمسة"], 6: ["ستة", "الستة"] };
    const targets = [
      [document.querySelector("#today .hero > p:not(.eyebrow)"), "count"],
      [document.querySelector("#heard")?.parentElement, "slash"],
      [document.querySelector(".sentence-summary h2"), "def"],
      [document.getElementById("playAll20"), "def"]
    ].filter(([el]) => el).map(([el, kind]) => ({ el, kind, html: el.innerHTML }));
    function adapt() {
      const n = activeStories.length;
      targets.forEach(t => {
        if (n === 6 || !NUM[n]) { t.el.innerHTML = t.html; return; }
        t.el.innerHTML = t.kind === "slash" ? t.html.replace("/6", "/" + n)
          : t.kind === "count" ? t.html.replace("ستة أخبار", NUM[n][0] + " أخبار") : t.html.replace("الستة", NUM[n][1]);
      });
      const box = document.getElementById("numbers");
      if (box && box.children.length !== n) {
        box.replaceChildren();
        activeStories.forEach((_, i) => {
          const b = document.createElement("button");
          b.textContent = i + 1;
          b.setAttribute("aria-label", `الخبر ${i + 1}`);
          b.onclick = () => { stopPlayback(); current = i; render(); };
          box.append(b);
        });
        render();
      }
      const heard = document.getElementById("heard");
      if (heard) heard.textContent = Math.min(+heard.textContent || 0, n); // عدّاد الجمل لا يتجاوز عدد الأخبار
    }
    const loadPrevious = loadLesson;
    loadLesson = function (key) { loadPrevious(key); adapt(); };
    adapt();

    // العودة إلى التبويب نفسه بعد تغيير المستوى
    const back = get(sessionStorage, "almodhesh-view");
    if (back) {
      try { sessionStorage.removeItem("almodhesh-view"); } catch {}
      const nav = document.querySelector(`.nav[data-view="${back}"]`);
      if (nav && !nav.classList.contains("active")) nav.click();
    }
  });
})();
