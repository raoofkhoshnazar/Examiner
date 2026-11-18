# -*- coding: utf-8 -*-
"""سنجش سلامت آزمون: زمان هر سوال، رخدادهای کپی/پیست و تشابه پاسخ‌ها.

همهٔ محاسبات بدون وابستگی خارجی و روی متن فارسی انجام می‌شود.
"""
import re
import unicodedata

MIN_TEXT_CHARS = 30          # حداقل کاراکتر برای پاسخ‌های تشریحی
FAST_ANSWER_SECONDS = 20     # پاسخی سریع‌تر از این، «شتاب‌زده» شمرده می‌شود

SIM_MEDIUM = 70
SIM_HIGH = 80
SIM_CRITICAL = 90

_DIACRITICS = re.compile("[ً-ْٰـ]")
_NON_WORD = re.compile(r"[^\w؀-ۿ]+")
_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")


# ---------------------------------------------------------------- متن پاسخ
def text_fields(q):
    """نام فیلدهای متنی هر سوال (برای حداقل کاراکتر و سنجش تشابه)."""
    kind = q["kind"]
    if kind == "text":
        return ["text"]
    if kind == "tf_explain":
        return ["explain"]
    if kind == "structured":
        keys = [f["key"] for f in q.get("fields", [])]
        if q.get("claims"):
            keys.append("notes")
        return keys
    if kind in ("numeric", "numeric_multi"):
        return ["work"]
    return []


def min_char_fields(q):
    """سوال‌هایی که پاسخ آزادشان حداقل ۳۰ کاراکتر لازم دارد.

    فیلدهای کوتاه ساختاریافته (پرسونا، بوم، سناریو) از این قاعده مستثنا هستند؛
    پاسخ‌های تشریحی واقعی، تصحیح درست/غلط و نقد استدلال مشمول‌اند.
    """
    kind = q["kind"]
    if kind in ("text", "tf_explain"):
        return text_fields(q)
    if kind == "structured" and q.get("claims"):
        return ["notes"]
    return []


def answer_text(q, payload):
    """متن آزاد نوشته‌شده در یک سوال."""
    parts = []
    for key in text_fields(q):
        value = (payload or {}).get(key)
        if isinstance(value, str):
            parts.append(value.strip())
    return " ".join(p for p in parts if p)


def text_length(q, payload):
    return len(answer_text(q, payload))


def short_questions(questions, answers):
    """سوال‌هایی که پاسخ متنی‌شان کمتر از حد مجاز است.

    `answers` نگاشت qid → payload (dict).
    """
    out = []
    for q in questions:
        keys = min_char_fields(q)
        if not keys:
            continue
        payload = answers.get(q["id"]) or {}
        length = sum(len(str(payload.get(k) or "").strip()) for k in keys)
        if length < MIN_TEXT_CHARS:
            out.append({"id": q["id"], "length": length})
    return out


# ---------------------------------------------------------------- تشابه
def normalize(text):
    """یکسان‌سازی فارسی/عربی و حذف نشانه‌ها برای مقایسهٔ منصفانه."""
    if not text:
        return ""
    text = unicodedata.normalize("NFKC", str(text)).translate(_DIGITS)
    text = text.replace("ي", "ی").replace("ك", "ک").replace("ۀ", "ه").replace("أ", "ا").replace("إ", "ا")
    text = text.replace("‌", "").replace("‏", "").replace("‎", "")
    text = _DIACRITICS.sub("", text)
    text = text.lower()
    text = _NON_WORD.sub(" ", text)
    return " ".join(text.split())


def shingles(text, size=4):
    """مجموعهٔ n-گرام کاراکتری از متن یکسان‌شده (بدون فاصله)."""
    compact = normalize(text).replace(" ", "")
    if len(compact) <= size:
        return {compact} if compact else set()
    return {compact[i:i + size] for i in range(len(compact) - size + 1)}


def similarity(a, b):
    """درصد شباهت دو پاسخ (ژاکار روی n-گرام)."""
    sa, sb = shingles(a), shingles(b)
    if not sa or not sb:
        return 0.0
    inter = len(sa & sb)
    union = len(sa | sb)
    return round(inter / union * 100, 1) if union else 0.0


