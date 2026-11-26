// «استمع 5 مرات – إنجليزي وعربي»: الخبر بالإنجليزية ثم ترجمته العربية، لكل أخبار الدرس، والتسلسل كاملًا 5 مرات.
// - تسجيلات ElevenLabs فقط (لا صوت متصفح)، وكل ملف يُعاد تشغيله في كل تكرار دون تسجيل جديد.
// - عنصر صوت واحد طوال التسلسل + أزرار التحكم في شاشة القفل (Media Session) ليستمر الاستماع في الخلفية حيث يسمح الجهاز.
// يعتمد على متغيرات app.js العامة: activeKey, activeStories, lessonAudio, stopPlayback, activeHumanAudio, playlistRun.
(function () {
  const ROUNDS = 5;
  const all20 = document.getElementById("playAll20");
  if (!all20) return;
  const button = document.createElement("button");
  button.id = "playBilingual5";
  button.type = "button";
  button.className = "play-all-20";
  button.textContent = "🔊 استمع 5 مرات – إنجليزي وعربي";
  all20.after(button);

  const player = new Audio();
  player.preload = "auto";
  let playing = false, run = 0, queue = [], pos = 0;

  function notice(text) {
    let el = document.getElementById("audioNotice");
    if (!el) {
      el = document.createElement("div");
      el.id = "audioNotice";
      el.className = "audio-notice";
      el.setAttribute("role", "status");
      document.body.append(el);
    }
    el.textContent = text;
    el.hidden = false;
    clearTimeout(notice.t);
    notice.t = setTimeout(() => { el.hidden = true; }, 3000);
  }

  function reset() {
    playing = false;
    button.classList.remove("playing");
    if ("mediaSession" in navigator) navigator.mediaSession.playbackState = "none";
  }

  // أي إيقاف من أزرار التطبيق (استمع، بطيء، ×20 ...) يوقف هذا التسلسل أيضًا
  const appStop = stopPlayback;
  stopPlayback = function () { appStop(); if (playing) { player.pause(); reset(); } };

  function setMedia(item) {
    if (!("mediaSession" in navigator) || typeof MediaMetadata === "undefined") return;
    navigator.mediaSession.metadata = new MediaMetadata({
      title: `${item.topic} · ${item.lang === "ar" ? "العربية" : "English"}`,
      artist: "المدهش – Almodhesh",
      album: `استماع ثنائي اللغة · ${item.round}/${ROUNDS}`,
      artwork: [{ src: "icons/icon-512.png", sizes: "512x512", type: "image/png" }]
    });
    navigator.mediaSession.playbackState = "playing";
  }

  function playNext(myRun) {
    if (myRun !== run || !playing) return;
    if (pos >= queue.length) { reset(); activeHumanAudio = null; return; }
    const item = queue[pos++];
    activeHumanAudio = player;          // زر «توقيف مؤقت» الموجود يعمل على هذا الصوت
    player.src = item.url;
    player.playbackRate = 1;
    setMedia(item);
    player.play().catch(() => { reset(); notice("تعذّر تشغيل الصوت. اضغط الزر مرة أخرى."); });
  }
  player.addEventListener("ended", () => playNext(run));
  player.addEventListener("error", () => playNext(run)); // ملف ناقص: يُتجاوز دون صوت بديل

  if ("mediaSession" in navigator) {
    const ms = navigator.mediaSession;
    try {
      ms.setActionHandler("play", () => { if (playing) { player.play(); ms.playbackState = "playing"; } });
      ms.setActionHandler("pause", () => { player.pause(); ms.playbackState = "paused"; });
      ms.setActionHandler("stop", () => stopPlayback());
    } catch {}
  }

  button.onclick = () => {
    if (playing) { stopPlayback(); return; }
    const arabic = (typeof lessonArabicAudio !== "undefined" && lessonArabicAudio[activeKey]) || [];
    const english = lessonAudio[activeKey] || [];
    if (!arabic.some(Boolean)) { notice("الاستماع بالإنجليزية والعربية متاح في الدروس الجديدة."); return; }
    stopPlayback();
    queue = [];
    for (let r = 1; r <= ROUNDS; r++) {
      activeStories.forEach((s, i) => {
        if (english[i]) queue.push({ url: english[i], lang: "en", topic: s.topic, round: r });
        if (arabic[i]) queue.push({ url: arabic[i], lang: "ar", topic: s.topic, round: r });
      });
    }
    pos = 0;
    run++;
    playing = true;
    button.classList.add("playing");
    playNext(run);
  };
})();
