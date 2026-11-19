# -*- coding: utf-8 -*-
"""سامانهٔ آزمون «واژه‌بان» — سرور HTTP استاندارد، بدون وابستگی خارجی"""
import csv
import hashlib
import io
import json
import os
import random
import re
import secrets
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

import db
import grading
import integrity
import reportcard
from exam_data import (AUTO_POINTS, CASE_HTML, EXAM, MANUAL_POINTS, MODEL_ANSWERS, QUESTIONS,
                       QUESTIONS_BY_ID, SECTIONS, SECTION_POINTS, TOTAL_POINTS)

# جدول‌های متن کیس هم داخل قاب اسکرول می‌روند تا در موبایل صفحه را پهن نکنند
CASE_HTML = re.sub(r"<table(\s[^>]*)?>", r'<div class="table-wrap tight"><table\1>', CASE_HTML)
CASE_HTML = CASE_HTML.replace("</table>", "</table></div>")

VERSION = EXAM["version"]
DURATION = EXAM["duration_minutes"] * 60
HERE = os.path.dirname(os.path.abspath(__file__))
STATIC = os.path.join(HERE, "static")


# ------------------------------------------------------------------ helpers
def e(text):
    return (str(text if text is not None else "")
            .replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            .replace('"', "&quot;"))


FA_DIGITS = str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹")


def fa(n):
    return str(n).translate(FA_DIGITS)


def fmt(n):
    """عدد با جداکنندهٔ هزارگان فارسی"""
    try:
        if abs(n - round(n)) < 1e-9:
            return fa(f"{int(round(n)):,}".replace(",", "٬"))
        return fa(f"{n:,.2f}".replace(",", "٬"))
    except (TypeError, ValueError):
        return fa(0)


def fa_clock(seconds):
    seconds = max(0, int(seconds))
    m, s = divmod(seconds, 60)
    h, m = divmod(m, 60)
    if h:
        text = f"{h}:{m:02d}:{s:02d}"
    else:
        text = f"{m:02d}:{s:02d}"
    return text.translate(FA_DIGITS)


def order_for(seed, participant_name):
    """ترتیب سوال‌ها ثابت و گزینه‌ها تصادفی — قابل بازسازی با seed"""
    rng = random.Random(f"{seed}:{participant_name}")
    result = {}
    for section in SECTIONS:
        qs = [q for q in QUESTIONS if q["section"] == section["id"]]
        for q in qs:
            if q["kind"] in ("single", "multi", "match_one"):
                keys = [o["key"] for o in (q.get("options") or q.get("choices") or [])]
                rng.shuffle(keys)
                result[q["id"]] = {"opts": keys}
            elif q["kind"] == "match":
                keys = [c["key"] for c in q["choices"]]
                rng.shuffle(keys)
                result[q["id"]] = {"choices": keys}
            else:
                result[q["id"]] = {}
    return result


def detect_device(handler):
    """دستگاه تقریبی از روی User-Agent: موبایل / تبلت / لپ‌تاپ-دسکتاپ."""
    ua = (handler.headers.get("User-Agent") or "").lower()
    if not ua:
        return "ناشناس"
    if "ipad" in ua or "tablet" in ua or ("android" in ua and "mobile" not in ua):
        return "تبلت"
    if "iphone" in ua or "ipod" in ua or "windows phone" in ua or "mobile" in ua or "android" in ua:
        return "گوشی"
    return "لپ‌تاپ / دسکتاپ"


def client_ip(handler):
    fwd = handler.headers.get("X-Forwarded-For") or ""
    return (fwd.split(",")[0].strip() if fwd else handler.client_address[0])[:60]


def cookie_value(handler, name):
    raw = handler.headers.get("Cookie") or ""
    for part in raw.split(";"):
        k, _, v = part.strip().partition("=")
        if k == name:
            return v
    return None


# ------------------------------------------------------------------ pages
def wordmark(size="lg"):
    return f"""
    <a class="wordmark {size}" href="/">
      <span class="wordmark-text">واژه‌بان</span>
      <span class="institution-mark" aria-hidden="true"></span>
    </a>"""


def page(title, body, user=None, extra_head="", wide=False, variant="app"):
    """title: «عنوان — واژه‌بان»؛ مسیر فعال از page.current_path خوانده می‌شود."""
    nav = ""
    if user:
        role = "مدیر" if user["role"] == "admin" else ("مصحح" if user["role"] == "grader" else "شرکت‌کننده")
        if user["role"] == "participant":
            items = [("/exam", "آزمون"), ("/guide", "راهنمای آزمون")]
        elif user["role"] == "grader":
            items = [("/grader", "نتایج"), ("/exam", "کارنامه")]
        else:
            items = [("/admin", "مدیریت"), ("/admin/live", "وضعیت زنده"), ("/grader", "نتایج")]
        current = "/guide" if page.current_path == "/guide" else page.current_path
        links = "".join(
            f'<a class="navlink{" active" if href == current else ""}" href="{href}">{e(text)}</a>'
            for href, text in items)
        nav = f"""
        <header class="topbar">
          {wordmark()}
          <nav class="navlinks">{links}</nav>
          <div class="account">
            <span class="who">{e(user['display_name'])} <span class="sep">/</span> {role}</span>
            <a class="signout" href="/logout">خروج از حساب</a>
          </div>
        </header>"""
    footer = """
    <footer class="site-footer">
      <span>آزمون کیس‌محور · نسخهٔ ۲.۰</span>
      <span>سامانهٔ ارزیابی کارشناسان پشتیبانی · مؤسسهٔ سرخ</span>
    </footer>"""
    return f"""<!doctype html>
<html lang="fa" dir="rtl">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{e(title)}</title>
<link rel="stylesheet" href="/static/style.css">
<link rel="icon" href="/static/favicon.svg" type="image/svg+xml">
<link rel="icon" href="/static/favicon-32.png" sizes="32x32" type="image/png">
<link rel="apple-touch-icon" href="/static/icons/icon-192.png">
<link rel="manifest" href="/static/manifest.webmanifest">
<meta name="theme-color" content="#2e2a2a">
<script src="/static/register-sw.js" defer></script>
{extra_head}
</head>
<body class="{'wide' if wide else ''} {variant}">
{nav}
<main>
{body}
</main>
{'' if variant == 'auth' else footer}
</body>
</html>"""


page.current_path = ""


def render_error(user, code=404, message=""):
    """صفحهٔ خطای دوستانه، بدون نمایش جزئیات فنی."""
    data = {
        404: ("این صفحه پیدا نشد", "نشانی‌ای که باز کردید وجود ندارد یا جابه‌جا شده است.",
              "همه‌چیز مرتب است؛ کافی است از دکمهٔ زیر برگردید."),
        403: ("دسترسی به این صفحه ندارید", "این بخش برای نقش فعلی حساب شما باز نیست.",
              "با حساب مناسب وارد شوید یا از مدیریت بخواهید دسترسی بدهد."),
        500: ("مشکلی پیش آمد", "خطایی موقت رخ داد و درخواست شما کامل نشد.",
              "لطفاً یک بار دیگر تلاش کنید؛ پاسخ‌های ذخیره‌شدهٔ آزمون دست‌نخورده‌اند."),
    }.get(code, ("خطا", "درخواست شما انجام نشد.", "لطفاً دوباره تلاش کنید."))
    title, sub, hint = data
    home = "/admin" if user and user["role"] == "admin" else (
        "/grader" if user and user["role"] == "grader" else ("/exam" if user else "/"))
    body = f"""
    <div class="errorpage">
      <div class="error-code">{fa(code)}</div>
      <h1>{e(title)}</h1>
      <p class="error-sub">{e(sub)}</p>
      {f'<p class="muted small">{e(message)}</p>' if message else ''}
      <p class="muted">{e(hint)}</p>
      <div class="actions center">
        <a class="btn primary" href="{home}">{"بازگشت به آزمون" if user else "بازگشت به ورود"}</a>
        <a class="btn" href="javascript:history.back()">صفحهٔ قبل</a>
      </div>
    </div>"""
    return page(f"{title} — واژه‌بان", body, user, variant="auth" if not user else "app")


ROLE_ORDER = {"admin": 0, "grader": 1, "participant": 2}


def login_usernames(conn):
    """نام کاربری‌های فعال برای فهرست انتخاب صفحهٔ ورود"""
    if conn is None:
        return []
    rows = conn.execute("SELECT username, role FROM users WHERE active=1").fetchall()
    pairs = [(r["username"], r["role"]) for r in rows]
    pairs.sort(key=lambda x: (ROLE_ORDER.get(x[1], 9), x[0].lower()))
    return [u for u, _ in pairs]


def render_login(conn=None, error="", notice=""):
    usernames = login_usernames(conn)
    options = "".join(f'<option value="{e(u)}">{e(u)}</option>' for u in usernames)
    body = f"""
    <header class="auth-header">
      {wordmark()}
      <span class="version-tag">نسخهٔ {fa(VERSION)}</span>
    </header>
    <main class="auth-main">
      <section class="auth-editorial">
        <span class="institution-badge">مؤسسهٔ سرخ <span class="sep">/</span> ارزیابی حرفه‌ای</span>
        <h1 class="auth-hero">دانشت را به<br>تصمیم تبدیل کن.</h1>
        <p class="auth-lede">آزمون کیس‌محور مبانی کسب‌وکار<br>یک مسئلهٔ واقعی؛ فرصتی برای نشان دادن نگاه تحلیلی...</p>
        <div class="auth-divider"></div>
        <div class="exam-facts">
          <div class="fact"><b>۱۰۰</b><span>نمره</span></div>
          <div class="fact"><b>۲۵</b><span>سؤال</span></div>
          <div class="fact"><b>{fa(EXAM["duration_minutes"])}</b><span>دقیقه</span></div>
        </div>
        <p class="auth-note">«در کیس نیست» هم یک پاسخ آگاهانه است؛<br>داده‌ها را ببینید، استدلال کنید و تصمیم ب...</p>
        <span class="auth-kicker">EXAMINER <span class="sep">/</span> VAZHEBAN</span>
      </section>

      <section class="auth-form">
        <h2 class="auth-title">خوش آمدید</h2>
        <p class="auth-sub">برای ورود به آزمون، اطلاعات حساب اختصاصی خود را وارد کنید.</p>
        {f'<div class="alert error" role="alert">{e(error)}</div>' if error else ''}
        {f'<div class="alert ok" role="status">{e(notice)}</div>' if notice else ''}
        <form method="post" action="/login" class="login-form" aria-label="ورود به سامانه">
          <label class="field">
            <span class="field-label">نام کاربری</span>
            <select name="username" class="field-select username-list" required autofocus aria-label="نام کاربری را از فهرست انتخاب کنید">
              <option value="" disabled selected>— نام کاربری خود را از فهرست انتخاب کنید —</option>
              {options}
            </select>
            <span class="field-help">روی کادر بزنید و با اسکرول بین نام‌ها، نام کاربری خودتان را انتخاب کنید؛ پس از انتخاب، فهرست بسته می‌شود.</span>
          </label>
          <label class="field">
            <span class="field-label">رمز عبور</span>
            <input name="password" type="password" placeholder="••••••••" autocomplete="current-password" required aria-label="رمز عبور">
          </label>
          <button class="btn-login" type="submit" aria-label="ورود به سامانه">ورود به سامانه ←</button>
        </form>
        <div class="auth-hint">
          <b>حساب کاربری ندارید؟</b>
          <span>نام کاربری و رمز اختصاصی را از مسئول آزمون مؤسسه دریافت کنید.</span>
        </div>
        <p class="auth-foot">ورود به‌معنای آمادگی برای شروع آزمون نیست؛<br>پیش از شروع، راهنما را خواهید دید.</p>
      </section>
    </main>
    <footer class="auth-footer">
      <span>نسخهٔ {fa(VERSION)}</span>
      <span>مؤسسهٔ سرخ</span>
    </footer>"""
    return page("ورود — آزمون واژه‌بان", body, variant="auth")