def level(percent):
    """سطح هشدار بر اساس درصد تشابه."""
    if percent > SIM_CRITICAL:
        return "critical"
    if percent > SIM_HIGH:
        return "high"
    if percent > SIM_MEDIUM:
        return "medium"
    return ""


LEVEL_LABEL = {
    "medium": "اخطار سطح متوسط",
    "high": "اخطار سطح بالا",
    "critical": "اخطار سطح بحرانی",
}


def similarity_matrix(participants, questions):
    """ماتریس تشابه پاسخ‌های تشریحی بین شرکت‌کنندگان.

    participants: فهرست dict با کلیدهای id, name, texts={qid: str}
    return: {id: {"max": pct, "with": name, "avg": pct, "level": ...}}
    """
    qids = [q["id"] for q in questions if text_fields(q)]
    result = {p["id"]: {"max": 0.0, "with": "", "avg": 0.0, "level": "", "pairs": 0} for p in participants}

    def profile(p):
        return {qid: p["texts"].get(qid, "") for qid in qids if len(p["texts"].get(qid, "").strip()) >= 20}

    profiles = {p["id"]: profile(p) for p in participants}
    for i, a in enumerate(participants):
        pa = profiles[a["id"]]
        if not pa:
            continue
        scores = []
        for b in participants[i + 1:]:
            pb = profiles[b["id"]]
            shared = [qid for qid in pa if qid in pb]
            if not shared:
                continue
            pair = sum(similarity(pa[qid], pb[qid]) for qid in shared) / len(shared)
            pair = round(pair, 1)
            scores.append(pair)
            for mine, other, name in ((a, b, b["name"]), (b, a, a["name"])):
                info = result[mine["id"]]
                if pair > info["max"]:
                    info["max"] = pair
                    info["with"] = name
        if scores:
            info = result[a["id"]]
            info["avg"] = round(sum(scores) / len(scores), 1)
            info["pairs"] = len(scores)
    for info in result.values():
        info["level"] = level(info["max"])
    return result


# ---------------------------------------------------------------- سلامت
def health(attempt, answers, events):
    """خلاصهٔ سلامت یک تلاش.

    attempt: ردیف attempts
    answers: نگاشت qid → ردیف answers
    events: فهرست ردیف‌های events
    """
    kinds = {}
    for ev in events:
        kinds[ev["kind"]] = kinds.get(ev["kind"], 0) + 1

    answered = len(answers)
    spent = sum(int(r["time_spent"] or 0) for r in answers.values())
    timed = [(qid, int(r["time_spent"] or 0)) for qid, r in answers.items() if (r["time_spent"] or 0) > 0]
    fast = [qid for qid, secs in timed if secs < FAST_ANSWER_SECONDS]
    fastest = min(timed, key=lambda x: x[1]) if timed else None

    end = attempt["submitted_at"] or attempt["deadline"]
    return {
        "answered": answered,
        "time_spent": spent,
        "fast": fast,
        "fastest": fastest,
        "duration": max(0, int(end) - int(attempt["started_at"])),
        "tab_switches": kinds.get("blur", 0),
        "paste": kinds.get("paste", 0),
        "copy": kinds.get("copy", 0),
        "relogin": kinds.get("relogin", 0),
    }


def flags(h, similarity_info):
    """فهرست هشدارهای قابل نمایش برای یک نفر."""
    out = []
    if h["paste"]:
        out.append(("warn", f"{h['paste']} بار تلاش برای چسباندن متن (مسدود شد)"))
    if h["copy"]:
        out.append(("warn", f"{h['copy']} بار تلاش برای کپی متن (مسدود شد)"))
    if h["tab_switches"] >= 5:
        out.append(("warn", f"{h['tab_switches']} بار خروج از صفحهٔ آزمون"))
    elif h["tab_switches"]:
        out.append(("info", f"{h['tab_switches']} بار خروج از صفحهٔ آزمون"))
    if h["fast"]:
        out.append(("info", f"{len(h['fast'])} پاسخ در کمتر از {FAST_ANSWER_SECONDS} ثانیه"))
    if h["relogin"]:
        out.append(("warn", f"{h['relogin']} بار ورود دوباره از دستگاه دیگر"))
    if similarity_info and similarity_info.get("level"):
        out.append((similarity_info["level"],
                    f"{LEVEL_LABEL[similarity_info['level']]} — "
                    f"{similarity_info['max']}٪ تشابه با {similarity_info['with']}"))
    return out
