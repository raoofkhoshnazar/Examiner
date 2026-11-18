/* سامانهٔ آزمون واژه‌بان — منطق صفحهٔ آزمون */
(function () {
  "use strict";

  const S = window.EXAM_STATE;
  const FA = ["۰", "۱", "۲", "۳", "۴", "۵", "۶", "۷", "۸", "۹"];
  const fa = (n) => String(n).replace(/[0-9]/g, (d) => FA[+d]);

  const answers = {};
  const timers = {};
  let submitted = false;
  let lastTick = Math.round((S.deadline - S.serverNow));

  // ------------------------------- state bootstrap
  (S.saved || {}) && Object.keys(S.saved).forEach((qid) => { answers[qid] = S.saved[qid] || {}; });

  // پاسخ‌هایی که هنگام قطعی اتصال فقط در مرورگر ذخیره شده‌اند، برمی‌گردند
  let restoredDraft = false;
  function mergeDraft() {
    let draft = null;
    try { draft = JSON.parse(localStorage.getItem("vazheban_draft") || "null"); } catch (err) { draft = null; }
    if (!draft || typeof draft !== "object") return;
    const isEmpty = (v) => v == null || v === "" || (Array.isArray(v) && !v.length) ||
      (typeof v === "object" && !Array.isArray(v) && !Object.keys(v).length);
    Object.keys(draft).forEach((qid) => {
      if (!S.qids.includes(qid)) return;
      const local = draft[qid] || {};
      const server = answers[qid] || {};
      Object.keys(local).forEach((field) => {
        if (isEmpty(server[field]) && !isEmpty(local[field])) {
          answers[qid] = answers[qid] || {};
          answers[qid][field] = local[field];
          restoredDraft = true;
        }
      });
    });
  }
  mergeDraft();

  function setAnswer(qid, field, value) {
    answers[qid] = answers[qid] || {};
    answers[qid][field] = value;
    markAnswered(qid);
  }

  // ------------------------------- restore UI
  function restore() {
    document.querySelectorAll("[data-qid]").forEach((el) => {
      const qid = el.dataset.qid;
      const data = answers[qid];
      if (!data) return;
      if (el.tagName === "INPUT" && el.type === "radio") {
        if (el.name === "answer" && data.choice === el.value) el.checked = true;
        if (el.dataset.field === "conclusion" && data.conclusion === el.value) el.checked = true;
      } else if (el.tagName === "INPUT" && el.type === "checkbox") {
        if (el.name === "answer_multi") el.checked = (data.choices || []).includes(el.value);
        if (el.classList.contains("claimchk")) el.checked = (data.claims || []).includes(el.value);
      } else if (el.tagName === "SELECT" && el.dataset.pid) {
        const pid = el.dataset.pid;
        if (data.matches && data.matches[pid]) el.value = data.matches[pid];
      } else if (el.tagName === "TEXTAREA") {
        const f = el.dataset.field;
        if (data[f] != null) el.value = data[f];
      } else if (el.tagName === "INPUT" && el.type === "text") {
        const f = el.dataset.field;
        if (data[f] != null) el.value = data[f];
      }
    });
    // دکمه‌های درست/غلط
    document.querySelectorAll(".tfbox").forEach((box) => {
      const qid = box.dataset.qid;
      const d = answers[qid];
      if (d && d.tf != null) {
        box.querySelectorAll(".btn.tf").forEach((b) => {
          b.classList.toggle("selected", String(d.tf) === String(Number(b.dataset.val) === 1));
        });
      }
    });
    S.qids.forEach(markAnswered);
    updateProgress();
  }

  function markAnswered(qid) {
    const d = answers[qid] || {};
    const has = Object.keys(d).some((k) => {
      const v = d[k];
      if (v == null || v === "") return false;
      if (Array.isArray(v)) return v.length > 0;
      if (typeof v === "object") return Object.keys(v).length > 0;
      return true;
    });
    const nav = document.querySelector(`.qnav[data-target="${qid}"]`);
    if (nav) nav.classList.toggle("answered", has);
  }

  function updateProgress() {
    let done = 0;
    S.qids.forEach((qid) => {
      const d = answers[qid] || {};
      if (Object.keys(d).some((k) => {
        const v = d[k];
        if (v == null || v === "") return false;
        if (Array.isArray(v)) return v.length > 0;
        if (typeof v === "object") return Object.keys(v).length > 0;
        return true;
      })) done++;
    });
    document.getElementById("answeredCount").textContent = `${fa(done)} از ${fa(S.qids.length)}`;
    document.getElementById("progress").style.width = (done / S.qids.length * 100) + "%";
  }

  // ------------------------------- ممنوعیت کپی/پیست
  const MIN_CHARS = S.minChars || 50;

  function report(kind, detail) {
    if (submitted) return;
    try {
      fetch("/api/event", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ kind: kind, detail: detail || "" }),
      });
    } catch (err) { /* ثبت رخداد نباید آزمون را متوقف کند */ }
  }

  function isEditable(el) {
    return el && (el.tagName === "TEXTAREA" || (el.tagName === "INPUT" && el.type === "text"));
  }

  function blockedNotice(what) {
    flash(what + " در این آزمون غیرفعال است.");
  }

  function wireClipboard() {
    ["copy", "cut", "paste"].forEach((evt) => {
      document.addEventListener(evt, (ev) => {
        const el = ev.target;
        if (evt === "paste" || isEditable(el)) {
          ev.preventDefault();
          report(evt, el && el.dataset ? (el.dataset.qid || "") : "");
          blockedNotice(evt === "paste" ? "چسباندن متن" : "کپی متن");
          return;
        }
        // کپی متن کیس یا سوال هم ممنوع است
        ev.preventDefault();
        report(evt, "page");
        blockedNotice(evt === "paste" ? "چسباندن متن" : "کپی متن");
      }, true);
    });
    // کشیدن و رها کردن متن (drag & drop) هم مسیر دیگری برای چسباندن است
    ["drop", "dragover"].forEach((evt) => {
      document.addEventListener(evt, (ev) => {
        if (!isEditable(ev.target)) return;
        ev.preventDefault();
        if (evt === "drop") {
          report("paste", "drop");
          blockedNotice("چسباندن متن");
        }
      }, true);
    });
    // انتخاب و انتقال متن با ماوس هم غیرفعال می‌شود (پاسخ‌ها هنوز قابل تایپ‌اند)
    document.addEventListener("contextmenu", (ev) => {
      if (!isEditable(ev.target)) ev.preventDefault();
    });
  }

  // ------------------------------- شمارندهٔ کاراکتر
  function charCounter(el) {
    if (!el || !el.dataset || !el.dataset.qid) return null;
    const box = el.closest(".qpanel");
    if (!box) return null;
    let counter = box.querySelector(`.charcount[data-for="${el.dataset.qid}"]`);
    if (!counter) {
      counter = document.createElement("div");
      counter.className = "charcount";
      counter.dataset.for = el.dataset.qid;
      const head = box.querySelector(".qhead");
      if (head) head.appendChild(counter);
      else box.appendChild(counter);
    }
    return counter;
  }

  function textOfQuestion(qid) {
    const box = document.querySelector(`.qpanel[data-qid="${qid}"]`);
    if (!box) return "";
    return Array.from(box.querySelectorAll('textarea, input[type="text"]'))
      .map((el) => (el.value || "").trim()).filter(Boolean).join(" ");
  }

  const MIN_QIDS = S.minCharQids || [];

  function refreshCounter(qid) {
    if (MIN_QIDS.indexOf(qid) === -1) return;
    const box = document.querySelector(`.qpanel[data-qid="${qid}"]`);
    if (!box) return;
    const counter = charCounter(hasText);
    if (!counter) return;
    const len = textOfQuestion(qid).length;
    const ok = len >= MIN_CHARS;
    counter.textContent = `${fa(len)} / ${fa(MIN_CHARS)} کاراکتر`;
    counter.classList.toggle("ok", ok);
    counter.classList.toggle("short", !ok && len > 0);
  }

  function shortQuestions() {
    return MIN_QIDS.filter((qid) => {
      const box = document.querySelector(`.qpanel[data-qid="${qid}"]`);
      if (!box) return false;
      return textOfQuestion(qid).length < MIN_CHARS;
    });
  }

  // ------------------------------- saving
  async function save(qid) {
    if (submitted) return;
    try {
      const res = await fetch("/api/answer", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ qid, payload: answers[qid] || {} }),
      });
      if (res.ok) {
        const data = await res.json();
        if (typeof data.remaining === "number") lastTick = data.remaining;
      }
    } catch (err) { /* شبکه قطع شد؛ پاسخ در حافظه است و بعداً دوباره ذخیره می‌شود */ }
    updateProgress();
  }

  function debounce(fn, ms) {
    let h;
    return function (...args) {
      clearTimeout(h);
      const self = this;
      h = setTimeout(() => fn.apply(self, args), ms);
    };
  }
  const saveSoon = {};
  function queueSave(qid) {
    saveSoon[qid] = saveSoon[qid] || debounce(() => save(qid), 700);
    saveSoon[qid]();
  }

  // ------------------------------- event wiring
  function wire() {
    document.addEventListener("change", (ev) => {
      const el = ev.target;
      const qid = el.dataset ? el.dataset.qid : null;
      if (!qid) return;

      if (el.type === "radio" && el.name === "answer") {
        setAnswer(qid, "choice", el.value);
        save(qid);
      } else if (el.type === "checkbox" && el.name === "answer_multi") {
        const box = el.closest(".options");
        const vals = Array.from(box.querySelectorAll(`input[value]`)).filter((x) => x.checked).map((x) => x.value);
        setAnswer(qid, "choices", vals);
        save(qid);
      } else if (el.type === "radio" && el.dataset.field === "conclusion") {
        setAnswer(qid, "conclusion", el.value);
        save(qid);
      } else if (el.tagName === "SELECT" && el.dataset.pid) {
        answers[qid] = answers[qid] || {};
        answers[qid].matches = answers[qid].matches || {};
        if (el.value) answers[qid].matches[el.dataset.pid] = el.value;
        else delete answers[qid].matches[el.dataset.pid];
        setAnswer(qid, "matches", answers[qid].matches);
        save(qid);
      } else if (el.type === "checkbox" && el.classList.contains("claimchk")) {
        const vals = Array.from(document.querySelectorAll(`.claimchk[data-qid="${qid}"]`))
          .filter((x) => x.checked).map((x) => x.value);
        if (vals.length > 2) {
          el.checked = false;
          flash("فقط دو ادعا را می‌توانید انتخاب کنید.");
          return;
        }
        setAnswer(qid, "claims", vals);
        save(qid);
      } else if (el.tagName === "TEXTAREA") {
        setAnswer(qid, el.dataset.field, el.value);
        queueSave(qid);
      } else if (el.type === "text") {
        setAnswer(qid, el.dataset.field, el.value);
        queueSave(qid);
      }
    });

    // درست/غلط
    document.querySelectorAll(".tfbox").forEach((box) => {
      const qid = box.dataset.qid;
      box.querySelectorAll(".btn.tf").forEach((btn) => {
        btn.addEventListener("click", () => {
          const v = btn.dataset.val === "1";
          box.querySelectorAll(".btn.tf").forEach((b) => b.classList.remove("selected"));
          btn.classList.add("selected");
          setAnswer(qid, "tf", v);
          save(qid);
        });
      });
    });

    // ناوبری سوال‌ها
    document.querySelectorAll(".qnav").forEach((btn) => {
      btn.addEventListener("click", () => {
        const pan = document.getElementById("panel-" + btn.dataset.target);
        if (pan) pan.scrollIntoView({ behavior: "smooth", block: "start" });
        document.querySelectorAll(".qnav").forEach((b) => b.classList.remove("current"));
        btn.classList.add("current");
      });
    });

    document.getElementById("toggleCase").addEventListener("click", () => {
      document.querySelector(".case-pane").classList.toggle("closed");
    });

    // ارسال
    const modal = document.getElementById("modalBack");
    document.getElementById("submitBtn").addEventListener("click", () => {
      const tooShort = shortQuestions();
      if (tooShort.length) {
        document.getElementById("modalText").innerHTML =
          `<b>${fa(tooShort.length)} سوال کمتر از ${fa(MIN_CHARS)} کاراکتر دارند:</b> ` +
          tooShort.map((x) => `<span dir="ltr">${x}</span>`).join("، ") +
          `<br><br>تا وقتی هر پاسخ تشریحی به ${fa(MIN_CHARS)} کاراکتر نرسد، ارسال ممکن نیست.`;
        modal.classList.add("show");
        document.getElementById("modalConfirm").style.display = "none";
        return;
      }
      document.getElementById("modalConfirm").style.display = "";
      const empty = S.qids.filter((qid) => {
        const d = answers[qid] || {};
        return !Object.keys(d).some((k) => {
          const v = d[k];
          if (v == null || v === "") return false;
          if (Array.isArray(v)) return v.length > 0;
          if (typeof v === "object") return Object.keys(v).length > 0;
          return true;
        });
      });
      document.getElementById("modalText").innerHTML = empty.length
        ? `<b>${fa(empty.length)} سوال بی‌پاسخ دارید:</b> ${empty.map((x) => `<span dir="ltr">${x}</span>`).join("، ")}<br>نمرهٔ منفی ندارید؛ اگر پاسخ‌ها را نمی‌خواهید بررسی کنید، دوباره بزنید.
           <br><br>آیا مطمئنید که می‌خواهید آزمون را برای همیشه ارسال کنید؟`
        : "همهٔ سوال‌ها پاسخ دارند. پس از ارسال، امکان تغییر پاسخ‌ها وجود ندارد. آیا مطمئنید؟";
      modal.classList.add("show");
    });
    document.getElementById("modalCancel").addEventListener("click", () => modal.classList.remove("show"));
    document.getElementById("modalConfirm").addEventListener("click", async () => {
      try {
        const res = await fetch("/api/submit", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({}),
        });
        if (!res.ok) {
          const data = await res.json().catch(() => ({}));
          if (data.error === "short_answers") {
            modal.classList.remove("show");
            flash(`هر پاسخ تشریحی باید حداقل ${fa(MIN_CHARS)} کاراکتر باشد.`);
            return;
          }
        }
      } catch (err) { /* خطای شبکه؛ سرور با مهلت خودش ارسال می‌کند */ }
      submitted = true;
      try { localStorage.removeItem("vazheban_draft"); } catch (e) {}
      window.location.href = "/exam";
    });

    window.addEventListener("beforeunload", (ev) => {
      if (!submitted) { ev.preventDefault(); ev.returnValue = ""; }
    });

    // شمارندهٔ کاراکتر هنگام تایپ
    document.addEventListener("input", (ev) => {
      const el = ev.target;
      if (el && el.dataset && el.dataset.qid) refreshCounter(el.dataset.qid);
    });

    // ثبت خروج از صفحهٔ آزمون
    document.addEventListener("visibilitychange", () => {
      if (document.hidden && !submitted) report("blur", "hidden");
    });
    window.addEventListener("blur", () => { if (!submitted) report("blur", "window"); });

    // تلاش برای اسکرین‌شات (فقط در مرورگرهایی که پشتیبانی می‌کنند)
    if (navigator.mediaDevices && navigator.mediaDevices.getDisplayMedia) {
      const orig = navigator.mediaDevices.getDisplayMedia.bind(navigator.mediaDevices);
      navigator.mediaDevices.getDisplayMedia = function (...args) {
        report("screenshot", "getDisplayMedia");
        return Promise.reject(new Error("screen capture disabled"));
      };
      void orig;
    }
    document.addEventListener("keyup", (ev) => {
      const key = (ev.key || "").toLowerCase();
      const printScreen = key === "printscreen" || ev.code === "PrintScreen";
      const macShot = ev.metaKey && ev.shiftKey && ["3", "4", "5"].includes(key);
      if (printScreen || macShot) {
        report("screenshot", printScreen ? "printscreen" : "mac");
        flash("گرفتن تصویر از صفحه در این آزمون مجاز نیست.");
      }
    });

    // دوره‌ای: همهٔ پاسخ‌های محلی را بفرست
    setInterval(() => { if (!submitted) S.qids.forEach((qid) => save(qid)); }, 15000);
  }

  function flash(msg) {
    const div = document.createElement("div");
    div.className = "alert warn";
    div.style.cssText = "position:fixed;bottom:1rem;left:50%;transform:translateX(-50%);z-index:200";
    div.textContent = msg;
    document.body.appendChild(div);
    setTimeout(() => div.remove(), 2600);
  }

  // ------------------------------- timer (server-authoritative)
  function tick() {
    lastTick -= 1;
    const el = document.getElementById("timer");
    if (!el) return;
    const m = Math.max(0, Math.floor(lastTick / 60));
    const s = Math.max(0, lastTick % 60);
    el.textContent = `${fa(String(m).padStart(2, "0"))}:${fa(String(s).padStart(2, "0"))}`;
    el.classList.toggle("low", lastTick <= 300);
    if (lastTick === 900) flash("۱۵ دقیقه باقی مانده است.");
    if (lastTick === 300) flash("۵ دقیقه باقی مانده است.");
    if (lastTick <= 0 && !submitted) {
      submitted = true;
      timeOver();
    }
  }

  // پایان زمان: سرور خودش آزمون را می‌بندد و ذخیره می‌کند؛ ما فقط خبر می‌دهیم
  async function timeOver() {
    const box = document.getElementById("timeOver");
    if (box) box.classList.add("show");
    for (let i = 0; i < 15; i++) {
      try {
        const r = await fetch("/exam/time");
        if (r.ok) {
          const d = await r.json();
          if (!d.active) break;
        }
      } catch (err) { /* دوباره تلاش کن */ }
      await new Promise((res) => setTimeout(res, 1000));
    }
    window.location.href = "/exam";
  }

  // همگام‌سازی زمان با سرور هر ۳۰ ثانیه
  async function syncTime() {
    try {
      const r = await fetch("/exam/time");
      if (r.ok) {
        const d = await r.json();
        if (d.active && typeof d.remaining === "number") {
          lastTick = d.remaining;
          if (lastTick <= 0 && !submitted) { submitted = true; timeOver(); }
        } else if (!d.active && !submitted) window.location.href = "/exam";
      }
    } catch (err) { /* از زمان محلی استفاده کن */ }
  }

  // ذخیرهٔ موقت در مرورگر برای قطعی اتصال
  document.addEventListener("input", debounce(() => {
    try { localStorage.setItem("vazheban_draft", JSON.stringify(answers)); } catch (e) {}
  }, 1000));

  wireClipboard();
  restore();
  wire();
  MIN_QIDS.forEach(refreshCounter);
  if (restoredDraft) {
    flash("پاسخ‌های ذخیره‌نشدهٔ قبلی بازیابی شد و دوباره ذخیره می‌شود.");
    setTimeout(() => { S.qids.forEach((qid) => save(qid)); }, 1200);
  }
  tick();
  setInterval(tick, 1000);
  setInterval(syncTime, 30000);
})();