def render_intro(user):
    return page("راهنمای آزمون — واژه‌بان", f"""
    <div class="page-head">
      <div>
        <span class="eyebrow">مؤسسهٔ سرخ · ارزیابی حرفه‌ای</span>
        <h1 class="page-title">{e(EXAM['title'])}</h1>
        <p class="page-sub">یک کیس واقعی، ۲۵ سوال، {fa(EXAM["duration_minutes"])} دقیقه. پیش از شروع این صفحه را تا انتها بخوانید.</p>
      </div>
      <span class="version-chip">نسخهٔ {fa(VERSION)}</span>
    </div>

    <div class="guide-grid">
      <section class="panel guide-main">
        <h2 class="panel-title">راهنمای شرکت در آزمون</h2>
        <div class="intro-text">{EXAM['intro']}</div>
        <h3 class="subhead">چک‌لیست پیش از شروع</h3>
        <ul class="checklist">
          <li>کیس «واژه‌بان» در تمام مدت آزمون کنار سوال‌ها قابل مشاهده است؛ لازم نیست جایی بروید.</li>
          <li>تایمر از لحظهٔ شروع روی سرور اجرا می‌شود و با بستن مرورگر متوقف نمی‌شود.</li>
          <li>پاسخ‌ها هنگام نوشتن ذخیره می‌شوند؛ اگر اتصال قطع شد، به همان نقطه برمی‌گردید.</li>
          <li>پس از پایان زمان، پاسخ‌ها خودکار ارسال می‌شوند. شما فقط یک بار می‌توانید آزمون بدهید.</li>
          <li>بخش‌های تشریحی پس از آزمون با روبریک تصحیح می‌شوند؛ نمرهٔ نهایی پس از آن اعلام می‌شود.</li>
          <li>هر پاسخ تشریحی باید حداقل {fa(integrity.MIN_TEXT_CHARS)} کاراکتر داشته باشد؛ تا آن حد، ارسال ممکن نیست.</li>
          <li>کپی، چسباندن و کشیدن متن در صفحهٔ آزمون غیرفعال است و تلاش‌ها ثبت می‌شوند.</li>
          <li>ورود هم‌زمان از دو دستگاه ممکن نیست؛ ورود دوم، نشست قبلی را می‌بندد.</li>
          <li>خروج از صفحهٔ آزمون و تلاش برای گرفتن اسکرین‌شات ثبت می‌شود؛ اگر مرورگر بسته شود، زمان از دست نمی‌رود و با همان حساب برمی‌گردید.</li>
        </ul>
        <div class="notice">
          <b>شرط قبولی:</b> ۶۵ از ۱۰۰ و حداقل ۶ از ۱۰ در بخش محاسبهٔ ساده.
          نمرهٔ منفی وجود ندارد؛ هیچ سوالی را خالی نگذارید.
        </div>
        <form method="post" action="/exam/start" class="guide-cta">
          <button class="btn primary big" type="submit">شروع آزمون ←</button>
        </form>
      </section>

      <aside class="panel guide-side">
        <div class="fact-row">
          <div class="fact-card"><b>۱۰۰</b><span>نمره</span></div>
          <div class="fact-card"><b>۲۵</b><span>سؤال</span></div>
          <div class="fact-card"><b>{fa(EXAM["duration_minutes"])}</b><span>دقیقه</span></div>
        </div>
        <div class="divider"></div>
        <h3 class="subhead">ساختار بخش‌ها</h3>
        <div class="table-wrap tight"><table class="mini-table">
          <thead><tr><th>بخش</th><th>نوع</th><th>بارم</th></tr></thead>
          <tbody>
          {''.join(f'<tr><td>{e(s["id"])}</td><td>{e(s["title"])}</td><td>{fa(s["points"])}</td></tr>' for s in SECTIONS)}
          </tbody>
        </table></div>
        <p class="muted small">بارم دستی با روبریک مصحح محاسبه می‌شود.</p>
      </aside>
    </div>""", user)


def options_html(q, order):
    src = q.get("options") or q.get("choices") or []
    keys = order.get("opts") or [o["key"] for o in src]
    by_key = {o["key"]: o["text"] for o in src}
    out = []
    for i, k in enumerate(keys):
        input_type = "radio" if q["kind"] != "multi" else "checkbox"
        name = "answer" if q["kind"] != "multi" else "answer_multi"
        out.append(f"""<label class="option">
          <input type="{input_type}" name="{name}" value="{e(k)}" data-qid="{q['id']}">
          <span class="optkey">{fa(i+1)}</span>
          <span>{by_key[k]}</span>
        </label>""")
    return "\n".join(out)


def render_question(q, order, n):
    """بدنهٔ سوال برای پنل راست"""
    head = f'<div class="qhead"><span class="qbadge">{e(q["id"])}</span><span class="pts">{fa(q["points"])} نمره</span></div>'
    stem = f'<div class="stem">{q["stem"]}</div>'
    body = ""
    kind = q["kind"]
    if q["kind"] in ("single", "multi", "match_one"):
        body = f'<div class="options" data-kind="{q["kind"]}">{options_html(q, order)}</div>'
    elif kind == "tf_explain":
        body = f"""
        <div class="tfbox" data-qid="{q['id']}">
          <div class="tfrow">
            <button type="button" class="btn tf" data-val="1">درست</button>
            <button type="button" class="btn tf" data-val="0">غلط</button>
          </div>
        </div>
        <label class="freetext">
          <span>{e(q['explain_label'])}</span>
          <textarea rows="3" data-qid="{q['id']}" data-field="explain" placeholder="در یک جمله…"></textarea>
        </label>"""
    elif kind == "match":
        by_key = {c["key"]: c["text"] for c in q["choices"]}
        keys = order.get("choices") or [c["key"] for c in q["choices"]]
        rows = []
        for pair in q["pairs"]:
            opts = "".join(f'<option value="{e(k)}">{e(k)}. {e(by_key[k])}</option>' for k in keys)
            rows.append(f"""<tr>
              <td class="match-left">{e(pair['left'])}</td>
              <td><select data-qid="{q['id']}" data-pid="{e(pair['id'])}">
                <option value="">— انتخاب شاهد —</option>{opts}
              </select></td>
            </tr>""")
        body = f'<div class="table-wrap tight"><table class="match-table"><thead><tr><th>مفهوم</th><th>شاهد در کیس</th></tr></thead><tbody>{"".join(rows)}</tbody></table></div>'
    elif kind == "numeric":
        f = q["fields"][0]
        body = f"""<label class="numfield"><span>{e(f['label'])}</span>
          <input type="text" inputmode="decimal" data-qid="{q['id']}" data-field="{e(f['key'])}" placeholder="مثلاً ۳٬۰۰۰٬۰۰۰">
        </label>
        <label class="freetext"><span>{e(q.get('work_label','مسیر محاسبه'))}</span>
          <textarea rows="2" data-qid="{q['id']}" data-field="work"></textarea></label>"""
    elif kind == "numeric_multi":
        fields = "".join(f"""<label class="numfield"><span>{e(f['label'])}</span>
          <input type="text" inputmode="decimal" data-qid="{q['id']}" data-field="{e(f['key'])}" placeholder="مثلاً ۲۱٬۰۰۰٬۰۰۰">
        </label>""" for f in q["fields"])
        concl = q.get("conclusion")
        opts = "".join(f'<label class="option"><input type="radio" name="c_{q["id"]}" data-qid="{q["id"]}" data-field="conclusion" value="{e(o["key"])}"><span>{e(o["text"])}</span></label>' for o in concl["options"])
        body = fields + f'<div class="options">{opts}</div><label class="freetext"><span>{e(q.get("work_label","مسیر محاسبه"))}</span><textarea rows="2" data-qid="{q["id"]}" data-field="work"></textarea></label>'
    elif kind == "text":
        body = f'<label class="freetext"><textarea rows="5" data-qid="{q["id"]}" data-field="text" placeholder="پاسخ خود را اینجا بنویسید…"></textarea></label>'
    elif kind == "structured":
        parts = []
        if q.get("claims"):
            parts.append('<div class="claim-box"><b>ادعاها:</b><ol>' + "".join(
                f'<li><label><input type="checkbox" class="claimchk" data-qid="{q["id"]}" value="{e(c["key"])}"> {e(c["text"])}</label></li>'
                for c in q["claims"]) + "</ol></div>")
        for f in q.get("fields", []):
            parts.append(f'<label class="freetext"><span>{e(f["label"])}</span>'
                         f'<textarea rows="{f.get("rows",2)}" data-qid="{q["id"]}" data-field="{e(f["key"])}"></textarea></label>')
        if q.get("claims"):
            parts.append(f'<label class="freetext"><span>خطای استدلالی و اصلاح آن (برای هر ادعای انتخاب‌شده)</span>'
                         f'<textarea rows="4" data-qid="{q["id"]}" data-field="notes"></textarea></label>')
        body = "".join(parts)
    return head + stem + body


ALLOWED_EVENTS = {"blur", "paste", "copy", "cut", "screenshot"}


def auto_submit_expired(conn):
    """هر تلاشِ فعالی که مهلتش گذشته، خودکار ارسال و ذخیره می‌شود."""
    now = int(time.time())
    rows = conn.execute(
        "SELECT id FROM attempts WHERE submitted_at IS NULL AND deadline <= ?", (now,)).fetchall()
    for r in rows:
        conn.execute("UPDATE attempts SET submitted_at=?, status='expired' WHERE id=? AND submitted_at IS NULL",
                     (now, r["id"]))
        conn.commit()
        db.log_event(conn, r["id"], "auto_submit", "زمان آزمون تمام شد")
        owner = conn.execute("SELECT user_id FROM attempts WHERE id=?", (r["id"],)).fetchone()
        if owner:
            db.log_audit(conn, owner["user_id"], "exam_auto_submit", "ارسال خودکار پایان زمان")
        recompute_attempt(conn, r["id"])
    return len(rows)


