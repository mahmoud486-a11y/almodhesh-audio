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
    const stat = [...document.querySelectorAll(".stats span")].find(s => s.textContent.includes("المستوى"));
    if (stat) stat.textContent = "المستوى " + LEVELS[level].cefr;

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

    // العودة إلى التبويب نفسه بعد تغيير المستوى
    const back = get(sessionStorage, "almodhesh-view");
    if (back) {
      try { sessionStorage.removeItem("almodhesh-view"); } catch {}
      const nav = document.querySelector(`.nav[data-view="${back}"]`);
      if (nav && !nav.classList.contains("active")) nav.click();
    }
  });
})();
