// تنبيه بدرس جديد: يفحص ملف latest.json الصغير كل 5 دقائق أثناء فتح التطبيق وعند العودة إليه أو عودة الاتصال.
// لا يستدعي أي خدمة مدفوعة (طلب ثابت إلى الموقع نفسه)، ولا يقاطع صوتًا ولا قراءة ولا اختبارًا ولا تقدّم التعلّم:
// - أثناء الاستخدام يظهر شريط صغير بزر «حدّث الآن» بالأنماط الموجودة، ولا يُعاد تحميل الصفحة تلقائيًا.
// - التحديث التلقائي يحدث فقط عند العودة من الخلفية إن لم يلمس المتعلم شيئًا بعد عودته ولا يوجد صوت أو اختبار قيد التشغيل.
// تقدّم التعلّم (المسموع، المحفوظ، الكلمات المضافة، نتائج الاختبارات) محفوظ في المتصفح ويبقى بعد التحديث،
// ويعود المتعلم إلى التبويب نفسه. ويبقى آخر درس محمَّل صالحًا للقراءة دون اتصال بفضل عامل الخدمة.
(function () {
  const INTERVAL = 5 * 60 * 1000;
  const store = {
    get(k) { try { return sessionStorage.getItem(k); } catch { return null; } },
    set(k, v) { try { sessionStorage.setItem(k, v); } catch {} }
  };
  let checking = false;
  let lastTouch = Date.now();
  let returnedAt = 0;
  ["pointerdown", "keydown", "touchstart", "scroll"].forEach(ev =>
    addEventListener(ev, () => { lastTouch = Date.now(); }, { passive: true, capture: true }));

  const quizOpen = () => !!document.querySelector(".quiz-card .quiz-progress");
  const audioOpen = () => (typeof activeHumanAudio !== "undefined" && !!activeHumanAudio) ||
    !!document.querySelector("#playAll20.playing");
  const busy = () => quizOpen() || audioOpen();

  function reload(date) {
    store.set("update-reloaded", date);
    const nav = document.querySelector(".nav.active");
    if (nav) store.set("almodhesh-view", nav.dataset.view); // level.js يعيد المتعلم إلى التبويب نفسه
    location.reload();
  }

  function banner(date) {
    if (document.getElementById("updateBanner") || store.get("update-dismissed") === date) return;
    const el = document.createElement("aside");
    el.id = "updateBanner";
    el.className = "install-banner";
    el.setAttribute("role", "status");
    el.innerHTML = `
      <img src="icons/icon-192.png" alt="" width="44" height="44">
      <div class="install-text"><strong>يوجد درس جديد</strong><span>اضغط «حدّث الآن» حين تنتهي من الاستماع أو القراءة أو الاختبار.</span></div>
      <button type="button" class="install-go">↻ حدّث الآن</button>
      <button type="button" class="install-close" aria-label="إغلاق">×</button>`;
    const hero = document.querySelector("#today .hero");
    if (!hero) return;
    hero.after(el);
    el.querySelector(".install-go").onclick = () => reload(date);
    el.querySelector(".install-close").onclick = () => { store.set("update-dismissed", date); el.remove(); };
  }

  async function check(fromForeground) {
    if (checking || document.hidden || navigator.onLine === false) return;
    checking = true;
    try {
      const res = await fetch("latest.json?u=" + Date.now(), { cache: "no-store" });
      if (!res.ok) return;
      const date = String((await res.json()).lesson || "");
      if (!/^\d{4}-\d{2}-\d{2}$/.test(date) || date <= lessonDate) return;
      const idleSinceReturn = fromForeground && returnedAt && lastTouch <= returnedAt;
      if (idleSinceReturn && !busy() && store.get("update-reloaded") !== date) reload(date);
      else banner(date);
    } catch { /* بلا اتصال: يبقى الدرس المحمَّل */ }
    finally { checking = false; }
  }

  setInterval(() => check(false), INTERVAL);
  document.addEventListener("visibilitychange", () => {
    if (!document.hidden) { returnedAt = Date.now(); check(true); }
  });
  addEventListener("online", () => check(false));
})();
