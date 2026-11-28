// اختبارات الواجهة بلا متصفح: تشغّل update.js و weekly.js في بيئة محاكاة وتتحقق من السلوك. تُنفَّذ من test_frontend.py.
const fs = require("fs");
const vm = require("vm");
const path = require("path");
const SITE = path.join(__dirname, "..", "site");
const results = [];
const check = (name, ok, detail) => results.push({ name, ok: !!ok, detail: ok ? "" : String(detail || "") });

function el() {
  const e = { children: [], className: "", id: "", innerHTML: "", hidden: false, onclick: null, dataset: {},
    setAttribute() {}, append(c) { this.children.push(c); }, after(c) { env.afterCalls.push(c); }, remove() { env.removed++; },
    querySelector(sel) { return e["_q" + sel] || (e["_q" + sel] = el()); }, querySelectorAll() { return []; },
    classList: { contains: () => false, add() {}, remove() {} } };
  return e;
}

function makeEnv(opts = {}) {
  const listeners = {};
  const env = { reloads: 0, fetches: [], afterCalls: [], removed: 0, intervals: [], session: {}, local: {}, localReads: [],
    banners: 0 };
  const hero = el();
  hero.after = c => { env.afterCalls.push(c); env.banners++; };
  const doc = {
    hidden: !!opts.hidden,
    getElementById: id => (id === "updateBanner" ? (env.afterCalls.at(-1) && env.removed === 0 ? env.afterCalls.at(-1) : null) : (id === "weekly" ? el() : null)),
    createElement: () => el(),
    querySelector: sel => {
      if (sel === "#today .hero") return hero;
      if (sel === ".nav.active") return { dataset: { view: "today" } };
      if (sel === ".quiz-card .quiz-progress") return opts.quiz ? {} : null;
      if (sel === "#playAll20.playing") return null;
      return null;
    },
    addEventListener: (ev, fn) => { (listeners["doc:" + ev] ||= []).push(fn); },
  };
  const win = {
    addEventListener: (ev, fn) => { (listeners["win:" + ev] ||= []).push(fn); },
  };
  const ctx = {
    document: doc, window: win, navigator: { onLine: opts.online !== false },
    location: { reload() { env.reloads++; } },
    sessionStorage: { getItem: k => env.session[k] ?? null, setItem: (k, v) => { env.session[k] = String(v); } },
    localStorage: { getItem: k => { env.localReads.push(k); return env.local[k] ?? null; }, setItem: (k, v) => { env.local[k] = String(v); } },
    setInterval: (fn, ms) => { env.intervals.push({ fn, ms }); return 1; },
    setTimeout, clearTimeout, console, Date: opts.Date || Date, JSON, Promise, String, Math, Object, Array, Set, RegExp, Event: class {},
    fetch: async url => { env.fetches.push(url); if (opts.delay) await new Promise(r => setTimeout(r, opts.delay)); if (opts.fail) throw new Error("offline");
      return { ok: opts.status === undefined, json: async () => ({ lesson: opts.latest || "2026-11-26" }) }; },
    addEventListener: (ev, fn) => { (listeners["win:" + ev] ||= []).push(fn); },
    lessonDate: "2026-11-26",
  };
  ctx.activeHumanAudio = opts.audio ? { paused: false } : null;
  vm.createContext(ctx);
  env.ctx = ctx; env.listeners = listeners;
  env.fire = (name, ...a) => (listeners[name] || []).forEach(f => f(...a));
  env.run = file => vm.runInContext(fs.readFileSync(path.join(SITE, file), "utf8") + "\n;globalThis.__lessonDate = lessonDate;", ctx, { filename: file });
  return env;
}
const tick = () => new Promise(r => setTimeout(r, 10));
const origEnv = makeEnv;
global.env = null;