def render_exam(user, attempt, answers):
    order = json.loads(attempt["order_json"])
    sections_html = []
    for section in SECTIONS:
        qs = [q for q in QUESTIONS if q["section"] == section["id"]]
        blocks = []
        for q in qs:
            blocks.append(f'<div class="qpanel" id="panel-{q["id"]}" data-qid="{q["id"]}">'
                          f'{render_question(q, order.get(q["id"], {}), 0)}</div>')
        sections_html.append(f"""
        <section class="section-block" id="sec-{section['id']}">
          <h2>بخش {e(section['id'])} — {e(section['title'])}
            <span class="muted small">{fa(section['count'])} سوال · {fa(section['points'])} نمره · حدود {fa(section['time_minutes'])} دقیقه</span>
          </h2>
          {f'<p class="hint">{e(section["hint"])}</p>' if section.get('hint') else ''}
          {''.join(blocks)}
        </section>""")

    flat_questions = []
    for section in SECTIONS:
        for q in QUESTIONS:
            if q["section"] == section["id"]:
                flat_questions.append(q)

    grid = "".join(
        f'<button class="qnav" data-target="{q["id"]}" data-section="{q["section"]}">{e(q["id"])}</button>'
        for q in flat_questions)

    resumed = int(time.time()) - attempt["started_at"] > 90
    resume_note = ('<p class="resume-note">این ادامهٔ آزمون شماست؛ پاسخ‌های ذخیره‌شده برگشتند و زمان از لحظهٔ شروع بدون توقف ادامه دارد.</p>'
                   if resumed else '')

    body = f"""
    {resume_note}
    <div class="recbar" aria-live="polite"><span class="recdot"></span> این آزمون در حال ثبت فعالیت است؛ کپی، چسباندن و گرفتن تصویر از صفحه غیرفعال است.</div>
    <div class="timerbar">
      <div class="timer" id="timer" role="timer" aria-live="off" aria-label="زمان باقی‌ماندهٔ آزمون">--:--</div>
      <div class="progresswrap" role="progressbar" aria-label="تعداد پاسخ‌های ثبت‌شده" aria-valuemin="0" aria-valuemax="25"><div class="progress" id="progress"></div></div>
      <div class="answered" id="answeredCount" aria-live="polite">۰ از ۲۵ پاسخ</div>
      <button class="btn danger" id="submitBtn" type="button" aria-label="ارسال نهایی پاسخ‌ها و پایان آزمون">ارسال نهایی</button>
    </div>
    <div class="exam-layout">
      <div class="case-pane" id="casePane">
        <div class="case-head">
          <b>کیس واژه‌بان</b>
          <button class="btn small" id="toggleCase" type="button" aria-controls="caseBody" aria-expanded="true">بستن / بازکردن</button>
        </div>
        <p class="case-lead">پیش از پاسخ دادن، این کیس را کامل بخوانید. متن کیس در تمام مدت آزمون همین‌جا در دسترس است.</p>
        <div class="case-body" id="caseBody">{CASE_HTML}</div>
        <div class="case-foot">
          <a class="btn primary" href="#qgrid">کیس را خواندم؛ رفتن به سوال‌ها ↓</a>
        </div>
      </div>
      <div class="exam-main">
        <div class="answers-head" id="answersHead">سوال‌ها</div>
        <div class="qgrid" id="qgrid">{grid}</div>
        <div class="section-nav" id="sectionNav">
          {''.join(f'<a href="#sec-{s["id"]}">بخش {e(s["id"])}</a>' for s in SECTIONS)}
        </div>
        <div id="sections">{''.join(sections_html)}</div>
      </div>
    </div>
    <div class="timeover" id="timeOver" role="alert" aria-live="assertive">
      <div class="timeover-card">
        <h2>وقت آزمون تمام شد</h2>
        <p>زمان ۶۰ دقیقه‌ای آزمون به پایان رسید. پاسخ‌هایی که تا این لحظه ثبت شده بود، خودکار برای مصحح ارسال و ذخیره شد.</p>
        <p class="muted">در حال باز کردن نتیجه…</p>
      </div>
    </div>
    <div class="modal-back" id="modalBack">
      <div class="modal">
        <h3>ارسال نهایی آزمون</h3>
        <p id="modalText"></p>
        <div class="modal-actions">
          <button class="btn" id="modalCancel">بازگشت</button>
          <button class="btn primary" id="modalConfirm">بله، ارسال کن</button>
        </div>
      </div>
    </div>
    <script>
      window.EXAM_STATE = {json.dumps({
        "deadline": attempt["deadline"],
        "serverNow": int(time.time()),
        "qids": [q["id"] for q in flat_questions],
        "sections": SECTION_POINTS,
        "minChars": integrity.MIN_TEXT_CHARS,
        "minCharQids": [q["id"] for q in flat_questions if integrity.min_char_fields(q)],
        "saved": answers,
      }, ensure_ascii=False)};
    </script>
    <script src="/static/exam.js"></script>"""
    return page("آزمون — واژه‌بان", body, user, wide=True, variant="app taking-exam")


def render_result(user, attempt, section_scores, manual_pending):
    total = attempt["total_score"]
    auto = attempt["auto_score"]
    manual = attempt["manual_score"] or 0
    rows = []
    from exam_data import SECTIONS as SECS
    for s in SECS:
        sc = section_scores.get(s["id"], 0)
        pct = (sc / s["points"] * 100) if s["points"] else 0
        status = "قوی" if pct >= 75 else ("قابل قبول" if pct >= 50 else "نیازمند تقویت")
        rows.append(f"""<tr><td>{e(s['title'])}</td><td>{fmt(sc)}</td><td>{fa(s['points'])}</td>
        <td>{fmt(round(pct))}٪</td><td><span class="badge {'good' if pct>=75 else ('mid' if pct>=50 else 'low')}">{status}</span></td></tr>""")
    passed = attempt["passed"]
    verdict = "قبول" if passed else ("قبول مشروط" if passed is None else "نیاز به تلاش بیشتر")
    e_score = section_scores.get("E", 0)
    cond_note = ""
    if total >= 65 and e_score < 6:
        cond_note = '<div class="alert error">شرط حداقلی بخش محاسبه (۶ از ۱۰) محقق نشده است.</div>'

    expired = attempt["status"] == "expired"
    expired_note = ""
    if expired:
        expired_note = f"""<div class="alert warn time-over">
          <b>وقت آزمون تمام شد.</b> پاسخ‌هایی که تا این لحظه ثبت شده بود، خودکار برای مصحح ارسال و ذخیره شد.
          سوالی که پیش از پایان زمان ذخیره نکرده‌اید در این نتیجه لحاظ نشده است.
        </div>"""

    body = f"""
    <div class="card">
      <h1>{'وقت آزمون تمام شد' if expired else 'نتیجهٔ آزمون'}</h1>
      <p class="muted">{e(user['display_name'])} — نسخهٔ {fa(VERSION)} — {'ارسال خودکار' if expired else 'ارسال‌شده'} در {time.strftime('%Y-%m-%d %H:%M', time.localtime(attempt['submitted_at'] or time.time()))}</p>
      {expired_note}
      {f'<div class="alert ok">نتیجهٔ نهایی است.</div>' if not manual_pending else f'<div class="alert warn">بخش‌های تشریحی در حال تصحیح است. نمرهٔ خودکار {fmt(auto)} از {fa(AUTO_POINTS)}؛ نمرهٔ نهایی پس از تصحیح اعلام می‌شود.</div>'}
      {cond_note}
      <div class="score-hero">
        <div class="score-big">{fmt(total)}<span>از ۱۰۰</span></div>
        <div class="score-verdict">{verdict}</div>
        <div class="score-split">
          <span>خودکار: {fmt(auto)}</span>
          <span>تشریحی: {fmt(manual)} از {fa(MANUAL_POINTS)}</span>
        </div>
      </div>
      <div class="table-wrap md"><table class="table">
        <thead><tr><th>بخش</th><th>نمره</th><th>از</th><th>درصد</th><th>وضعیت</th></tr></thead>
        <tbody>{''.join(rows)}</tbody>
      </table></div>
      <p class="muted small">معیار قبولی: {fa(65)} از {fa(100)} و حداقل {fa(6)} از {fa(10)} در بخش محاسبه.</p>
      <div class="actions">
        <a class="btn primary" href="/report/{attempt['id']}">مشاهدهٔ کارنامهٔ ارزیابی</a>
        <a class="btn" href="/report/{attempt['id']}?download=1">دانلود کارنامه</a>
      </div>
    </div>"""
    return page("نتیجه — واژه‌بان", body, user)


# ------------------------------------------------------------------ grader
def attempt_health(conn, attempt_row):
    """سلامت یک تلاش: رخدادها، زمان هر سوال و درصد تشابه با بقیه."""
    answers = {r["qid"]: r for r in conn.execute(
        "SELECT * FROM answers WHERE attempt_id=?", (attempt_row["id"],))}
    events = conn.execute("SELECT * FROM events WHERE attempt_id=?", (attempt_row["id"],)).fetchall()
    return integrity.health(attempt_row, answers, events)


def similarity_for(conn):
    """درصد تشابه هر شرکت‌کننده با بقیه (فقط تلاش‌های ارسال‌شده)."""
    rows = conn.execute(
        "SELECT a.id, a.user_id, u.display_name, u.username FROM attempts a "
        "JOIN users u ON u.id=a.user_id WHERE a.submitted_at IS NOT NULL").fetchall()
    participants = []
    by_attempt = {}
    for r in rows:
        answers = {x["qid"]: json.loads(x["payload"]) for x in conn.execute(
            "SELECT qid, payload FROM answers WHERE attempt_id=?", (r["id"],))}
        texts = {q["id"]: integrity.answer_text(q, answers.get(q["id"]) or {}) for q in QUESTIONS}
        p = {"id": r["id"], "name": r["display_name"] or r["username"], "texts": texts}
        participants.append(p)
        by_attempt[r["id"]] = p
    return integrity.similarity_matrix(participants, QUESTIONS)


LEVEL_BADGE = {"medium": "mid", "high": "low", "critical": "low"}
LEVEL_CLASS = {"medium": "sim-medium", "high": "sim-high", "critical": "sim-critical"}


