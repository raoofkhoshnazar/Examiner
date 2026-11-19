# -*- coding: utf-8 -*-
"""کارنامهٔ کیفی قابل دانلود: قوت، ضعف، تسلط و راهنمای بهبود."""
import time

import grading
from exam_data import QUESTIONS, SECTIONS

FA_DIGITS = str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹")


def e(text):
    return (str(text if text is not None else "").replace("&", "&amp;")
            .replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;"))


def fa(n):
    return str(n).translate(FA_DIGITS)


def fmt(n):
    try:
        if abs(n - round(n)) < 1e-9:
            return fa(f"{int(round(n)):,}".replace(",", "٬"))
        return fa(f"{n:,.2f}".replace(",", "٬"))
    except (TypeError, ValueError):
        return fa(0)


TOPIC_GUIDE = {
    "value proposition": ("ارزش پیشنهادی", "تمرین کنید در یک جمله بگویید مشتری چه دردی دارد و شما چه جایگزین بهتری می‌دهید؛ ارزش پیشنهادی باید قابل اندازه‌گیری باشد، نه شعار."),
    "customer problem": ("مسئلهٔ مشتری", "برای دو محصول دلخواه، «درد» را از «راه‌حل» جدا بنویسید و بگویید چرا این درد هزینه‌بر است."),
    "customer problem / درد": ("مسئلهٔ مشتری", "درد را با شاهد (رفتار یا هزینهٔ فعلی مشتری) توصیف کنید، نه با حدس."),
    "user / customer / buyer": ("کاربر، مشتری و خریدار", "برای یک کیس آشنا، سه نقش را جدا کنید و بگویید تصمیم خرید دست کیست."),
    "cac / ltv": ("CAC و LTV", "نسبت LTV به CAC را برای یک مثال عددی حساب کنید و بگویید چه زمانی کسب‌وکار هنوز زیان‌ده است."),
    "break-even": ("نقطهٔ سربه‌سر", "فرمول را با اعداد واقعی تمرین کنید: هزینهٔ ثابت ÷ (قیمت − هزینهٔ متغیر)."),
    "tam – sam – som": ("اندازهٔ بازار", "بازار را از بالا و از پایین یک بار حساب کنید و اختلاف را توضیح دهید."),
    "segmentation": ("بخش‌بندی", "یک بازار را به سه بخش با معیار روشن تقسیم کنید و بگویید چرا یک بخش را انتخاب می‌کنید."),
    "idea validation": ("اعتبارسنجی ایده", "بین «نظر پرسیدن» و «آزمون رفتار» فرق بگذارید؛ معیار موفقیت را از قبل تعیین کنید."),
    "سود / ltv-cac": ("سود و نسبت LTV/CAC", "هزینهٔ جذب را در برابر ارزش عمر مشتری بگذارید و اثر ریزش را روی نتیجه ببینید."),
    "ltv / ریزش": ("LTV و ریزش", "با نرخ ریزش مشخص، عمر متوسط مشتری و LTV را حساب کنید."),
    "tam": ("اندازهٔ بازار", "TAM را با منبع و فرض روشن بنویسید؛ عدد بدون فرض ارزش تحلیلی ندارد."),
    "4p / stp / رقیب و جایگزین": ("آمیختهٔ بازاریابی و رقابت", "برای یک برند آشنا 4P را بنویسید و رقیب مستقیم را از جایگزین (مثلاً «هیچ کاری نکردن») جدا کنید."),
    "cac": ("هزینهٔ جذب مشتری", "CAC را در دو کانال مختلف حساب و مقایسه کنید."),
    "ltv / واحد اقتصادی": ("واحد اقتصادی", "سود هر مشتری را در یک دوره حساب کنید و بگویید چه زمانی سرمایه برمی‌گردد."),
    "مسئله و درد": ("مسئله و درد", "درد را از زبان مشتری بنویسید و با یک شاهد واقعی پشتیبانی کنید."),
    "رقیب و جایگزین": ("رقبا و جایگزین‌ها", "فهرست رقبا را با جایگزین‌های غیرمستقیم کامل کنید و مزیت واقعی خود را بگویید."),
    "تصمیم یکپارچه (saas، بخش‌بندی، قیمت)": ("تصمیم یکپارچه", "تصمیم را با داده، بخش هدف و اثر قیمت روی سود توجیه کنید؛ توصیه بدون عدد ضعیف است."),
    "persona / target audience": ("پرسونا و مخاطب", "پرسونا را با ویژگی‌های قابل‌سنجش (نقش، بودجه، انگیزه، مانع) بنویسید."),
    "tam / ltv-cac / تحقیق بازار": ("تحلیل بازار و اقتصاد واحد", "برای هر ادعا یک منبع یا محاسبه بیاورید و تناقض‌های تحلیل را بررسی کنید."),
    "business model canvas": ("بوم مدل کسب‌وکار", "بوم را کامل کنید و بگویید کدام خانه ضعیف‌ترین فرض کل مدل است."),
}

SECTION_ADVICE = {
    "A": "مبانی واژگان کسب‌وکار را با یک درس کوتاه و چند تمرین چهارگزینه‌ای مرور کنید.",
    "B": "پاسخ چندگزینه‌ای را با معیار «همهٔ گزینه‌های درست» تمرین کنید؛ یک گزینهٔ ناقص هم نمره می‌گیرد.",
    "C": "برای هر گزاره، دلیل درست یا غلط بودن را در یک جمله بنویسید؛ فقط علامت زدن کافی نیست.",
    "D": "مفاهیم هم‌خانواده (4P، STP، رقیب/جایگزین) را در یک جدول کنار هم بگذارید.",
    "E": "محاسبات CAC، LTV و سربه‌سر را با اعداد واقعی و ماشین‌حساب تمرین کنید.",
    "F": "پاسخ تشریحی را با ساختار «درد ← شاهد ← راه‌حل ← معیار موفقیت» بنویسید.",
    "G": "تصمیم را در قالب «گزینه‌ها، معیار، انتخاب، ریسک» بنویسید و همیشه عدد بیاورید.",
    "H": "پرسونا را از داده و مشاهده بسازید، نه از حدس؛ ویژگی‌ها باید قابل‌سنجش باشند.",
    "I": "استدلال را با جدا کردن «فرض»، «شاهد» و «نتیجه» نقد کنید.",
    "J": "بوم کسب‌وکار را برای یک کسب‌وکار واقعی کامل کنید و ضعیف‌ترین خانه را مشخص کنید.",
}


def _pct(score, points):
    return round(score / points * 100) if points else 0


def _topic_key(topic):
    return (topic or "").strip().lower()


def build_report(conn, attempt, questions=QUESTIONS, sections=SECTIONS):
    """داده‌های کارنامه: تسلط، قوت، ضعف، احتمال نفهمیدن، راهنمای بهبود."""
    answers = {r["qid"]: r for r in conn.execute(
        "SELECT * FROM answers WHERE attempt_id=?", (attempt["id"],))}
    auto_by, manual_by = {}, {}
    for qid, row in answers.items():
        q = next((x for x in questions if x["id"] == qid), None)
        if not q:
            continue
        if q["auto"]:
            auto_by[q["section"]] = auto_by.get(q["section"], 0) + (row["auto_score"] or 0)
        if q["manual"]:
            manual_by[qid] = row["manual_score"] or 0
    sec_score = grading.section_totals(auto_by, manual_by)
    rows, mastered, strong, weak, unclear = [], [], [], [], []
    for s in sections:
        got = float(sec_score.get(s["id"], 0))
        pct = _pct(got, s["points"])
        rows.append({"id": s["id"], "title": s["title"], "score": got,
                     "points": s["points"], "pct": pct})
        if pct >= 75:
            mastered.append(s)
        elif pct >= 50:
            strong.append(s)
        elif pct >= 25:
            weak.append(s)
        else:
            unclear.append(s)

    topic_stats = {}
    for q in questions:
        row = answers.get(q["id"])
        if not row:
            continue
        auto = float(row["auto_score"] or 0)
        manual = row["manual_score"]
        if q["manual"] and manual is None:
            continue
        earned = auto + float(manual or 0)
        full = q["auto"] + q["manual"]
        entry = topic_stats.setdefault(_topic_key(q["topic"]),
                                       {"topic": q["topic"], "earned": 0.0, "full": 0.0})
        entry["earned"] += earned
        entry["full"] += full

    good_topics, weak_topics = [], []
    for key, st in topic_stats.items():
        pct = _pct(st["earned"], st["full"])
        item = dict(st, pct=pct)
        if pct >= 75:
            good_topics.append(item)
        elif pct < 50:
            weak_topics.append(item)
    good_topics.sort(key=lambda x: -x["pct"])
    weak_topics.sort(key=lambda x: x["pct"])

    advice = []
    for s in unclear + weak:
        advice.append({"title": s["title"], "text": SECTION_ADVICE.get(s["id"], "")})
    topic_advice = []
    for st in weak_topics:
        g = TOPIC_GUIDE.get(_topic_key(st["topic"]))
        if g:
            topic_advice.append({"label": g[0], "text": g[1], "pct": st["pct"]})

    if not weak_topics and not unclear:
        plan = ["تمایل شما در همهٔ مباحث بالای حد قبولی است؛ برای تعمیق، یکی از مباحث قوی را به یک تحلیل واقعی روی یک کسب‌وکار تبدیل کنید.",
                "پاسخ‌های تشریحی خود را یک بار دیگر بخوانید و برای هر ادعا یک عدد یا شاهد اضافه کنید."]
    else:
        plan = ["اول مباحثی را مرور کنید که نمرهٔ زیر ۵۰٪ گرفته‌اید؛ همان‌ها بیشترین اثر را روی نمرهٔ کل دارند.",
                "برای هر مبحث ضعیف، یک مثال واقعی با عدد بنویسید و آن را با پاسخ مرجع مقایسه کنید.",
                "روی پاسخ‌های تشریحی، ساختار چهاربخشی «درد ← شاهد ← راه‌حل ← معیار موفقیت» را تمرین کنید."]
        if any(r["id"] == "E" and r["pct"] < 60 for r in rows):
            plan.insert(0, "بخش محاسبه (CAC، LTV، سربه‌سر) شرط حداقلی قبولی دارد؛ تمرین عددی را جدی بگیرید.")
        if any(r["id"] == "J" for r in rows) and any(r["id"] == "J" and r["pct"] < 50 for r in rows):
            plan.append("بوم مدل کسب‌وکار را یک بار کامل برای یک کسب‌وکار آشنا پر کنید تا ارتباط خانه‌ها را ببینید.")

    return {"rows": rows, "mastered": mastered, "strong": strong, "weak": weak,
            "unclear": unclear, "good_topics": good_topics, "weak_topics": weak_topics,
            "advice": advice, "topic_advice": topic_advice, "plan": plan}


REPORT_CSS = """
body{margin:0;background:#f5f7f8;color:#23282f;font-family:Tahoma,'Vazirmatn',sans-serif;direction:rtl}
.wrap{max-width:820px;margin:0 auto;padding:32px 20px}
.sheet{background:#fff;border:1px solid #e3e7ec;border-radius:14px;padding:34px 30px}
.brand{display:flex;justify-content:space-between;align-items:baseline;border-bottom:2px solid #dc4c46;padding-bottom:12px;margin-bottom:22px}
.brand b{font-size:22px;color:#dc4c46}.brand span{font-size:12px;color:#73859f}
h1{font-size:24px;margin:0 0 4px}h2{font-size:16px;margin:26px 0 10px;color:#dc4c46}
.meta{color:#73859f;font-size:12.5px;margin-bottom:18px}
.hero{display:flex;gap:22px;align-items:center;background:#f7f9fa;border:1px solid #e3e7ec;border-radius:12px;padding:18px 20px}
.hero .num{font-size:40px;font-weight:bold;color:#dc4c46;line-height:1}
.hero .num small{font-size:13px;color:#73859f;font-weight:normal}
.hero .v{font-size:15px}
table{width:100%;border-collapse:collapse;font-size:13px;margin-top:6px}
th,td{padding:7px 9px;border-bottom:1px solid #e8ecf0;text-align:right}
th{background:#f7f9fa;color:#73859f;font-weight:normal;font-size:12px}
.tag{display:inline-block;padding:2px 9px;border-radius:20px;font-size:11.5px}
.good{background:#e9f3ee;color:#1f6b57}.mid{background:#fdf4e3;color:#8a5a12}.low{background:#fdeceb;color:#c0392b}
ul{margin:6px 0 0;padding-inline-start:18px}li{margin:5px 0;font-size:13px;line-height:1.9}
.two{display:grid;grid-template-columns:1fr 1fr;gap:18px}
.tblwrap{width:100%;overflow-x:auto}
.tblwrap table{min-width:100%}
body{overflow-x:clip;overflow-y:auto;overflow-wrap:break-word}
.hero{flex-wrap:wrap}
li,td,th,.meta{overflow-wrap:anywhere}
.note{font-size:12px;color:#73859f;margin-top:20px;border-top:1px dashed #e3e7ec;padding-top:12px}
.actions{text-align:center;margin:18px 0}
.actions a{display:inline-block;background:#dc4c46;color:#fff;text-decoration:none;padding:10px 20px;border-radius:10px;font-size:13px}
@media print{body{background:#fff}.actions{display:none}.sheet{border:none;padding:0}}
@media (max-width:640px){.two{grid-template-columns:1fr}.sheet{padding:20px 14px}.wrap{padding:16px 10px}
  .hero{padding:14px}.hero .num{font-size:34px}.tblwrap table{min-width:420px}table{font-size:12.5px}th,td{padding:6px 7px}}
@media (max-width:400px){.hero .num{font-size:30px}.sheet{padding:16px 11px}.tblwrap table{min-width:380px}}
"""


def render_report(conn, attempt, owner_name, download=False, questions=QUESTIONS, sections=SECTIONS):
    rep = build_report(conn, attempt, questions, sections)
    total = attempt["total_score"] or 0
    verdict = "قبول" if attempt["passed"] else ("قبول مشروط" if attempt["passed"] is None else "نیازمند تلاش بیشتر")

    sec_rows = "".join(
        f"<tr><td>{e(r['title'])}</td><td>{fmt(r['score'])} / {fa(r['points'])}</td>"
        f"<td>{fa(r['pct'])}٪</td>"
        f"<td><span class=\"tag {'good' if r['pct'] >= 75 else ('mid' if r['pct'] >= 50 else 'low')}\">"
        f"{'مسلط' if r['pct'] >= 75 else ('قابل قبول' if r['pct'] >= 50 else 'نیازمند مرور')}</span></td></tr>"
        for r in rep["rows"])

    good = "".join(f"<li>{e(t['topic'])} <span class=\"tag good\">{fa(t['pct'])}٪</span></li>"
                   for t in rep["good_topics"]) or "<li>در سطح مبحث، تسلط روشنی ثبت نشده است.</li>"
    weak = "".join(f"<li>{e(t['topic'])} <span class=\"tag low\">{fa(t['pct'])}٪</span></li>"
                   for t in rep["weak_topics"]) or "<li>مبحث ضعیف مشخصی پیدا نشد.</li>"
    unclear_items = "".join(f"<li>{e(s['title'])}</li>" for s in rep["unclear"]) or "<li>مبحثی با احتمال عدم درک پیدا نشد.</li>"
    read_more = "".join(f"<li><b>{e(a['title'])}:</b> {e(a['text'])}</li>" for a in rep["advice"]) or "<li>نیاز به مرور بخش مشخصی دیده نشد.</li>"
    topic_more = "".join(f"<li><b>{e(a['label'])}:</b> {e(a['text'])}</li>" for a in rep["topic_advice"])
    plan = "".join(f"<li>{e(p)}</li>" for p in rep["plan"])
    date = time.strftime("%Y-%m-%d", time.localtime(attempt["submitted_at"] or time.time()))

    html = f"""<!doctype html>
<html lang="fa" dir="rtl"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>کارنامهٔ آزمون — {e(owner_name)}</title><style>{REPORT_CSS}</style></head>
<body><div class="wrap"><div class="sheet">
  <div class="brand"><b>واژه‌بان</b><span>کارنامهٔ ارزیابی · مؤسسهٔ سرخ</span></div>
  <h1>کارنامهٔ آزمون کیس‌محور</h1>
  <div class="meta">{e(owner_name)} · تاریخ ارسال {fa(date)} · {'ارسال خودکار پس از پایان زمان' if attempt['status'] == 'expired' else 'ارسال دستی'}</div>
  <div class="hero">
    <div class="num">{fmt(total)}<small> از ۱۰۰</small></div>
    <div class="v"><b>{e(verdict)}</b><br>
      <span style="color:#73859f;font-size:12.5px">خودکار {fmt(attempt['auto_score'] or 0)} · تشریحی {fmt(attempt['manual_score'] or 0)}</span></div>
  </div>
  {'' if attempt['passed'] is not None else '<p class="note">بخش‌های تشریحی هنوز کامل تصحیح نشده‌اند؛ نتیجهٔ قبولی پس از تصحیح قطعی می‌شود.</p>'}

  <h2>نتیجه به تفکیک بخش</h2>
  <div class="tblwrap"><table><thead><tr><th>بخش</th><th>نمره</th><th>درصد</th><th>وضعیت</th></tr></thead><tbody>{sec_rows}</tbody></table></div>

  <div class="two">
    <div><h2>مباحثی که مسلط شده‌اید</h2><ul>{good}</ul></div>
    <div><h2>مباحثی که باید بیشتر بخوانید</h2><ul>{weak}</ul></div>
  </div>

  <h2>احتمالاً به‌طور کامل متوجه نشده‌اید</h2>
  <ul>{unclear_items}</ul>

  <h2>چه چیزی را مرور کنید</h2>
  <ul>{read_more}</ul>
  {f'<h2>راهنمای مبحثی</h2><ul>{topic_more}</ul>' if topic_more else ''}

  <h2>برنامهٔ بهبود</h2>
  <ul>{plan}</ul>

  <p class="note">این کارنامه ارزیابی کیفی بر پایهٔ نمرهٔ هر بخش و مبحث است، نه قضاوت دربارهٔ توانایی کلی. هدفش این است که بدانید کجا محکم هستید و کدام مبحث را باید یک بار دیگر بخوانید.</p>
</div>
<div class="actions"><a href="javascript:window.print()">چاپ یا ذخیره به PDF</a></div>
</div></body></html>"""
    return html
