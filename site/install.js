// زر "ثبّت المدهش": يظهر فقط حين يمكن تثبيت الموقع كتطبيق، ويختفي بعد التثبيت أو الإغلاق.
(function () {
  const HIDE_KEY = "install-dismissed-until";
  const store = {
    get(k) { try { return localStorage.getItem(k); } catch { return null; } },
    set(k, v) { try { localStorage.setItem(k, v); } catch {} }
  };
  const installed = () =>
    window.matchMedia("(display-mode: standalone)").matches || window.navigator.standalone === true;
  const dismissed = () => Date.now() < Number(store.get(HIDE_KEY) || 0);
  const isIOS = /iphone|ipad|ipod/i.test(navigator.userAgent) ||
    (navigator.platform === "MacIntel" && navigator.maxTouchPoints > 1);

  let deferred = null;

  function banner(html, onInstall) {
    if (installed() || dismissed() || document.getElementById("installBanner")) return;
    const el = document.createElement("aside");
    el.id = "installBanner";
    el.className = "install-banner";
    el.innerHTML = `
      <img src="icons/icon-192.png" alt="" width="44" height="44">
      <div class="install-text">${html}</div>
      ${onInstall ? '<button type="button" class="install-go">📲 ثبّت المدهش</button>' : ""}
      <button type="button" class="install-close" aria-label="إغلاق">×</button>`;
    document.querySelector("#today .hero").after(el);
    if (onInstall) el.querySelector(".install-go").onclick = onInstall;
    el.querySelector(".install-close").onclick = () => {
      store.set(HIDE_KEY, String(Date.now() + 14 * 24 * 3600 * 1000));
      el.remove();
    };
  }
  const hide = () => document.getElementById("installBanner")?.remove();

  // Chrome و Edge (ويندوز، أندرويد، ماك): نافذة التثبيت الرسمية
  window.addEventListener("beforeinstallprompt", e => {
    e.preventDefault();
    deferred = e;
    banner("<strong>المدهش كتطبيق على جهازك</strong><span>أيقونة على سطح المكتب، ودرس جديد كل صباح.</span>", async () => {
      if (!deferred) return;
      deferred.prompt();
      const choice = await deferred.userChoice.catch(() => null);
      deferred = null;
      if (choice && choice.outcome === "accepted") hide();
    });
  });
  window.addEventListener("appinstalled", hide);

  // آيفون وآيباد: لا توجد نافذة تثبيت، فنعرض الطريقة
  if (isIOS) {
    banner("<strong>أضف المدهش إلى شاشتك الرئيسية</strong><span>في Safari اضغط زر المشاركة (مربع بسهم للأعلى) ثم «إضافة إلى الشاشة الرئيسية».</span>", null);
  }
})();