def render_grader(user, conn):
    rows = conn.execute("""
      SELECT a.*, u.display_name, u.username,
        (SELECT COUNT(*) FROM answers an WHERE an.attempt_id=a.id AND an.manual_score IS NULL
          AND an.qid IN (SELECT qid FROM answers WHERE attempt_id=a.id)) AS dummy
      FROM attempts a JOIN users u ON u.id=a.user_id ORDER BY a.started_at DESC
    """).fetchall()
    manual_qids = [q["id"] for q in QUESTIONS if q["manual"] > 0]
    ph = ",".join("?" * len(manual_qids))
    stats = {"total": 0, "submitted": 0, "graded": 0, "avg": 0.0, "passed": 0,
             "flagged": 0, "paste": 0, "critical": 0}
    sims = similarity_for(conn)
    out = []
    for a in rows:
        submitted = a["submitted_at"] is not None
        sim = sims.get(a["id"], {})
        pending = conn.execute(
            f"SELECT COUNT(*) c FROM answers WHERE attempt_id=? AND qid IN ({ph}) AND manual_score IS NULL",
            (a["id"], *manual_qids)).fetchone()["c"]
        answered = conn.execute("SELECT COUNT(*) c FROM answers WHERE attempt_id=?", (a["id"],)).fetchone()["c"]
        status = "در حال آزمون" if not submitted else ("در انتظار تصحیح" if pending else "تصحیح‌شده")
        h = attempt_health(conn, a)
        warnings = integrity.flags(h, sim)
        risky = [w for w in warnings if w[0] != "info"]
        if risky:
            stats["flagged"] += 1
        if h["paste"]:
            stats["paste"] += 1
        if sim.get("level") == "critical":
            stats["critical"] += 1
        sim_cell = "—"
        if submitted and sim:
            sim_cell = (f'<span class="sim {LEVEL_CLASS.get(sim["level"], "")}">'
                        f'{fmt(sim["max"])}٪</span>'
                        f'<span class="muted small"> با {e(sim["with"])}</span>' if sim.get("with") else "—")
        health_cell = (f'<a class="btn small{" warn" if risky else ""}" href="/grader/attempt/{a["id"]}#health">'
                       f'{"⚠ " + fa(len(risky)) + " هشدار" if risky else "سالم"}</a>' if submitted else "—")
        out.append(f"""<tr>
          <td>{e(a['display_name'])}</td>
          <td>{e(a['username'])}</td>
          <td>{'—' if not submitted else time.strftime('%Y-%m-%d %H:%M', time.localtime(a['submitted_at']))}</td>
          <td>{status}</td>
          <td>{fa(answered)} / {fa(25)}</td>
          <td>{fmt(a['auto_score'])}</td>
          <td>{fmt(a['total_score'])}</td>
          <td>{'—' if pending or not submitted else ('قبول' if a['passed'] else 'رد')}</td>
          <td>{sim_cell}</td>
          <td>{health_cell}</td>
          <td>{'—' if not submitted else f'<a class="btn small" href="/grader/attempt/{a["id"]}">تصحیح</a>'}</td>
        </tr>""")
        if submitted:
            stats["submitted"] += 1
            if pending:
                stats["graded"] += 0
            else:
                stats["graded"] += 1
                stats["avg"] += a["total_score"]
                if a["passed"]:
                    stats["passed"] += 1
        stats["total"] += 1
    avg = stats["avg"] / stats["graded"] if stats["graded"] else 0
    body = f"""
    <div class="card wide-card">
      <h1>پنل مصحح — مطالعه</h1>
      <div class="stat-grid">
        <div class="stat"><b>{fa(stats['submitted'])}</b><span>ارسال‌شده</span></div>
        <div class="stat"><b>{fa(stats['graded'])}</b><span>تصحیح‌شده</span></div>
        <div class="stat"><b>{fmt(round(avg))}</b><span>میانگین نمره</span></div>
        <div class="stat"><b>{fa(stats['passed'])}</b><span>قبول</span></div>
        <div class="stat"><b>{fa(stats['flagged'])}</b><span>با هشدار سلامت</span></div>
        <div class="stat"><b>{fa(stats['paste'])}</b><span>تلاش برای چسباندن</span></div>
        <div class="stat"><b>{fa(stats['critical'])}</b><span>تشابه بحرانی</span></div>
      </div>
      <div class="actions">
        <a class="btn primary" href="/grader/export.csv">دانلود اکسل (CSV) کامل</a>
        <a class="btn" href="/grader/export-answers.csv">دانلود پاسخ‌های خام</a>
      </div>
      <div class="table-wrap wide"><table class="table">
        <thead><tr><th>نام</th><th>نام کاربری</th><th>زمان ارسال</th><th>وضعیت</th><th>پاسخ</th><th>خودکار</th><th>کل</th><th>نتیجه</th><th>تشابه</th><th>سلامت</th><th></th></tr></thead>
        <tbody>{''.join(out) or '<tr><td colspan="11" class="muted">هنوز تلاشی ثبت نشده است.</td></tr>'}</tbody>
      </table></div>
    </div>"""
    return page("پنل مصحح — واژه‌بان", body, user, wide=True)


LIVE_IDLE_SECONDS = 120     # بی‌فعالیتی بیشتر از این، «نیمه‌کاره خارج‌شده» شمرده می‌شود

AUDIT_LABEL = {
    "login": "ورود", "logout": "خروج", "login_failed": "ورود ناموفق",
    "exam_start": "شروع آزمون", "exam_submit": "ارسال آزمون",
    "exam_auto_submit": "ارسال خودکار", "admin_reset_password": "تغییر رمز",
    "admin_reset_attempt": "بازنشانی تلاش", "admin_create_user": "ساخت کاربر",
}
AUDIT_TONE = {"login": "good", "logout": "mid", "login_failed": "low",
              "exam_submit": "good", "exam_auto_submit": "mid"}


def device_icon(device):
    return {"گوشی": "📱", "تبلت": "📟", "لپ‌تاپ / دسکتاپ": "💻"}.get(device, "·")


def live_snapshot(conn):
    """عکس لحظه‌ای وضعیت آزمون: در حال آزمون، تمام‌کرده، منقضی، نیمه‌کاره."""
    now = int(time.time())
    rows = conn.execute(
        "SELECT a.*, u.display_name, u.username FROM attempts a JOIN users u ON u.id=a.user_id "
        "ORDER BY a.started_at DESC").fetchall()
    snap = {"live": [], "done": [], "expired": [], "left": [], "now": now}
    for a in rows:
        answered = conn.execute("SELECT COUNT(*) AS c FROM answers WHERE attempt_id=?",
                                (a["id"],)).fetchone()["c"]
        last = a["last_seen"] or a["started_at"]
        item = {
            "name": a["display_name"], "username": a["username"],
            "device": a["device"] or "ناشناس", "answered": answered,
            "remaining": a["deadline"] - now, "idle": now - last,
            "progress": round(answered / len(QUESTIONS) * 100),
            "submitted": a["submitted_at"], "score": a["total_score"],
        }
        if a["submitted_at"]:
            snap["expired" if a["status"] == "expired" else "done"].append(item)
        elif item["idle"] > LIVE_IDLE_SECONDS:
            snap["left"].append(item)
        else:
            snap["live"].append(item)
    snap["audit"] = conn.execute(
        "SELECT au.*, u.display_name, u.username FROM audit au LEFT JOIN users u ON u.id=au.user_id "
        "ORDER BY au.id DESC LIMIT 60").fetchall()
    return snap


def _progress_cell(item):
    return (f'<div class="miniprogress"><span style="width:{item["progress"]}%"></span></div>'
            f'<span class="muted small">{fa(item["answered"])} / {fa(len(QUESTIONS))}'
            f' · {fa(item["progress"])}٪</span>')


def _person_cell(item):
    return f'{e(item["name"])}<br><span class="muted small">{e(item["username"])}</span>'


def _device_cell(item):
    return f'{device_icon(item["device"])} {e(item["device"])}'


def _live_table(items, empty_text):
    if not items:
        return f'<p class="muted">{empty_text}</p>'
    rows = []
    for it in items:
        active = it["idle"] < 45
        state = ('<span class="badge good">فعال</span>' if active else
                 f'<span class="badge mid">بی‌فعالیت {fa(max(0, it["idle"]) // 60)} دقیقه</span>')
        rows.append(
            "<tr><td>" + _person_cell(it) + "</td>"
            "<td>" + _device_cell(it) + "</td>"
            "<td>" + _progress_cell(it) + "</td>"
            f"<td>{fa_clock(max(0, it['remaining']))}</td><td>{state}</td></tr>")
    head = ("<thead><tr><th>نام</th><th>دستگاه</th><th>پیشرفت</th>"
            "<th>زمان باقی‌مانده</th><th>وضعیت</th></tr></thead>")
    return f'<div class="table-wrap md"><table class="table compact">{head}<tbody>{"".join(rows)}</tbody></table></div>'


def _done_table(items, empty_text, label):
    if not items:
        return f'<p class="muted">{empty_text}</p>'
    rows = "".join(
        "<tr><td>" + _person_cell(it) + "</td>"
        "<td>" + _device_cell(it) + "</td>"
        f"<td>{time.strftime('%H:%M', time.localtime(it['submitted']))}</td>"
        f"<td>{fmt(it['score'] or 0)}</td></tr>" for it in items)
    head = f"<thead><tr><th>نام</th><th>دستگاه</th><th>{e(label)}</th><th>نمره</th></tr></thead>"
    return f'<div class="table-wrap md"><table class="table compact">{head}<tbody>{rows}</tbody></table></div>'


def render_audit_rows(rows):
    return "".join(
        f"<tr><td>{time.strftime('%m-%d %H:%M', time.localtime(r['created_at']))}</td>"
        f"<td>{e(r['display_name'] or r['username'] or '—')}</td>"
        f"<td><span class=\"badge {AUDIT_TONE.get(r['action'], 'mid')}\">"
        f"{e(AUDIT_LABEL.get(r['action'], r['action']))}</span></td>"
        f"<td>{e(r['detail'] or '')}</td>"
        f"<td>{device_icon(r['device'] or '')} {e(r['device'] or '—')}</td></tr>"
        for r in rows)


def render_live(user, conn):
    snap = live_snapshot(conn)
    now = snap["now"]
    counts = [("در حال آزمون", len(snap["live"])), ("تمام‌کرده", len(snap["done"])),
              ("منقضی", len(snap["expired"])), ("نیمه‌کاره خارج‌شده", len(snap["left"]))]
    stats = "".join(f'<div class="stat"><b>{fa(n)}</b><span>{e(t)}</span></div>' for t, n in counts)
    audit_rows = render_audit_rows(snap["audit"])
    body = f"""
    <div class="card wide-card">
      <div class="livehead">
        <div>
          <h1>وضعیت زندهٔ آزمون</h1>
          <p class="muted">آخرین به‌روزرسانی: {time.strftime('%H:%M:%S', time.localtime(now))} —
          این صفحه هر ۲۰ ثانیه خودکار تازه می‌شود.</p>
        </div>
        <span class="livechip"><span class="recdot"></span> زنده</span>
      </div>
      <div class="stat-grid">{stats}</div>

      <h2>در حال آزمون ({fa(len(snap['live']))})</h2>
      {_live_table(snap['live'], 'در این لحظه کسی آزمون نمی‌دهد.')}

      <h2>نیمه‌کاره خارج‌شده ({fa(len(snap['left']))})</h2>
      <p class="muted small">بیش از دو دقیقه است هیچ فعالیتی از این افراد ثبت نشده؛ می‌توانند با همان حساب برگردند و تایمرشان ادامه دارد.</p>
      {_live_table(snap['left'], 'همهٔ آزمون‌دهنده‌ها فعال‌اند.')}

      <div class="twocol">
        <div><h2>تمام‌کرده ({fa(len(snap['done']))})</h2>
        {_done_table(snap['done'], 'هنوز کسی ارسال نکرده است.', 'ارسال')}</div>
        <div><h2>منقضی ({fa(len(snap['expired']))})</h2>
        {_done_table(snap['expired'], 'تلاش منقضی وجود ندارد.', 'ارسال خودکار')}</div>
      </div>

      <h2>لاگ ورودها و عملیات</h2>
      <p class="muted small">۶۰ رخداد آخر: ورود، خروج، ورود ناموفق، شروع و ارسال آزمون و اقدام‌های مدیر.</p>
      <div class="table-wrap md"><table class="table compact"><thead><tr><th>زمان</th><th>کاربر</th><th>رخداد</th><th>جزئیات</th><th>دستگاه</th></tr></thead>
      <tbody>{audit_rows or '<tr><td colspan="5" class="muted">هنوز رخدادی ثبت نشده است.</td></tr>'}</tbody></table></div>
      <p class="muted small">لاگ به‌صورت چرخشی فقط ۵۰۰۰ رخداد آخر را نگه می‌دارد.</p>
    </div>
    <script>setTimeout(function(){{ location.reload(); }}, 20000);</script>"""
    return page("وضعیت زنده — واژه‌بان", body, user, wide=True)


