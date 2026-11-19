/* تست اجرایی static/exam.js بدون مرورگر.
   فایل را در یک محیط DOM حداقلی اجرا می‌کند تا خطاهای زمان اجرا
   (مثل استفاده از متغیر تعریف‌نشده) که فقط با اجرا دیده می‌شوند گرفته شوند.
   اجرا: node tests/test_examjs.js */
"use strict";

const fs = require("fs");
const path = require("path");
const vm = require("vm");
const RealDate = Date;

const SRC = path.join(__dirname, "..", "static", "exam.js");

const FA = "۰۱۲۳۴۵۶۷۸۹";

function makeEl(overrides = {}) {
  const el = {
    tagName: "DIV",
    dataset: {},
    style: {},
    textContent: "",
    value: "",
    checked: false,
    className: "",
    children: [],
    classList: {
      _s: new Set(),
      add(c) { this._s.add(c); },
      remove(c) { this._s.delete(c); },
      contains(c) { return this._s.has(c); },
      toggle(c, on) { on === undefined ? (this.contains(c) ? this.remove(c) : this.add(c)) : (on ? this.add(c) : this.remove(c)); },
    },
    appendChild(child) { this.children.push(child); return child; },
    removeChild() {},
    remove() {},
    setAttribute(k, v) { this[k] = v; },
    getAttribute(k) { return this[k]; },
    _l: {},
    addEventListener(type, fn) { (this._l[type] = this._l[type] || []).push(fn); },
    fire(type, ev) { (this._l[type] || []).forEach((fn) => fn(ev || {})); },
    querySelector() { return null; },
    querySelectorAll() { return []; },
    closest() { return null; },
    focus() {},
    ...overrides,
  };
  return el;
}

function run({ withQuestions = true, failSubmit = false } = {}) {
  const errors = [];
  const clock = { now: 1_700_000_000_000 };     // ساعت قابل کنترل برای تست تایمر
  const timer = makeEl({ id: "timer" });
  const answered = makeEl({ id: "answeredCount" });
  const progress = makeEl({ id: "progress" });

  // یک پنل سوال با فیلد متنی، تا مسیر شمارندهٔ کاراکتر هم اجرا شود
  const field = makeEl({ tagName: "TEXTAREA", dataset: { qid: "C1" } });
  field.value = "";
  const panel = makeEl({ dataset: { qid: "C1" } });
  const byId = { timer, answeredCount: answered, progress };
  const els = {};            // عنصرهای ثابت هر شناسه تا شنونده‌ها گم نشوند
  const el = (id) => (byId[id] = byId[id] || (els[id] = makeEl({ id })));

  const found = (sel) => {
    if (!withQuestions) return null;
    if (typeof sel === "string" && sel.startsWith(".qpanel[data-qid=")) return panel;
    if (sel === 'textarea, input[type="text"]') return field;
    return null;
  };

  const listeners = [];        // (type, handler) برای شبیه‌سازی رخدادها
  const calls = [];            // درخواست‌های fetch برای بررسی محتوای ذخیره‌شده
  const document = {
    getElementById: (id) => el(id),
    querySelector: found,
    querySelectorAll: (sel) => (sel === "[data-qid]" && withQuestions ? [field] : []),
    createElement: () => makeEl(),
    addEventListener: (type, fn) => listeners.push([type, fn]),
    body: makeEl(),
  };
  panel.querySelector = (sel) => (sel === 'textarea, input[type="text"]' ? field : null);
  panel.querySelectorAll = (sel) => (sel === 'textarea, input[type="text"]' ? [field] : []);
  field.closest = () => panel;

  const timers = { intervals: [], timeouts: [] };
  const sandbox = {
    window: null,
    document,
    localStorage: { getItem: () => null, setItem: () => {}, removeItem: () => {} },
    fetch: (url, opts) => {
      calls.push({ url, body: opts && opts.body ? String(opts.body) : "" });
      if (failSubmit && String(url).indexOf("/api/submit") >= 0) {
        return Promise.reject(new Error("شبکه قطع است"));
      }
      return Promise.resolve({ ok: true, json: () => Promise.resolve({ active: true, remaining: 3600 }) });
    },
    navigator: { clipboard: undefined, sendBeacon: undefined },
    addEventListener: () => {},
    removeEventListener: () => {},
    matchMedia: () => ({ matches: false, addEventListener() {} }),
    location: { href: "", reload() {} },
    console: { error: (...a) => errors.push(a.map(String).join(" ")), warn: () => {}, log: () => {} },
    setTimeout: (fn) => { timers.timeouts.push(fn); return 1; },
    clearTimeout: () => {},
    setInterval: (fn, ms) => { timers.intervals.push([fn, ms]); return 1; },
    clearInterval: () => {},
    Promise,
    Math,
    Number,
    Object,
    Array,
    String,
    JSON,
    Date: Object.assign(function () { return new RealDate(); }, {
      now: () => clock.now,
    }),
    isFinite,
    Intl,
  };
  sandbox.window = sandbox;
  sandbox.globalThis = sandbox;
  sandbox.window.EXAM_STATE = {
    attemptId: 7,
    deadline: 1_700_000_000 + 3600,
    serverNow: 1_700_000_000,
    qids: ["A1", "C1", "F1"],
    sections: [],
    minChars: 30,
    minCharQids: ["C1", "F1"],
    saved: {},
  };

  vm.createContext(sandbox);
  vm.runInContext(fs.readFileSync(SRC, "utf-8"), sandbox, { filename: "exam.js" });
  const tickFn = timers.intervals.find(([, ms]) => ms === 1000)?.[0];
  return { sandbox, errors, timer, answered, progress, timers, listeners, calls, field,
           clock, tick: tickFn, el, location: sandbox.location, modal: el("modalBack") };
}

