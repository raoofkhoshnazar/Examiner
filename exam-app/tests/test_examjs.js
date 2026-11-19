/* تست اجرایی static/exam.js بدون مرورگر.
   فایل را در یک محیط DOM حداقلی اجرا می‌کند تا خطاهای زمان اجرا
   (مثل استفاده از متغیر تعریف‌نشده) که فقط با اجرا دیده می‌شوند گرفته شوند.
   اجرا: node tests/test_examjs.js */
"use strict";

const fs = require("fs");
const path = require("path");
const vm = require("vm");

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
    addEventListener() {},
    querySelector() { return null; },
    querySelectorAll() { return []; },
    closest() { return null; },
    focus() {},
    ...overrides,
  };
  return el;
}

function run({ withQuestions = true } = {}) {
  const errors = [];
  const timer = makeEl({ id: "timer" });
  const answered = makeEl({ id: "answeredCount" });
  const progress = makeEl({ id: "progress" });

  // یک پنل سوال با فیلد متنی، تا مسیر شمارندهٔ کاراکتر هم اجرا شود
  const field = makeEl({ tagName: "TEXTAREA", dataset: { qid: "C1" } });
  field.value = "";
  const panel = makeEl({ dataset: { qid: "C1" } });
  const byId = { timer, answeredCount: answered, progress };

  const found = (sel) => {
    if (!withQuestions) return null;
    if (typeof sel === "string" && sel.startsWith(".qpanel[data-qid=")) return panel;
    if (sel === 'textarea, input[type="text"]') return field;
    return null;
  };

  const listeners = [];        // (type, handler) برای شبیه‌سازی رخدادها
  const calls = [];            // درخواست‌های fetch برای بررسی محتوای ذخیره‌شده
  const document = {
    getElementById: (id) => byId[id] || makeEl({ id }),
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
    Date,
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
  return { sandbox, errors, timer, answered, progress, timers, listeners, calls, field };
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
  check("تایمر روی عدد معقول است", valid && t.startsWith("۵۹"), t);

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

// ---------------------------------------------------------------- مهلت نامعتبر
{
  const r = run();
  // اجرای دوباره با مهلت نامعتبر: تایمر نباید NaN نشان دهد
  const src = fs.readFileSync(SRC, "utf-8");
  check("منبع تایمر از عدد متناهی محافظت می‌کند", src.includes("Number.isFinite(lastTick)"));
}

// ---------------------------------------------------------------- پاسخ‌ها گم نشوند
(async () => {
  const r = run();

  // تایپ در یک سوال تشریحی، بدون خروج از فیلد
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
  const legacy = makeEl({ tagName: "INPUT", type: "radio", name: "answer", value: "الف",
                          dataset: { qid: "A9" } });
  fire(r, "change", legacy);
  await flushTimers(r);
  check("گروه عمومی و بی‌مالک «answer» دیگر پاسخ ثبت نمی‌کند",
        posts().length === callsBefore, `تعداد درخواست‌ها: ${posts().length}`);

  check("بدون خطای زمان اجرا در مسیر ذخیره", r.errors.length === 0, r.errors.join(" | "));

  console.log(failed ? `\n${failed} تست شکست خورد` : "\nهمهٔ تست‌های exam.js گذشت");
  process.exit(failed ? 1 : 0);
})();