def render_admin(user, conn, notice="", error=""):
    rows = conn.execute(
        "SELECT u.*, a.id AS attempt_id, a.submitted_at, a.total_score, a.started_at "
        "FROM users u LEFT JOIN attempts a ON a.user_id = u.id ORDER BY u.role DESC, u.username").fetchall()
    role_label = {"admin": "مدیر", "grader": "مصحح", "participant": "شرکت‌کننده"}
    out = []
    for r in rows:
        if r["attempt_id"] is None:
            state = '<span class="badge mid">بدون تلاش</span>'
        elif r["submitted_at"]:
            state = f'<span class="badge good">ارسال‌شده · {fmt(r["total_score"])}</span>'
        else:
            state = '<span class="badge low">در حال آزمون</span>'
        reset_btn = ""
        if r["role"] == "participant":
            reset_btn = f"""
              <form method="post" action="/admin/reset-attempt" class="inline"
                    onsubmit="return confirm('همهٔ پاسخ‌های این کاربر پاک شود تا بتواند دوباره آزمون بدهد؟')">
                <input type="hidden" name="user_id" value="{r['id']}">
                <button class="btn small danger" type="submit">بازنشانی تلاش</button>
              </form>"""
        out.append(f"""<tr>
          <td>{e(r['username'])}</td>
          <td>{e(r['display_name'])}</td>
          <td>{role_label.get(r['role'], r['role'])}</td>
          <td>{state}</td>
          <td>
            <form method="post" action="/admin/reset-password" class="inline">
              <input type="hidden" name="user_id" value="{r['id']}">
              <input type="text" name="password" placeholder="رمز تازه" required minlength="3" style="max-width:130px">
              <button class="btn small" type="submit">تغییر رمز</button>
            </form>
            {reset_btn}
          </td>
        </tr>""")

    body = f"""
    <div class="card wide-card">
      <h1>مدیریت — سامانهٔ آزمون</h1>
      {f'<div class="alert ok">{e(notice)}</div>' if notice else ''}
      {f'<div class="alert error">{e(error)}</div>' if error else ''}

      <div class="stat-grid">
        <div class="stat"><b>{fa(len([r for r in rows if r['role']=='participant']))}</b><span>شرکت‌کننده</span></div>
        <div class="stat"><b>{fa(len([r for r in rows if r['submitted_at']]))}</b><span>آزمون ارسال‌شده</span></div>
        <div class="stat"><b>{fa(len([r for r in rows if r['role']=='grader']))}</b><span>مصحح</span></div>
      </div>

      <h2>ساخت شرکت‌کنندهٔ تازه</h2>
      <form method="post" action="/admin/create-user" class="stack-form">
        <label><span>نام کاربری</span><input name="username" required pattern="[A-Za-z0-9_.-]{{3,32}}"></label>
        <label><span>نام نمایشی</span><input name="display_name" required></label>
        <label><span>رمز عبور</span><input name="password" required minlength="3"></label>
        <button class="btn primary" type="submit">ساخت کاربر</button>
      </form>

      <h2>کاربران</h2>
      <div class="table-wrap wide"><table class="table">
        <thead><tr><th>نام کاربری</th><th>نام نمایشی</th><th>نقش</th><th>وضعیت آزمون</th><th>عملیات</th></tr></thead>
        <tbody>{''.join(out)}</tbody>
      </table></div>
      <div class="actions">
        <a class="btn primary" href="/admin/live">وضعیت زندهٔ آزمون</a>
        <a class="btn" href="/grader/export.csv">دانلود CSV نتایج</a>
        <a class="btn" href="/grader/export-answers.csv">دانلود پاسخ‌های خام</a>
      </div>
    </div>"""
    return page("مدیریت — واژه‌بان", body, user, wide=True)


def render_grader_attempt(user, conn, attempt_id):
    a = conn.execute("SELECT a.*, u.display_name, u.username FROM attempts a JOIN users u ON u.id=a.user_id WHERE a.id=?",
                     (attempt_id,)).fetchone()
    if not a:
        return None
    answers = {r["qid"]: r for r in conn.execute("SELECT * FROM answers WHERE attempt_id=?", (attempt_id,))}
    blocks = []
    for section in SECTIONS:
        blocks.append(f'<h2 class="gsec">بخش {e(section["id"])} — {e(section["title"])}</h2>')
        for q in QUESTIONS:
            if q["section"] != section["id"]:
                continue
            row = answers.get(q["id"])
            payload = json.loads(row["payload"]) if row else {}
            blocks.append(render_grader_question(q, payload, row, attempt_id))

    health_html = render_health_card(conn, a) + render_wrong_card(answers)

    body = f"""
    <div class="card wide-card">
      <div class="gradertop">
        <div>
          <h1>تصحیح: {e(a['display_name'])} <span class="muted small">({e(a['username'])})</span></h1>
          <p class="muted">وضعیت: {'ارسال‌شده' if a['submitted_at'] else 'در حال آزمون'} ·
          خودکار: {fmt(a['auto_score'])} · کل فعلی: {fmt(a['total_score'])}</p>
        </div>
        <div class="navactions">
          {"<a class='btn small' href='/grader/attempt/"+str(attempt_id)+"/prev'>قبلی</a>" if False else ""}
          <a class="btn small" href="/grader">بازگشت به فهرست</a>
          <a class="btn small" href="/report/{attempt_id}?download=1">کارنامه</a>
          <a class="btn small" href="/grader/attempt/{attempt_id}/next">بعدی →</a>
        </div>
      </div>
      <div class="grade-summary" id="gradeSummary">—</div>
      {health_html}
      {''.join(blocks)}
    </div>
    <script>window.ATTEMPT_ID = {attempt_id};</script>
    <script src="/static/grader.js"></script>"""
    return page("تصحیح — واژه‌بان", body, user, wide=True)


def render_health_card(conn, attempt_row):
    """گزارش سلامت آزمون: زمان، رخدادها، زمان هر سوال و تشابه."""
    answers = {r["qid"]: r for r in conn.execute(
        "SELECT * FROM answers WHERE attempt_id=?", (attempt_row["id"],))}
    events = conn.execute("SELECT * FROM events WHERE attempt_id=? ORDER BY id", (attempt_row["id"],)).fetchall()
    h = integrity.health(attempt_row, answers, events)
    sims = similarity_for(conn)
    sim = sims.get(attempt_row["id"], {})
    warnings = integrity.flags(h, sim)

    warn_rows = "".join(
        f'<li class="warn-item {w[0]}">{e(w[1])}</li>' for w in warnings
    ) or '<li class="ok-item">هیچ نشانهٔ مشکوکی ثبت نشده است.</li>'

    q_rows = []
    for q in QUESTIONS:
        row = answers.get(q["id"])
        secs = int(row["time_spent"] or 0) if row else 0
        if not row:
            state = '<span class="muted">بی‌پاسخ</span>'
        elif secs and secs < integrity.FAST_ANSWER_SECONDS:
            state = f'<span class="badge low">{fa(secs)} ثانیه — شتاب‌زده</span>'
        else:
            state = '—'
        q_rows.append(f"""<tr><td>{e(q['id'])}</td><td>{fa_clock(secs) if row else '—'}</td><td>{state}</td></tr>""")

    sim_block = '<p class="muted">هنوز پاسخ ارسال‌شده‌ای برای مقایسه نیست.</p>'
    if sim.get("with"):
        sim_block = f"""
        <div class="sim-hero {LEVEL_CLASS.get(sim['level'], '')}">
          <b>{fmt(sim['max'])}٪</b>
          <span>بیشترین تشابه با <b>{e(sim['with'])}</b> · میانگین تشابه {fmt(sim['avg'])}٪</span>
        </div>
        {f'<div class="alert {LEVEL_BADGE.get(sim["level"], "ok").replace("mid", "warn").replace("low", "error")}">'
         f'<b>{e(integrity.LEVEL_LABEL[sim["level"]])}</b> — پاسخ‌های تشریحی این دو نفر بیشتر از '
         f'{fa(integrity.SIM_MEDIUM if sim["level"] == "medium" else integrity.SIM_HIGH if sim["level"] == "high" else integrity.SIM_CRITICAL)}٪ مشابه است. '
         'پیش از ثبت نمره، پاسخ‌ها را با هم مقایسه کنید.</div>' if sim["level"] else ''}"""

    return f"""
    <section class="healthcard" id="health">
      <h2 class="health-title">گزارش سلامت آزمون</h2>
      <div class="health-grid">
        <div class="health-cell"><b>{fa_clock(h['duration'])}</b><span>مدت آزمون</span></div>
        <div class="health-cell"><b>{fa(h['answered'])} / {fa(len(QUESTIONS))}</b><span>پاسخ داده‌شده</span></div>
        <div class="health-cell"><b>{fa_clock(h['time_spent'])}</b><span>زمان صرف‌شده روی پاسخ‌ها</span></div>
        <div class="health-cell"><b>{fa(h['tab_switches'])}</b><span>خروج از صفحه</span></div>
        <div class="health-cell"><b>{fa(h['paste'])}</b><span>تلاش چسباندن</span></div>
        <div class="health-cell"><b>{fa(h['copy'])}</b><span>تلاش کپی</span></div>
        <div class="health-cell"><b>{fa(h['relogin'])}</b><span>ورود از دستگاه دیگر</span></div>
        <div class="health-cell"><b>{fa(len(h['fast']))}</b><span>پاسخ شتاب‌زده</span></div>
      </div>
      <ul class="warnlist">{warn_rows}</ul>
      <h3 class="subhead">تشابه پاسخ‌ها</h3>
      {sim_block}
      <details class="qtimes">
        <summary>زمان‌سنجی هر سوال ({fa(len(answers))} پاسخ ثبت‌شده)</summary>
        <div class="table-wrap md"><table class="table compact">
          <thead><tr><th>سوال</th><th>زمان صرف‌شده</th><th>وضعیت</th></tr></thead>
          <tbody>{''.join(q_rows)}</tbody>
        </table></div>
      </details>
    </section>"""


def wrong_answer_note(q, payload):
    """پاسخ غلط یک سوال بسته (چهارگزینه‌ای، تطبیق، درست/غلط) به شکل علامت کوتاه."""
    kind = q["kind"]
    if kind in ("single", "match_one"):
        given = payload.get("choice")
        return f'انتخاب «{given}» ≠ کلید «{q["correct"]}»' if given and given != q["correct"] else ""
    if kind == "multi":
        given = set(payload.get("choices") or [])
        correct = set(q["correct"])
        if not given:
            return "بی‌پاسخ · کلید: " + "، ".join(q["correct"])
        if given == correct:
            return ""
        missing = [x for x in q["correct"] if x not in given]
        extra = [x for x in given if x not in q["correct"]]
        parts = []
        if missing:
            parts.append("جاافتاده: " + "، ".join(missing))
        if extra:
            parts.append("اضافی: " + "، ".join(extra))
        return " · ".join(parts)
    if kind in ("numeric", "numeric_multi"):
        return "پاسخ عددی نادرست" if payload else "بی‌پاسخ"
    if kind == "tf_explain":
        given = payload.get("tf")
        if given is None:
            return "بی‌پاسخ · کلید: " + ("درست" if q["correct"] else "غلط")
        return "" if bool(given) == bool(q["correct"]) else (
            f'تشخیص «{"درست" if given else "غلط"}» ≠ کلید «{"درست" if q["correct"] else "غلط"}»')
    return ""