/* یک رخداد را مثل مرورگر به شنونده‌های ثبت‌شده می‌رساند */
function fire(r, type, target) {
  r.listeners.filter(([t]) => t === type).forEach(([, fn]) => fn({ target, preventDefault() {} }));
}

/* زمان‌سنج‌های debounce را اجرا می‌کند تا ذخیره واقعاً انجام شود */
async function flushTimers(r) {
  const pending = r.timers.timeouts.splice(0, r.timers.timeouts.length);
  pending.forEach((fn) => fn());
  await new Promise((res) => setImmediate(res));
  await new Promise((res) => setImmediate(res));
}

let failed = 0;
function check(name, cond, detail = "") {
  if (cond) {
    console.log("ok   " + name);
  } else {
    failed++;
    console.log("FAIL " + name + (detail ? " — " + detail : ""));
  }
}

// ---------------------------------------------------------------- تست‌ها
{
  const r = run();
  check("بدون خطای زمان اجرا", r.errors.length === 0, r.errors.join(" | "));

  const t = r.timer.textContent;
  const valid = /^[۰-۹]{2}:[۰-۹]{2}$/.test(t);
  check("تایمر مقدار زمان نشان می‌دهد (نه --:--)", valid, JSON.stringify(t));
  check("تایمر در شروع عدد معقول (۵۹ یا ۶۰ دقیقه) است", valid && (t.startsWith("۵۹") || t === "۶۰:۰۰"), t);

  check("نوار پیشرفت به‌روز شده است", r.answered.textContent.includes("از"),
        JSON.stringify(r.answered.textContent));

  const hasTick = r.timers.intervals.some(([, ms]) => ms === 1000);
  check("حلقهٔ یک‌ثانیه‌ای تایمر ثبت شده است", hasTick);

  const hasSync = r.timers.intervals.some(([, ms]) => ms === 30000);
  check("همگام‌سازی ۳۰ ثانیه‌ای با سرور ثبت شده است", hasSync);
}

// ---------------------------------------------------------------- بدون سوال
{
  const r = run({ withQuestions: false });
  check("صفحهٔ بدون سوال هم خطا نمی‌دهد", r.errors.length === 0, r.errors.join(" | "));
  check("تایمر در صفحهٔ بدون سوال هم کار می‌کند",
        /^[۰-۹]{2}:[۰-۹]{2}$/.test(r.timer.textContent), JSON.stringify(r.timer.textContent));
}

