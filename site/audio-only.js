// صوت ElevenLabs فقط: يمنع صوت المتصفح/الجهاز نهائيًا.
// أي محاولة من التطبيق لاستخدام صوت المتصفح تُحوَّل إلى تسجيل ElevenLabs المطابق للنص (بالسرعة والتكرار نفسيهما)،
// وإن لم يوجد تسجيل لا يُشغَّل أي صوت بديل، وتظهر رسالة قصيرة.
// يعتمد على متغيرات app.js العامة: lessons, lessonAudio, lessonWordAudio, activeHumanAudio.
(function () {
  if (!("speechSynthesis" in window)) return;
  const norm = t => (t || "").trim().toLowerCase();
  const recordings = new Map();
  Object.keys(lessons).forEach(key => {
    (lessons[key].stories || []).forEach((s, i) => { const u = lessonAudio[key]?.[i]; if (u && !recordings.has(norm(s.en))) recordings.set(norm(s.en), u); });
    (lessons[key].words || []).forEach((w, i) => { const u = lessonWordAudio[key]?.[i]; if (u && !recordings.has(norm(w[0]))) recordings.set(norm(w[0]), u); });
  });

  let timer = null;
  function notice() {
    let el = document.getElementById("audioNotice");
    if (!el) {
      el = document.createElement("div");
      el.id = "audioNotice";
      el.className = "audio-notice";
      el.setAttribute("role", "status");
      document.body.append(el);
    }
    el.textContent = "تسجيل هذا النص غير متوفر حاليًا.";
    el.hidden = false;
    clearTimeout(timer);
    timer = setTimeout(() => { el.hidden = true; }, 2600);
  }

  speechSynthesis.speak = function (u) {
    const url = recordings.get(norm(u && u.text));
    if (!url) { notice(); return; }
    const audio = new Audio(url);
    activeHumanAudio = audio;
    audio.playbackRate = (u && u.rate) || 1;
    audio.preservesPitch = true;
    audio.onended = () => { if (activeHumanAudio === audio) activeHumanAudio = null; if (u && u.onend) u.onend(); };
    audio.onerror = () => { if (activeHumanAudio === audio) activeHumanAudio = null; notice(); };
    audio.play().catch(() => notice());
  };
})();