def wrong_list(answers_by_qid):
    """سوال‌های بسته‌ای که پاسخ غلط خورده‌اند (برای نمایش در صفحهٔ تصحیح)."""
    out = []
    for q in QUESTIONS:
        if not q["auto"]:
            continue
        row = answers_by_qid.get(q["id"])
        if row and (row["auto_score"] or 0) >= q["auto"]:
            continue
        payload = json.loads(row["payload"]) if row else {}
        out.append({"id": q["id"], "topic": q.get("topic", ""),
                    "given": payload.get("choice") or ("، ".join(payload.get("choices") or []) if q["kind"] == "multi" else ""),
                    "correct": q.get("correct"), "note": wrong_answer_note(q, payload)})
    return out


def render_wrong_card(answers_by_qid):
    wrong = wrong_list(answers_by_qid)
    if not wrong:
        return '<div class="wrongcard okcard"><h3>پاسخ‌های نادرست</h3><p>همهٔ سوال‌های بسته درست پاسخ داده شده‌اند.</p></div>'
    items = "".join(
        f'<li><b>{e(w["id"])}</b> <span class="muted small">({e(w["topic"])})</span> — {e(w["note"] or "پاسخ نادرست")}</li>'
        for w in wrong)
    tags = "، ".join(w["id"] for w in wrong)
    return ('<div class="wrongcard"><h3>پاسخ‌های نادرست ({fa(len(wrong))})</h3>'
            f'<p class="muted small">غلط‌ها: <b>{e(tags)}</b></p>'
            f'<ul class="wronglist">{items}</ul></div>')


def render_grader_question(q, payload, row, attempt_id):
    pts_auto = row["auto_score"] if row else None
    auto_txt = f'{fmt(pts_auto)} از {fa(q["auto"])}' if q["auto"] else "—"
    manual_cur = row["manual_score"] if row and row["manual_score"] is not None else None

    # نمایش پاسخ شرکت‌کننده
    view = []
    kind = q["kind"]
    if kind in ("single", "match_one"):
        view.append(f'<p>انتخاب: <b>{e(payload.get("choice") or "بی‌پاسخ")}</b> · کلید: <b>{e(q["correct"])}</b></p>')
    elif kind == "multi":
        view.append(f'<p>انتخاب: <b>{e("، ".join(payload.get("choices") or []) or "بی‌پاسخ")}</b> · کلید: <b>{e("، ".join(q["correct"]))}</b></p>')
    elif kind == "tf_explain":
        tf = payload.get("tf")
        tf_txt = "بی‌پاسخ" if tf is None else ("درست" if tf else "غلط")
        view.append(f'<p>تشخیص: <b>{tf_txt}</b> · کلید: <b>{"درست" if q["correct"] else "غلط"}</b></p>')
        view.append(f'<div class="answerbox">{e(payload.get("explain") or "—")}</div>')
    elif kind == "match":
        m = payload.get("matches") or {}
        view.append("<ul class='plain'>" + "".join(
            f'<li>{e(p["left"])} → <b>{e(m.get(p["id"]) or "—")}</b></li>' for p in q["pairs"]) + "</ul>")
    elif kind == "numeric":
        f = q["fields"][0]
        view.append(f'<p>پاسخ: <b>{e(payload.get(f["key"]) or "—")}</b> · مقدار درست: <b>{fmt(f["value"])}</b></p>')
        if payload.get("work"):
            view.append(f'<div class="answerbox small">مسیر: {e(payload["work"])}</div>')
    elif kind == "numeric_multi":
        for f in q.get("fields", []):
            view.append(f'<p>{e(f["label"])}: <b>{e(payload.get(f["key"]) or "—")}</b> · درست: <b>{fmt(f["value"])}</b></p>')
        c = q["conclusion"]
        chosen = payload.get("conclusion")
        ctext = next((o["text"] for o in c["options"] if o["key"] == chosen), "بی‌پاسخ")
        view.append(f'<p>نتیجه‌گیری: <b>{e(ctext)}</b></p>')
        if payload.get("work"):
            view.append(f'<div class="answerbox small">مسیر: {e(payload["work"])}</div>')
    elif kind == "structured":
        if q.get("claims"):
            view.append(f'<p>ادعاهای انتخاب‌شده: <b>{e("، ".join(payload.get("claims") or []) or "—")}</b></p>')
        for f in q.get("fields", []):
            view.append(f'<div class="fieldview"><span>{e(f["label"])}</span><div class="answerbox">{e(payload.get(f["key"]) or "—")}</div></div>')
        if q.get("claims"):
            view.append(f'<div class="fieldview"><span>نام خطا و اصلاح</span><div class="answerbox">{e(payload.get("notes") or "—")}</div></div>')
    elif kind == "text":
        view.append(f'<div class="answerbox">{e(payload.get("text") or "—")}</div>')

    rubric = ""
    if q["manual"]:
        controls = []
        for c in q["rubric"]:
            val = None
            if row and row["manual_json"]:
                try:
                    vals = json.loads(row["manual_json"])
                    val = vals.get(c["key"])
                except (json.JSONDecodeError, TypeError):
                    val = None
            opts = [f'<option value="{i}" {"selected" if val == i else ""}>{fa(i)}</option>' for i in range(0, c["max"] + 1)]
            controls.append(f"""<div class="rubric-row">
              <div class="rubric-name">{e(c['name'])} <span class="muted small">(حداکثر {fa(c['max'])})</span></div>
              <select class="rubric-select" data-qid="{q['id']}" data-key="{e(c['key'])}">
                <option value="">—</option>{''.join(opts)}
              </select>
              <div class="rubric-guide">{e(c.get('guide',''))}</div>
            </div>""")
        model = MODEL_ANSWERS.get(q["id"])
        rubric = f"""
        <div class="rubric">
          <div class="rubric-head">روبریک تصحیح · بارم دستی: {fa(q['manual'])}</div>
          {''.join(controls)}
          {f'<details class="model"><summary>پاسخ مرجع نمونه</summary><div>{e(model)}</div></details>' if model else ''}
          <button class="btn primary save-score" data-qid="{q['id']}" data-max="{q['manual']}">ثبت نمرهٔ این سوال</button>
          <span class="saved-flag" id="flag-{q['id']}">{'ثبت‌شده: ' + fmt(manual_cur) if manual_cur is not None else 'ثبت نشده'}</span>
        </div>"""

    return f"""<div class="gq" id="gq-{q['id']}">
      <div class="qhead"><span class="qbadge">{e(q['id'])}</span>
        <span class="pts">خودکار: {auto_txt} · دستی: {fa(q['manual'])}</span></div>
      <div class="stem">{q['stem']}</div>
      <div class="given">{''.join(view)}</div>
      {rubric}
    </div>"""


# ------------------------------------------------------------------ CSV
def _csv_num(n):
    """عدد با ارقام لاتین برای بازشدن درست در اکسل"""
    try:
        n = round(float(n), 2)
    except (TypeError, ValueError):
        return ""
    return str(int(n)) if abs(n - round(n)) < 1e-9 else f"{n:.2f}"


def export_rows(conn):
    manual_qids = [q["id"] for q in QUESTIONS if q["manual"] > 0]
    ph = ",".join("?" * len(manual_qids))
    header = ["نام", "نام کاربری", "شروع", "ارسال", "نمرهٔ خودکار"] + [q["id"] for q in QUESTIONS] + \
             ["نمرهٔ دستی", "نمرهٔ کل", "بخش E", "نتیجه",
              "بیشترین تشابه٪", "مشابه با", "تشابه میانگین٪", "سطح هشدار",
              "خروج از صفحه", "تلاش چسباندن", "تلاش کپی", "ورود از دستگاه دیگر"]
    rows = [header]
    sims = similarity_for(conn)
    attempts = conn.execute("SELECT a.*, u.display_name, u.username FROM attempts a JOIN users u ON u.id=a.user_id ORDER BY a.started_at").fetchall()
    for a in attempts:
        if not a["submitted_at"]:
            continue
        ans = {r["qid"]: r for r in conn.execute("SELECT * FROM answers WHERE attempt_id=?", (a["id"],))}
        auto_by = {}
        manual_by = {}
        cells = []
        for q in QUESTIONS:
            r = ans.get(q["id"])
            if not r:
                cells.append("")
                continue
            if q["auto"]:
                auto_by[q["section"]] = auto_by.get(q["section"], 0) + (r["auto_score"] or 0)
                auto_part = _csv_num(r["auto_score"] or 0)
                if q["manual"]:
                    cells.append(f"{auto_part}+{_csv_num(r['manual_score'] or 0)}/{q['points']}")
                else:
                    cells.append(f"{auto_part}/{q['points']}")
            else:
                manual_by[q["id"]] = r["manual_score"] or 0
                cells.append(f"{_csv_num(r['manual_score']) if r['manual_score'] is not None else 'در انتظار'}/{q['points']}")
        sec = grading.section_totals(auto_by, manual_by)
        rows.append([a["display_name"], a["username"],
                     time.strftime("%Y-%m-%d %H:%M", time.localtime(a["started_at"])),
                     time.strftime("%Y-%m-%d %H:%M", time.localtime(a["submitted_at"])),
                     a["auto_score"], *cells, a["manual_score"], a["total_score"], sec.get("E", 0),
                     "قبول" if a["passed"] else "رد",
                     *sim_cells(conn, a, sims)])
    return rows


def sim_cells(conn, attempt_row, sims):
    """چهار ستون تشابه و چهار ستون سلامت برای CSV."""
    sim = sims.get(attempt_row["id"], {})
    h = attempt_health(conn, attempt_row)
    return [
        _csv_num(sim.get("max") or 0) if sim.get("with") else "",
        sim.get("with", ""),
        _csv_num(sim.get("avg") or 0) if sim.get("with") else "",
        integrity.LEVEL_LABEL.get(sim.get("level", ""), "سالم"),
        h["tab_switches"], h["paste"], h["copy"], h["relogin"],
    ]


def export_raw_rows(conn):
    rows = [["نام کاربری", "سوال", "پاسخ خام", "نمرهٔ خودکار", "نمرهٔ دستی"]]
    attempts = conn.execute("SELECT a.id, u.username FROM attempts a JOIN users u ON u.id=a.user_id WHERE a.submitted_at IS NOT NULL ORDER BY a.started_at").fetchall()
    for a in attempts:
        ans = conn.execute("SELECT * FROM answers WHERE attempt_id=? ORDER BY qid", (a["id"],)).fetchall()
        for r in ans:
            payload = json.loads(r["payload"])
            readable = " | ".join(f"{k}: {v}" for k, v in payload.items() if v not in (None, "", [], {}))
            rows.append([a["username"], r["qid"], readable,
                         r["auto_score"] if r["auto_score"] is not None else "",
                         r["manual_score"] if r["manual_score"] is not None else ""])
    return rows


def csv_bytes(rows):
    buf = io.StringIO()
    buf.write("﻿")
    w = csv.writer(buf)
    w.writerows(rows)
    return buf.getvalue().encode("utf-8")


