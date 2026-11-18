# -*- coding: utf-8 -*-
"""موتور نمره‌دهی — بخش‌های خودکار بر اساس کلید سند"""
from exam_data import QUESTIONS_BY_ID, SECTION_POINTS


def _num(value):
    """پذیرش عدد فارسی/لاتین با جداکنندهٔ هزارگان"""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    s = str(value).strip()
    if not s:
        return None
    fa = "۰۱۲۳۴۵۶۷۸۹"
    ar = "٠١٢٣٤٥٦٧٨٩"
    out = []
    for ch in s:
        if ch in fa:
            out.append(str(fa.index(ch)))
        elif ch in ar:
            out.append(str(ar.index(ch)))
        elif ch in ",٬، ":
            continue
        elif ch in ".-":
            out.append("." if ch == "." else ch)
        elif ch.isdigit():
            out.append(ch)
        else:
            out.append(ch)
    t = "".join(out).replace("٫", ".")
    try:
        return float(t)
    except ValueError:
        return None


def grade_auto(q, payload):
    """نمرهٔ بخش خودکار یک سوال. payload شکل دیکشنری دارد."""
    kind = q["kind"]
    payload = payload or {}
    if kind == "single":
        return float(q["points"]) if payload.get("choice") == q["correct"] else 0.0

    if kind == "multi":
        sel = set(payload.get("choices") or [])
        correct = set(q["correct"])
        if not sel:
            return 0.0
        if sel == correct:
            return float(q["points"])
        partial = q.get("partial") or {}
        for rule, pts in partial.items():
            need = int(rule.split("of")[0])
            if len(sel) == need and sel.issubset(correct):
                return float(pts)
        return 0.0

    if kind == "tf_explain":
        val = payload.get("tf")
        if val is None or val == "":
            return 0.0
        return float(q["auto"]) if bool(val) == bool(q["correct"]) else 0.0

    if kind == "match_one":
        return float(q["points"]) if payload.get("choice") == q["correct"] else 0.0

    if kind == "match":
        assignments = payload.get("matches") or {}
        score = 0.0
        for pair in q["pairs"]:
            if assignments.get(pair["id"]) == pair["correct"]:
                score += 1.0
        return score

    if kind == "numeric":
        field = q["fields"][0]
        got = _num(payload.get(field["key"]))
        if got is None:
            return 0.0
        target = float(field["value"])
        tol = float(field.get("tolerance", 0.02)) * target
        return float(q["points"]) if abs(got - target) <= tol else 0.0

    if kind == "numeric_multi":
        score = 0.0
        for field in q["fields"]:
            got = _num(payload.get(field["key"]))
            if got is None:
                continue
            target = float(field["value"])
            tol = float(field.get("tolerance", 0.02)) * target
            if abs(got - target) <= tol:
                score += 2.0
        concl = q.get("conclusion")
        if concl and payload.get("conclusion") == concl["correct"]:
            score += 1.0
        return min(score, float(q["points"]))

    return 0.0  # text / structured → دستی


def auto_total(answers_by_qid):
    total = 0.0
    by_section = {}
    for q in QUESTIONS_BY_ID.values():
        if q["auto"] == 0:
            continue
        payload = answers_by_qid.get(q["id"], {})
        s = grade_auto(q, payload)
        by_section.setdefault(q["section"], 0.0)
        by_section[q["section"]] += s
        total += s
    return total, by_section


def section_totals(auto_by_section, manual_by_qid):
    """جمع نمرهٔ هر بخش با ترکیب خودکار و دستی"""
    out = {sid: float(auto_by_section.get(sid, 0.0)) for sid in SECTION_POINTS}
    for qid, score in manual_by_qid.items():
        q = QUESTIONS_BY_ID.get(qid)
        if not q:
            continue
        out[q["section"]] = out.get(q["section"], 0.0) + float(score or 0)
    return out


def is_passed(total, section_scores):
    return total >= 65 and section_scores.get("E", 0) >= 6
