// خدمة العمل دون اتصال لموقع المدهش.
// - الصفحة وملفات الدرس: الشبكة أولًا (حتى يظهر درس اليوم فور نشره)، ثم النسخة المحفوظة عند انقطاع الاتصال.
// - ملفات الصوت لا تُعترض (يتولاها المتصفح مباشرة).
const CACHE = "almodhesh-v8";
const SHELL = ["./", "index.html", "styles.css", "enhancements.css", "app.js", "lessons-data.js", "level.js", "level.css", "audio-only.js", "bilingual.js", "lessons-data-beginner.js", "lessons-data-intermediate.js", "lessons-data-advanced.js", "quiz.js", "quiz.css", "install.js", "weekly.js",
  "manifest.webmanifest", "icons/icon-192.png", "icons/icon-512.png"];

self.addEventListener("install", e => {
  e.waitUntil(caches.open(CACHE).then(c => c.addAll(SHELL)).then(() => self.skipWaiting()));
});

self.addEventListener("activate", e => {
  e.waitUntil(caches.keys()
    .then(keys => Promise.all(keys.filter(k => k !== CACHE).map(k => caches.delete(k))))
    .then(() => self.clients.claim()));
});

self.addEventListener("fetch", e => {
  const req = e.request;
  const url = new URL(req.url);
  if (req.method !== "GET" || url.origin !== location.origin || url.pathname.endsWith(".mp3")) return;
  e.respondWith(
    fetch(req, { cache: "no-cache" })
      .then(res => {
        if (res.ok) { const copy = res.clone(); caches.open(CACHE).then(c => c.put(req, copy)); }
        return res;
      })
      .catch(() => caches.match(req).then(r => r || caches.match("index.html")))
  );
});