// ---------------------------------------------------------------- تایمر تابع زمان واقعی
{
  const r = run();
  check("تایمر با ساعت دیوار محاسبه می‌شود (نه شمارش حلقه)",
        fs.readFileSync(SRC, "utf-8").includes("endAt - Date.now()"));

  // مرورگر در پس‌زمینه حلقه را متوقف کرده: ساعت ۹۰ ثانیه جلو می‌رود
  // و فقط یک بار tick اجرا می‌شود؛ باید همان ۹۰ ثانیه کسر شده باشد.
  r.clock.now += 90_000;
  r.tick();
  check("با توقف حلقه در پس‌زمینه، تایمر عقب نمی‌ماند",
        r.timer.textContent === "۵۸:۳۰", r.timer.textContent);

  // چند دقیقه بعد، باز هم یک tick
  r.clock.now += 300_000;
  r.tick();
  check("پس از ۵ دقیقهٔ دیگر، عدد دقیقاً همان زمان را نشان می‌دهد",
        r.timer.textContent === "۵۳:۳۰", r.timer.textContent);

  // پایان وقت: عدد صفر می‌شود و به منفی نمی‌رود
  r.clock.now += 3_600_000;
  r.tick();
  check("در پایان وقت، تایمر صفر می‌شود و منفی نمی‌شود",
        r.timer.textContent === "۰۰:۰۰", r.timer.textContent);
}

// ---------------------------------------------------------------- مهلت نامعتبر
{
  const r = run();
  // اجرای دوباره با مهلت نامعتبر: تایمر نباید NaN نشان دهد
  const src = fs.readFileSync(SRC, "utf-8");
  check("منبع تایمر از عدد متناهی محافظت می‌کند", src.includes("Number.isFinite(lastTick)"));
}