(async () => {
  // 1) لا درس أحدث: لا شريط ولا إعادة تحميل
  let e = global.env = makeEnv({ latest: "2026-11-26" });
  vm.runInContext("var lessonDate='2026-11-26'", e.ctx); e.run("update.js");
  e.intervals[0].fn(); await tick();
  check("interval is 5 minutes", e.intervals[0].ms === 300000, e.intervals[0].ms);
  check("no newer lesson: no banner and no reload", e.banners === 0 && e.reloads === 0, JSON.stringify({ b: e.banners, r: e.reloads }));
  check("polls only latest.json (no external host, no API)", e.fetches.length === 1 && /^latest\.json\?u=\d+$/.test(e.fetches[0]), e.fetches);

  // 2) درس أحدث أثناء الاستخدام: شريط فقط (لا إعادة تحميل)
  e = global.env = makeEnv({ latest: "2026-11-28" }); vm.runInContext("var lessonDate='2026-11-26'", e.ctx); e.run("update.js");
  e.intervals[0].fn(); await tick();
  check("newer lesson while in use: banner, no reload", e.banners === 1 && e.reloads === 0, JSON.stringify({ b: e.banners, r: e.reloads }));
  e.intervals[0].fn(); await tick();
  check("banner is not duplicated", e.banners >= 1, e.banners);

  // 3) عودة إلى المقدمة بلا لمس وبلا صوت/اختبار: تحديث تلقائي مرة واحدة مع حفظ التبويب
  e = global.env = makeEnv({ latest: "2026-11-28" }); vm.runInContext("var lessonDate='2026-11-26'", e.ctx); e.run("update.js");
  e.ctx.document.hidden = false; e.fire("doc:visibilitychange"); await tick();
  check("foreground + idle + nothing playing: auto-update once", e.reloads === 1 && e.session["almodhesh-view"] === "today", JSON.stringify({ r: e.reloads, s: e.session }));
  e.fire("doc:visibilitychange"); await tick();
  check("same lesson is never auto-reloaded twice (no loop)", e.reloads === 1 && e.banners === 1, JSON.stringify({ r: e.reloads, b: e.banners }));

  // 4) صوت قيد التشغيل: لا تحديث تلقائي
  e = global.env = makeEnv({ latest: "2026-11-28", audio: true }); vm.runInContext("var lessonDate='2026-11-26'", e.ctx); e.run("update.js");
  e.fire("doc:visibilitychange"); await tick();
  check("audio playing: never reloads", e.reloads === 0 && e.banners === 1, JSON.stringify({ r: e.reloads, b: e.banners }));

  // 5) اختبار مفتوح: لا تحديث تلقائي
  e = global.env = makeEnv({ latest: "2026-11-28", quiz: true }); vm.runInContext("var lessonDate='2026-11-26'", e.ctx); e.run("update.js");
  e.fire("doc:visibilitychange"); await tick();
  check("quiz in progress: never reloads", e.reloads === 0 && e.banners === 1, JSON.stringify({ r: e.reloads, b: e.banners }));

  // 6) لمس بعد العودة: شريط لا إعادة تحميل
  e = global.env = makeEnv({ latest: "2026-11-28", delay: 40 }); vm.runInContext("var lessonDate='2026-11-26'", e.ctx); e.run("update.js");
  e.fire("doc:visibilitychange");
  await new Promise(r => setTimeout(r, 10));
  e.fire("win:pointerdown");  // المتعلم لمس الشاشة بينما الفحص جارٍ
  await new Promise(r => setTimeout(r, 80));
  check("touch after returning: banner instead of reload", e.reloads === 0 && e.banners === 1, JSON.stringify({ r: e.reloads, b: e.banners }));

  // 7) التطبيق مخفي أو بلا اتصال أو فشل الطلب: لا طلب/لا خطأ
  e = global.env = makeEnv({ hidden: true, latest: "2026-11-28" }); vm.runInContext("var lessonDate='2026-11-26'", e.ctx); e.run("update.js");
  e.intervals[0].fn(); await tick();
  check("hidden app does not fetch", e.fetches.length === 0, e.fetches);
  e = global.env = makeEnv({ fail: true }); vm.runInContext("var lessonDate='2026-11-26'", e.ctx); e.run("update.js");
  e.intervals[0].fn(); await tick();
  check("offline/fetch error is silent", e.banners === 0 && e.reloads === 0, JSON.stringify({ b: e.banners, r: e.reloads }));
  e = global.env = makeEnv({ online: false, latest: "2026-11-28" }); vm.runInContext("var lessonDate='2026-11-26'", e.ctx); e.run("update.js");
  e.intervals[0].fn(); await tick();
  check("offline does not fetch", e.fetches.length === 0, e.fetches);
  e = global.env = makeEnv({ status: 404 }); vm.runInContext("var lessonDate='2026-11-26'", e.ctx); e.run("update.js");
  e.intervals[0].fn(); await tick();
  check("missing latest.json is ignored", e.banners === 0 && e.reloads === 0, JSON.stringify({ b: e.banners, r: e.reloads }));

  // 8) المراجعة الأسبوعية: نتيجة كل مستوى مستقلة
  const Friday = class extends Date { constructor(...a) { super(...(a.length ? a : ["2026-11-27T12:00:00"])); } };
  const keysUsed = {};
  for (const level of ["beginner", "intermediate", "advanced"]) {
    const w = makeEnv({ Date: Friday });
    vm.runInContext(`var lessonDate='2026-11-26'; var lessons={'2026-11-26':{words:[['a','b']],stories:[{en:'x',ar:'y'}]}}; var lessonAudio={}; window.almodheshLevel='${level}'; function utter(){}; function stopPlayback(){}; var activeHumanAudio=null;`, w.ctx);
    w.ctx.window.almodheshLevel = level;
    try { w.run("weekly.js"); } catch (err) { check("weekly.js runs for " + level, false, err.message); continue; }
    keysUsed[level] = w.localReads.find(k => k.startsWith("quiz-week-best-"));
  }
  check("weekly best score key differs per level",
    keysUsed.beginner && keysUsed.beginner !== keysUsed.intermediate && keysUsed.intermediate !== keysUsed.advanced &&
    keysUsed.advanced.endsWith("-advanced"), JSON.stringify(keysUsed));

  console.log(JSON.stringify(results));
})();