# ------------------------------------------------------------------ scoring helpers
def recompute_attempt(conn, attempt_id):
    attempt = conn.execute("SELECT * FROM attempts WHERE id=?", (attempt_id,)).fetchone()
    rows = conn.execute("SELECT * FROM answers WHERE attempt_id=?", (attempt_id,)).fetchall()
    auto_by = {}
    manual_by = {}
    auto_sum = 0.0
    for r in rows:
        q = QUESTIONS_BY_ID.get(r["qid"])
        if not q:
            continue
        if q["auto"]:
            s = r["auto_score"] or 0
            auto_by[q["section"]] = auto_by.get(q["section"], 0) + s
            auto_sum += s
        if q["manual"]:
            manual_by[r["qid"]] = r["manual_score"] or 0
    manual_sum = sum(manual_by.values())
    total = auto_sum + manual_sum
    sections = grading.section_totals(auto_by, manual_by)
    # اگر هنوز بخش دستی تصحیح نشده، نتیجهٔ قبولی قطعی نیست
    all_graded = True
    for q in QUESTIONS:
        if q["manual"]:
            r = next((x for x in rows if x["qid"] == q["id"]), None)
            if r is None or r["manual_score"] is None:
                all_graded = False
                break
    passed = (1 if grading.is_passed(total, sections) else 0) if all_graded else None
    conn.execute("UPDATE attempts SET auto_score=?, manual_score=?, total_score=?, passed=? WHERE id=?",
                 (auto_sum, manual_sum, total, passed, attempt_id))
    conn.commit()
    attempt = conn.execute("SELECT * FROM attempts WHERE id=?", (attempt_id,)).fetchone()
    return attempt, sections, not all_graded