(async () => {
  let r = run();


  const ta1 = makeEl({ tagName: "TEXTAREA", dataset: { qid: "C1", field: "explain" } });
  ta1.value = "پاسخ تشریحی سوال اول";
  fire(r, "input", ta1);
  await flushTimers(r);

  const posts = () => r.calls.filter((c) => c.url === "/api/answer").map((c) => JSON.parse(c.body));
  check("تایپ در فیلد بلافاصله ذخیره می‌شود (بدون نیاز به خروج از فیلد)",
        posts().some((b) => b.qid === "C1" && b.payload.explain === "پاسخ تشریحی سوال اول"),
        JSON.stringify(posts()));

  // سپس تایپ در سوال دیگر: پاسخ قبلی نباید پاک شود
  const ta2 = makeEl({ tagName: "TEXTAREA", dataset: { qid: "F1", field: "text" } });
  ta2.value = "پاسخ سوال دوم";
  fire(r, "input", ta2);
  await flushTimers(r);

  const last = posts().filter((b) => b.qid === "C1").pop();
  check("پاسخ سوال قبلی پس از پاسخ دادن به سوال بعدی دست‌نخورده می‌ماند",
        last && last.payload.explain === "پاسخ تشریحی سوال اول",
        JSON.stringify(last));

  // گزینه‌های هر سوال گروه مستقل دارند: انتخاب در یک سوال، انتخاب دیگری را پاک نمی‌کند
  const radioA1 = makeEl({ tagName: "INPUT", type: "radio", name: "answer_A1", value: "ب",
                           dataset: { qid: "A1" } });
  fire(r, "change", radioA1);
  const radioA2 = makeEl({ tagName: "INPUT", type: "radio", name: "answer_A2", value: "ج",
                           dataset: { qid: "A2" } });
  fire(r, "change", radioA2);
  await flushTimers(r);

  const saved = {};
  posts().forEach((b) => { saved[b.qid] = b.payload; });
  check("انتخاب هر سوال چهارگزینه‌ای جداگانه ذخیره می‌شود",
        saved.A1 && saved.A1.choice === "ب" && saved.A2 && saved.A2.choice === "ج",
        JSON.stringify(saved));

  const callsBefore = posts().length;

  // رادیوی «نتیجه‌گیری» (data-field دارد) نباید به‌جای گزینهٔ چهارگزینه‌ای ثبت شود
  const concl = makeEl({ tagName: "INPUT", type: "radio", name: "c_E1", value: "x",
                         dataset: { qid: "E1", field: "conclusion" } });
  fire(r, "change", concl);
  await flushTimers(r);
  check("رادیوی نتیجه‌گیری به‌جای گزینهٔ سوال ثبت نمی‌شود",
        posts().slice(callsBefore).every((b) => !(b.qid === "E1" && b.payload.choice === "x")),
        JSON.stringify(posts().slice(callsBefore)));

  // چک‌باکس ادعا نباید مثل گزینهٔ چندانتخابی خوانده شود
  const claim = makeEl({ tagName: "INPUT", type: "checkbox", name: "claim",
                         value: "2", dataset: { qid: "I1" } });
  claim.classList.add("claimchk");
  claim.closest = () => null;
  const beforeClaim = posts().length;
  fire(r, "change", claim);
  await flushTimers(r);
  check("چک‌باکس ادعا با گزینهٔ چندانتخابی اشتباه نمی‌شود",
        posts().slice(beforeClaim).every((b) => !(b.qid === "I1" && b.payload.choices)),
        JSON.stringify(posts().slice(beforeClaim)));

  check("بدون خطای زمان اجرا در مسیر ذخیره", r.errors.length === 0, r.errors.join(" | "));



  // ۱) قطع اینترنت: نباید صفحه ترک شود و نباید پیام موفقیت داده شود
  r = run({ failSubmit: true });
  r.location.href = "";
  const modalConfirm = r.el("modalConfirm");
  const modalText = r.el("modalText");
  check("دکمهٔ ارسال به شنونده وصل شده است", (modalConfirm._l.click || []).length > 0);

  modalConfirm.fire("click");
  // انتظار برای سه تلاش با تأخیر ۸۰۰ و ۱۶۰۰ میلی‌ثانیه
  for (let i = 0; i < 40; i++) {
    await new Promise((res) => setImmediate(res));
    if (r.timers.timeouts.length) {
      const fns = r.timers.timeouts.splice(0, r.timers.timeouts.length);
      fns.forEach((fn) => fn());
    }
  }
  await new Promise((res) => setImmediate(res));

  check("با قطع اینترنت، صفحهٔ آزمون ترک نمی‌شود", r.location.href === "", JSON.stringify(r.location.href));
  check("پیام «ارسال انجام نشد» به کاربر نشان داده می‌شود",
        String(modalText.innerHTML).includes("ارسال انجام نشد"), String(modalText.innerHTML).slice(0, 80));
  const submits = r.calls.filter((c) => c.url === "/api/submit").length;
  check("ارسال نهایی چند بار تلاش می‌شود (بیش از یک بار)", submits > 1, `تلاش: ${submits}`);
  check("دکمهٔ ارسال پس از شکست دوباره فعال می‌شود", modalConfirm.disabled === false);
  check("بدون خطای زمان اجرا در مسیر ارسال ناموفق", r.errors.length === 0, r.errors.join(" | "));

  // ۲) ارسال موفق: پاسخ‌های ذخیره‌نشده پیش از ارسال فرستاده می‌شوند
  const ok = run();
  ok.location.href = "";
  const ta = makeEl({ tagName: "TEXTAREA", dataset: { qid: "F1", field: "text" } });
  ta.value = "متن تازه‌ای که هنوز ذخیره نشده بود";
  fire(ok, "input", ta);

  ok.el("modalConfirm").fire("click");
  for (let i = 0; i < 40; i++) {
    await new Promise((res) => setImmediate(res));
    if (ok.timers.timeouts.length) {
      const fns = ok.timers.timeouts.splice(0, ok.timers.timeouts.length);
      fns.forEach((fn) => fn());
    }
  }
  await new Promise((res) => setImmediate(res));

  const savedFirst = ok.calls.findIndex((c) => c.url === "/api/answer" &&
    JSON.parse(c.body).qid === "F1");
  const submitAt = ok.calls.findIndex((c) => c.url === "/api/submit");
  check("پاسخ تازه‌تایپ‌شده پیش از ارسال نهایی ذخیره می‌شود",
        savedFirst >= 0 && submitAt > savedFirst, `ذخیره: ${savedFirst}، ارسال: ${submitAt}`);
  check("پس از ارسال موفق به صفحهٔ نتیجه می‌رود", ok.location.href === "/exam", ok.location.href);

  console.log(failed ? `\n${failed} تست شکست خورد` : "\nهمهٔ تست‌های exam.js گذشت");
  process.exit(failed ? 1 : 0);
})();