# ------------------------------------------------------------------ handler
class Handler(BaseHTTPRequestHandler):
    server_version = "VazhebanExam/1.0"

    def log_message(self, fmt_s, *args):
        sys.stderr.write("%s - %s\n" % (self.address_string(), fmt_s % args))

    # ---------- low level
    def send_html(self, html, status=200, cookie=None):
        data = html.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        if cookie:
            self.send_header("Set-Cookie", cookie)
        self.end_headers()
        self.wfile.write(data)

    def send_json(self, obj, status=200):
        data = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def send_file(self, data, ctype, filename=None):
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        if filename:
            self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
        self.end_headers()
        self.wfile.write(data)

    def redirect(self, path, cookie=None):
        self.send_response(303)
        self.send_header("Location", path)
        if cookie:
            self.send_header("Set-Cookie", cookie)
        self.end_headers()

    def read_body(self):
        length = int(self.headers.get("Content-Length") or 0)
        return self.rfile.read(length) if length else b""

    def read_json(self):
        raw = self.read_body()
        if not raw:
            return {}
        try:
            return json.loads(raw.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            return {}

    def current_user(self, conn):
        return db.session_user(conn, cookie_value(self, "vb_session"))

    # ---------- dispatch
    def safe_route(self, route, conn):
        try:
            auto_submit_expired(conn)
            route(conn)
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception:  # noqa: BLE001 — یک خطای گذرا نباید صفحهٔ خام بدهد
            import traceback
            traceback.print_exc()
            try:
                self.send_html(render_error(self.current_user(conn), 500), 500)
            except Exception:  # noqa: BLE001
                pass

    def do_GET(self):
        conn = db.connect()
        try:
            self.safe_route(self.route_get, conn)
        finally:
            conn.close()

    def do_POST(self):
        conn = db.connect()
        try:
            self.safe_route(self.route_post, conn)
        finally:
            conn.close()

    def route_get(self, conn):
        path = urlparse(self.path).path
        user = self.current_user(conn)
        page.current_path = path

        if path == "/sw.js":
            fp = os.path.join(STATIC, "sw.js")
            with open(fp, "rb") as f:
                data = f.read()
            self.send_response(200)
            self.send_header("Content-Type", "application/javascript; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Service-Worker-Allowed", "/")
            self.end_headers()
            self.wfile.write(data)
            return

        if path == "/offline":
            with open(os.path.join(STATIC, "offline.html"), "rb") as f:
                self.send_file(f.read(), "text/html; charset=utf-8")
            return

        if path.startswith("/static/"):
            rel = path[len("/static/"):]
            name = os.path.basename(rel)
            fp = os.path.join(STATIC, rel) if "/" in rel else os.path.join(STATIC, name)
            if not os.path.abspath(fp).startswith(os.path.abspath(STATIC)):
                fp = ""
            if os.path.isfile(fp):
                ext = name.rsplit(".", 1)[-1]
                ctype = {"css": "text/css; charset=utf-8",
                         "js": "application/javascript; charset=utf-8",
                         "html": "text/html; charset=utf-8",
                         "webmanifest": "application/manifest+json; charset=utf-8",
                         "png": "image/png",
                         "svg": "image/svg+xml",
                         "woff2": "font/woff2"}.get(ext, "application/octet-stream")
                with open(fp, "rb") as f:
                    self.send_file(f.read(), ctype)
            else:
                self.send_html(render_error(self.current_user(conn), 404), 404)
            return

        if path == "/login":
            self.send_html(render_login(conn))
            return
        if path == "/logout":
            token = cookie_value(self, "vb_session")
            if token:
                row = db.session_user(conn, token)
                if row:
                    db.log_audit(conn, row["id"], "logout", "خروج از حساب", client_ip(self), detect_device(self))
                db.delete_session(conn, token)
            self.redirect("/login", "vb_session=; Path=/; Max-Age=0")
            return
        if path == "/":
            if not user:
                self.redirect("/login")
                return
            self.redirect("/admin" if user["role"] == "admin"
                          else ("/grader" if user["role"] == "grader" else "/exam"))
            return
        if path == "/health":
            self.send_json({"ok": True})
            return

        if not user:
            self.redirect("/login")
            return

        if path == "/guide" and user["role"] == "participant":
            attempt = conn.execute("SELECT * FROM attempts WHERE user_id=?", (user["id"],)).fetchone()
            if attempt:
                self.redirect("/exam")
                return
            self.send_html(render_intro(user))
            return

        if path == "/exam":
            attempt = conn.execute("SELECT * FROM attempts WHERE user_id=?", (user["id"],)).fetchone()
            if attempt and attempt["submitted_at"]:
                attempt, sections, pending = recompute_attempt(conn, attempt["id"])
                self.send_html(render_result(user, attempt, sections, pending))
                return
            if not attempt:
                self.send_html(render_intro(user))
                return
            answers = {}
            for r in conn.execute("SELECT * FROM answers WHERE attempt_id=?", (attempt["id"],)):
                answers[r["qid"]] = json.loads(r["payload"])
            page.current_path = "/exam"
            conn.execute("UPDATE attempts SET last_seen=? WHERE id=?", (int(time.time()), attempt["id"]))
            conn.commit()
            self.send_html(render_exam(user, attempt, answers))
            return

        m = re.match(r"^/report/(\d+)$", path)
        if m:
            row = conn.execute("SELECT a.*, u.display_name AS owner, u.username AS owner_username FROM attempts a JOIN users u ON u.id=a.user_id WHERE a.id=?",
                               (int(m.group(1)),)).fetchone()
            allowed = row and row["submitted_at"] and (user["role"] in ("grader", "admin") or row["user_id"] == user["id"])
            if not allowed:
                self.send_html(render_error(user, 404, "کارنامه‌ای برای این تلاش موجود نیست."), 404)
                return
            html = reportcard.render_report(conn, row, row["owner"])
            if urlparse(self.path).query.find("download=1") >= 0:
                data = html.encode("utf-8")
                name = re.sub(r"[^A-Za-z0-9_.-]", "_", row["owner_username"] or "report")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(data)))
                self.send_header("Content-Disposition", f'attachment; filename="vazheban-report-{name}.html"')
                self.end_headers()
                self.wfile.write(data)
            else:
                self.send_html(html)
            return

        if path == "/exam/time":
            attempt = conn.execute("SELECT * FROM attempts WHERE user_id=? AND submitted_at IS NULL", (user["id"],)).fetchone()
            if not attempt:
                self.send_json({"active": False})
            else:
                conn.execute("UPDATE attempts SET last_seen=? WHERE id=?", (int(time.time()), attempt["id"]))
                conn.commit()
                self.send_json({"active": True, "remaining": attempt["deadline"] - int(time.time())})
            return

        if path == "/admin" and user["role"] == "admin":
            self.send_html(render_admin(user, conn))
            return

        if path == "/admin/live" and user["role"] == "admin":
            self.send_html(render_live(user, conn))
            return

        if path == "/grader" and user["role"] in ("grader", "admin"):
            self.send_html(render_grader(user, conn))
            return

        m = re.match(r"^/grader/attempt/(\d+)$", path)
        if m and user["role"] in ("grader", "admin"):
            html = render_grader_attempt(user, conn, int(m.group(1)))
            if html is None:
                self.send_html(render_error(user, 404, "این تلاش در سامانه ثبت نشده است."), 404)
            else:
                self.send_html(html)
            return

        m = re.match(r"^/grader/attempt/(\d+)/(next|prev)$", path)
        if m and user["role"] in ("grader", "admin"):
            cur = int(m.group(1))
            direction = ">" if m.group(2) == "next" else "<"
            row = conn.execute(
                f"SELECT id FROM attempts WHERE submitted_at IS NOT NULL AND id {direction} ? "
                f"ORDER BY id {'ASC' if direction == '>' else 'DESC'} LIMIT 1", (cur,)).fetchone()
            self.redirect(f"/grader/attempt/{row['id']}" if row else f"/grader/attempt/{cur}")
            return

        if path == "/grader/export.csv" and user["role"] in ("grader", "admin"):
            self.send_file(csv_bytes(export_rows(conn)), "text/csv; charset=utf-8", "vazheban-results.csv")
            return
        if path == "/grader/export-answers.csv" and user["role"] in ("grader", "admin"):
            self.send_file(csv_bytes(export_raw_rows(conn)), "text/csv; charset=utf-8", "vazheban-answers.csv")
            return

        self.send_html(render_error(user, 404), 404)

    def route_post(self, conn):
        path = urlparse(self.path).path
        user = self.current_user(conn)

        if path == "/login":
            form = parse_qs(self.read_body().decode("utf-8"))
            username = (form.get("username") or [""])[0].strip()
            password = (form.get("password") or [""])[0]
            row = db.get_user_by_username(conn, username)
            if row and row["active"] and db.verify_password(password, row["password_hash"], row["salt"]):
                token = db.create_session(conn, row["id"], days=2)
                # هر کاربر فقط روی یک دستگاه: نشست‌های قبلی بسته می‌شوند
                if db.close_other_sessions(conn, row["id"], token) and row["role"] == "participant":
                    attempt = conn.execute(
                        "SELECT id FROM attempts WHERE user_id=? AND submitted_at IS NULL", (row["id"],)).fetchone()
                    if attempt:
                        db.log_event(conn, attempt["id"], "relogin", "ورود از دستگاه دیگر")
                db.log_audit(conn, row["id"], "login", "ورود موفق", client_ip(self), detect_device(self))
                home = "/admin" if row["role"] == "admin" else ("/grader" if row["role"] == "grader" else "/exam")
                self.redirect(home, f"vb_session={token}; Path=/; HttpOnly; Secure; SameSite=Lax; Max-Age=172800")
            else:
                if username:
                    db.log_audit(conn, row["id"] if row else None, "login_failed",
                                 f"تلاش ناموفق: {username}", client_ip(self), detect_device(self))
                self.send_html(render_login(conn, error="نام کاربری یا رمز عبور نادرست است."), 401)
            return

        if not user:
            self.send_json({"error": "unauthenticated"}, 401)
            return

        if path == "/admin/create-user" and user["role"] == "admin":
            form = parse_qs(self.read_body().decode("utf-8"))
            username = (form.get("username") or [""])[0].strip()
            name = (form.get("display_name") or [""])[0].strip()
            pw = (form.get("password") or [""])[0]
            if not re.match(r"^[A-Za-z0-9_.-]{3,32}$", username) or not name or len(pw) < 3:
                self.send_html(render_admin(user, conn, error="اطلاعات ناقص یا نام کاربری نامعتبر است."), 400)
                return
            if db.get_user_by_username(conn, username):
                self.send_html(render_admin(user, conn, error="این نام کاربری قبلاً وجود دارد."), 400)
                return
            db.create_user(conn, username, name, pw, "participant")
            db.log_audit(conn, user["id"], "admin_create_user", f"ساخت کاربر {username}",
                         client_ip(self), detect_device(self))
            self.send_html(render_admin(user, conn, notice=f"کاربر «{username}» ساخته شد."))
            return

        if path == "/admin/reset-password" and user["role"] == "admin":
            form = parse_qs(self.read_body().decode("utf-8"))
            try:
                uid = int((form.get("user_id") or ["0"])[0])
            except ValueError:
                uid = 0
            pw = (form.get("password") or [""])[0]
            target = db.get_user(conn, uid)
            if not target or len(pw) < 3:
                self.send_html(render_admin(user, conn, error="کاربر پیدا نشد یا رمز کوتاه است."), 400)
                return
            db.set_password(conn, uid, pw)
            conn.execute("DELETE FROM sessions WHERE user_id=?", (uid,))
            conn.commit()
            db.log_audit(conn, user["id"], "admin_reset_password", f"تغییر رمز {target['username']}",
                         client_ip(self), detect_device(self))
            self.send_html(render_admin(user, conn, notice=f"رمز «{target['username']}» تغییر کرد."))
            return

        if path == "/admin/reset-attempt" and user["role"] == "admin":
            form = parse_qs(self.read_body().decode("utf-8"))
            try:
                uid = int((form.get("user_id") or ["0"])[0])
            except ValueError:
                uid = 0
            target = db.get_user(conn, uid)
            if not target or target["role"] != "participant":
                self.send_html(render_admin(user, conn, error="فقط تلاش شرکت‌کننده قابل بازنشانی است."), 400)
                return
            old = conn.execute("SELECT id FROM attempts WHERE user_id=?", (uid,)).fetchone()
            if old:
                conn.execute("DELETE FROM answers WHERE attempt_id=?", (old["id"],))
                conn.execute("DELETE FROM events WHERE attempt_id=?", (old["id"],))
                conn.execute("DELETE FROM attempts WHERE id=?", (old["id"],))
                conn.commit()
            db.log_audit(conn, user["id"], "admin_reset_attempt", f"بازنشانی تلاش {target['username']}",
                         client_ip(self), detect_device(self))
            self.send_html(render_admin(user, conn, notice=f"تلاش «{target['username']}» پاک شد؛ می‌تواند دوباره آزمون بدهد."))
            return

        if path == "/exam/start":
            if user["role"] != "participant":
                self.redirect("/grader")
                return
            existing = conn.execute("SELECT * FROM attempts WHERE user_id=?", (user["id"],)).fetchone()
            if not existing:
                now = int(time.time())
                seed = secrets.randbelow(1_000_000)
                order = order_for(seed, user["username"])
                device = detect_device(self)
                conn.execute(
                    "INSERT INTO attempts (user_id, exam_version, started_at, deadline, status, seed, order_json, "
                    "ip, device, last_seen) VALUES (?,?,?,?,?,?,?,?,?,?)",
                    (user["id"], VERSION, now, now + DURATION, "in_progress", seed,
                     json.dumps(order, ensure_ascii=False), client_ip(self), device, now))
                conn.commit()
                attempt = conn.execute("SELECT * FROM attempts WHERE user_id=?", (user["id"],)).fetchone()
                db.log_event(conn, attempt["id"], "start", device)
                db.log_audit(conn, user["id"], "exam_start", "شروع آزمون", client_ip(self), device)
            self.redirect("/exam")
            return

        if path == "/api/answer":
            attempt = conn.execute("SELECT * FROM attempts WHERE user_id=? AND submitted_at IS NULL",
                                   (user["id"],)).fetchone()
            if not attempt:
                self.send_json({"error": "no_active_attempt"}, 403)
                return
            body = self.read_json()
            qid = body.get("qid")
            payload = body.get("payload")
            q = QUESTIONS_BY_ID.get(qid)
            if not q or not isinstance(payload, dict):
                self.send_json({"error": "bad_request"}, 400)
                return
            if int(time.time()) > attempt["deadline"] + 10:
                self.send_json({"error": "time_over"}, 403)
                return
            auto = grading.grade_auto(q, payload) if q["auto"] else None
            now = int(time.time())
            conn.execute("UPDATE attempts SET last_seen=? WHERE id=?", (now, attempt["id"]))
            existing = conn.execute("SELECT * FROM answers WHERE attempt_id=? AND qid=?",
                                    (attempt["id"], qid)).fetchone()
            # زمان صرف‌شده: از اولین پاسخ تا آخرین ویرایش روی همین سوال
            first_at = (existing["first_at"] or existing["updated_at"]) if existing else now
            if existing and existing["first_at"] is None:
                first_at = existing["updated_at"]
            time_spent = max(0, now - int(first_at)) if existing else 0
            if existing:
                conn.execute(
                    "UPDATE answers SET payload=?, auto_score=?, updated_at=?, first_at=?, time_spent=? "
                    "WHERE attempt_id=? AND qid=?",
                    (json.dumps(payload, ensure_ascii=False), auto, now, first_at, time_spent,
                     attempt["id"], qid))
            else:
                conn.execute(
                    "INSERT INTO answers (attempt_id, qid, payload, auto_score, updated_at, first_at, time_spent) "
                    "VALUES (?,?,?,?,?,?,?)",
                    (attempt["id"], qid, json.dumps(payload, ensure_ascii=False), auto, now, now, 0))
            conn.commit()
            remain = attempt["deadline"] - now
            keys = integrity.min_char_fields(q)
            text_len = sum(len(str(payload.get(k) or "").strip()) for k in keys)
            need = integrity.MIN_TEXT_CHARS if keys else 0
            self.send_json({"ok": True, "remaining": remain, "auto": auto,
                            "chars": text_len, "min_chars": need, "short": text_len < need})
            return

        if path == "/api/event":
            attempt = conn.execute("SELECT * FROM attempts WHERE user_id=? AND submitted_at IS NULL",
                                   (user["id"],)).fetchone()
            body = self.read_json()
            kind = str(body.get("kind") or "")
            if kind not in ALLOWED_EVENTS or not attempt:
                self.send_json({"ok": True})   # رخداد بی‌اثر؛ آزمون را متوقف نمی‌کند
                return
            detail = str(body.get("detail") or "")[:200]
            db.log_event(conn, attempt["id"], kind, detail)
            self.send_json({"ok": True})
            return

        if path == "/api/submit":
            attempt = conn.execute("SELECT * FROM attempts WHERE user_id=? AND submitted_at IS NULL",
                                   (user["id"],)).fetchone()
            if not attempt:
                self.redirect("/exam")
                return
            body = self.read_json()
            # ارسال دستی با پاسخ‌های کوتاه مسدود است؛ ارسال خودکار پایان زمان نه
            if not body.get("auto"):
                answers = {r["qid"]: json.loads(r["payload"])
                           for r in conn.execute("SELECT qid, payload FROM answers WHERE attempt_id=?",
                                                 (attempt["id"],))}
                short = integrity.short_questions(QUESTIONS, answers)
                if short:
                    self.send_json({"error": "short_answers",
                                    "min_chars": integrity.MIN_TEXT_CHARS,
                                    "short": short[:10]}, 400)
                    return
            conn.execute("UPDATE attempts SET submitted_at=?, status='submitted' WHERE id=?",
                         (int(time.time()), attempt["id"]))
            conn.commit()
            db.log_event(conn, attempt["id"], "submit")
            db.log_audit(conn, user["id"], "exam_submit", "ارسال آزمون", client_ip(self), detect_device(self))
            recompute_attempt(conn, attempt["id"])
            self.send_json({"ok": True, "redirect": "/exam"})
            return

        if path == "/api/score" and user["role"] in ("grader", "admin"):
            body = self.read_json()
            attempt_id = int(body.get("attempt_id") or 0)
            qid = body.get("qid")
            scores = body.get("scores") or {}
            q = QUESTIONS_BY_ID.get(qid)
            if not q or not q["manual"]:
                self.send_json({"error": "bad_question"}, 400)
                return
            total = 0.0
            clean = {}
            for c in q["rubric"]:
                try:
                    v = float(scores.get(c["key"]))
                except (TypeError, ValueError):
                    self.send_json({"error": f"missing:{c['key']}"}, 400)
                    return
                v = max(0.0, min(float(c["max"]), v))
                clean[c["key"]] = v
                total += v
            now = int(time.time())
            existing = conn.execute("SELECT * FROM answers WHERE attempt_id=? AND qid=?", (attempt_id, qid)).fetchone()
            if not existing:
                conn.execute("INSERT INTO answers (attempt_id, qid, payload, auto_score, manual_score, manual_json, scorer_id, scored_at, updated_at) "
                             "VALUES (?,?,'{}',0,?,?,?,?,?)",
                             (attempt_id, qid, total, json.dumps(clean, ensure_ascii=False), user["id"], now, now))
            else:
                conn.execute("UPDATE answers SET manual_score=?, manual_json=?, scorer_id=?, scored_at=? WHERE attempt_id=? AND qid=?",
                             (total, json.dumps(clean, ensure_ascii=False), user["id"], now, attempt_id, qid))
            conn.commit()
            attempt, sections, pending = recompute_attempt(conn, attempt_id)
            self.send_json({"ok": True, "total": total, "attempt_total": attempt["total_score"],
                            "manual_score": attempt["manual_score"], "pending": pending,
                            "passed": attempt["passed"]})
            return

        self.send_json({"error": "not_found"}, 404)


def sweeper(stop, interval=20):
    """حتی وقتی کسی به سرور وصل نیست، تلاش‌های منقضی را می‌بندد."""
    while not stop.wait(interval):
        try:
            conn = db.connect()
            try:
                auto_submit_expired(conn)
            finally:
                conn.close()
        except Exception as exc:  # noqa: BLE001 — سرویس نباید به‌خاطر یک خطای گذرا بخوابد
            sys.stderr.write(f"auto-submit sweep failed: {exc}\n")


def main():
    port = int(os.environ.get("PORT", "8090"))
    db.init_db()
    httpd = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    sys.stderr.write(f"vazheban exam listening on 127.0.0.1:{port}\n")
    stop = threading.Event()
    threading.Thread(target=sweeper, args=(stop,), daemon=True).start()
    try:
        httpd.serve_forever()
    finally:
        stop.set()


if __name__ == "__main__":
    main()
