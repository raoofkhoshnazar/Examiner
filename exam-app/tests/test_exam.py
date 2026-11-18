# -*- coding: utf-8 -*-
"""تست موتور نمره‌دهی، منطق قبولی و جریان ذخیره/تصحیح.

اجرا:  python3 -m unittest tests.test_exam -v   (از پوشهٔ exam-app)
یا:   python3 tests/test_exam.py
"""
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

TMP = tempfile.mkdtemp(prefix="vazheban-test-")
os.environ["VAZHEBAN_DB"] = os.path.join(TMP, "test.db")

import db  # noqa: E402
import grading  # noqa: E402
from exam_data import QUESTIONS, QUESTIONS_BY_ID, TOTAL_POINTS  # noqa: E402


class TestExamContent(unittest.TestCase):
    def test_total_points_is_100(self):
        self.assertEqual(TOTAL_POINTS, 100)
        self.assertEqual(sum(q["points"] for q in QUESTIONS), 100)

    def test_twenty_five_questions_in_ten_sections(self):
        self.assertEqual(len(QUESTIONS), 25)
        self.assertEqual(len({q["section"] for q in QUESTIONS}), 10)

    def test_auto_plus_manual_equals_points(self):
        for q in QUESTIONS:
            self.assertEqual(q["auto"] + q["manual"], q["points"], q["id"])


class TestGrading(unittest.TestCase):
    def test_single_correct_and_wrong(self):
        q = QUESTIONS_BY_ID["A1"]
        self.assertEqual(grading.grade_auto(q, {"choice": "ب"}), 3)
        self.assertEqual(grading.grade_auto(q, {"choice": "الف"}), 0)

    def test_multi_all_or_partial(self):
        q = QUESTIONS_BY_ID["B1"]
        self.assertEqual(grading.grade_auto(q, {"choices": ["الف", "ب", "د", "ه"]}), 6)
        self.assertEqual(grading.grade_auto(q, {"choices": ["الف", "ب", "د"]}), 3)
        # سه درست + یک نادرست → صفر
        self.assertEqual(grading.grade_auto(q, {"choices": ["الف", "ب", "د", "ج"]}), 0)
        self.assertEqual(grading.grade_auto(q, {"choices": ["الف", "ب"]}), 0)

    def test_truefalse_two_points(self):
        self.assertEqual(grading.grade_auto(QUESTIONS_BY_ID["C1"], {"tf": False}), 2)
        self.assertEqual(grading.grade_auto(QUESTIONS_BY_ID["C1"], {"tf": True}), 0)
        self.assertEqual(grading.grade_auto(QUESTIONS_BY_ID["C2"], {"tf": True}), 2)

    def test_match_five_points(self):
        for qid, correct in (("D1", "ب"), ("D2", "د"), ("D3", "الف"), ("D4", "ه"), ("D5", "ج")):
            q = QUESTIONS_BY_ID[qid]
            self.assertEqual(q["points"], 1)
            self.assertEqual(grading.grade_auto(q, {"choice": correct}), 1, qid)
            wrong = "ج" if correct != "ج" else "و"
            self.assertEqual(grading.grade_auto(q, {"choice": wrong}), 0, qid)

    def test_cac_exact(self):
        q = QUESTIONS_BY_ID["E1"]
        self.assertEqual(grading.grade_auto(q, {"cac": "۳٬۰۰۰٬۰۰۰"}), 5)
        self.assertEqual(grading.grade_auto(q, {"cac": "3000000"}), 5)
        self.assertEqual(grading.grade_auto(q, {"cac": "3,000,000"}), 5)
        self.assertEqual(grading.grade_auto(q, {"cac": "قابل محاسبه نیست"}), 0)

    def test_ltv_and_conclusion(self):
        q = QUESTIONS_BY_ID["E2"]
        payload = {"ltv_a": "۲۱۰۰۰۰۰۰", "ltv_c": "۲۸۳۵۰۰۰", "conclusion": "1"}
        self.assertEqual(grading.grade_auto(q, payload), 5)
        # نتیجه‌گیری اشتباه → ۴
        payload["conclusion"] = "2"
        self.assertEqual(grading.grade_auto(q, payload), 4)
        # هر دو عدد اشتباه → ۰
        self.assertEqual(grading.grade_auto(q, {"ltv_a": "1500000", "ltv_c": "900000", "conclusion": "3"}), 0)

    def test_tolerance_two_percent(self):
        q = QUESTIONS_BY_ID["E1"]
        self.assertEqual(grading.grade_auto(q, {"cac": "2950000"}), 5)   # −۱.۷٪
        self.assertEqual(grading.grade_auto(q, {"cac": "2800000"}), 0)   # −۶.۷٪

    def test_manual_questions_get_zero_from_auto(self):
        for q in QUESTIONS:
            if q["auto"] == 0:
                self.assertEqual(grading.grade_auto(q, {"text": "هر چیزی"}), 0, q["id"])

    def test_pass_rule(self):
        sections = {s: 0 for s in "ABCDEFGHIJ"}
        sections["A"] = 24; sections["B"] = 6; sections["C"] = 12
        sections["D"] = 5; sections["E"] = 10; sections["F"] = 16
        sections["G"] = 10; sections["H"] = 5; sections["I"] = 6; sections["J"] = 6
        total = sum(sections.values())
        self.assertTrue(grading.is_passed(total, sections))
        # نمرهٔ کافی ولی محاسبه زیر ۶ → رد
        sections["E"] = 5
        self.assertFalse(grading.is_passed(total - 5, sections))
        # نمرهٔ کل زیر ۶۵ → رد
        sections["E"] = 10
        self.assertFalse(grading.is_passed(60, sections))


class TestFlow(unittest.TestCase):
    """جریان واقعی: کاربر، تلاش، ذخیرهٔ پاسخ، تصحیح دستی، نمرهٔ کل"""

    @classmethod
    def setUpClass(cls):
        db.init_db()
        cls.conn = db.connect()
        cls.uid = db.create_user(cls.conn, "t_sup", "تست پشتیبان", "secret123", "participant")
        cls.gid = db.create_user(cls.conn, "t_grader", "تست مصحح", "grader123", "grader")

    def test_end_to_end_score(self):
        import json as _json
        import time
        conn = self.conn
        now = int(time.time())
        conn.execute(
            "INSERT INTO attempts (user_id, exam_version, started_at, deadline, status, seed, order_json) "
            "VALUES (?,?,?,?,?,?,?)", (self.uid, "2.0", now, now + 2700, "in_progress", 7, "{}"))
        conn.commit()
        aid = conn.execute("SELECT id FROM attempts WHERE user_id=?", (self.uid,)).fetchone()["id"]

        # پاسخ‌های کامل و درست به همهٔ سوال‌های خودکار
        answers = {
            "A1": {"choice": "ب"}, "A2": {"choice": "ج"}, "A3": {"choice": "ب"}, "A4": {"choice": "ج"},
            "A5": {"choice": "ب"}, "A6": {"choice": "الف"}, "A7": {"choice": "ج"}, "A8": {"choice": "ب"},
            "B1": {"choices": ["الف", "ب", "د", "ه"]},
            "C1": {"tf": False, "explain": "خیر"}, "C2": {"tf": True, "explain": "درست"},
            "C3": {"tf": False, "explain": "خیر"},
            "D1": {"choice": "ب"}, "D2": {"choice": "د"}, "D3": {"choice": "الف"},
            "D4": {"choice": "ه"}, "D5": {"choice": "ج"},
            "E1": {"cac": "3000000"},
            "E2": {"ltv_a": "21000000", "ltv_c": "2835000", "conclusion": "1"},
        }
        for qid, payload in answers.items():
            q = QUESTIONS_BY_ID[qid]
            conn.execute("INSERT INTO answers (attempt_id, qid, payload, auto_score, updated_at) VALUES (?,?,?,?,?)",
                         (aid, qid, _json.dumps(payload), grading.grade_auto(q, payload), now))
        conn.commit()

        import app
        attempt, sections, pending = app.recompute_attempt(conn, aid)
        self.assertEqual(attempt["auto_score"], 51)  # ۲۴ + ۶ + ۶ + ۵ + ۱۰
        self.assertTrue(pending)  # بخش‌های دستی هنوز تصحیح نشده
        self.assertIsNone(attempt["passed"])

        # مصحح همهٔ سوال‌های دستی را نمرهٔ کامل می‌دهد
        for q in QUESTIONS:
            if q["manual"]:
                manual = {c["key"]: c["max"] for c in q["rubric"]}
                total = sum(manual.values())
                self.assertEqual(total, q["manual"], q["id"])
                existing = conn.execute(
                    "SELECT 1 FROM answers WHERE attempt_id=? AND qid=?", (aid, q["id"])).fetchone()
                if existing:
                    conn.execute(
                        "UPDATE answers SET manual_score=?, manual_json=? WHERE attempt_id=? AND qid=?",
                        (total, _json.dumps(manual), aid, q["id"]))
                else:
                    conn.execute(
                        "INSERT INTO answers (attempt_id, qid, payload, auto_score, manual_score, manual_json, updated_at) "
                        "VALUES (?,?,'{}',0,?,?,?)",
                        (aid, q["id"], total, _json.dumps(manual), now))
        conn.execute("UPDATE attempts SET submitted_at=? WHERE id=?", (now, aid))
        conn.commit()

        attempt, sections, pending = app.recompute_attempt(conn, aid)
        self.assertFalse(pending)
        self.assertEqual(attempt["total_score"], 100)
        self.assertEqual(attempt["passed"], 1)
        self.assertEqual(sections["E"], 10)

    def test_partial_manual_blocks_final_verdict(self):
        import app
        conn = self.conn
        attempt, sections, pending = app.recompute_attempt(
            conn, conn.execute("SELECT id FROM attempts WHERE user_id=?", (self.uid,)).fetchone()["id"])
        # بعد از حذف یک نمرهٔ دستی، نتیجه نباید قبول قطعی بماند
        conn.execute("UPDATE answers SET manual_score=NULL WHERE attempt_id=? AND qid='F1'", (attempt["id"],))
        conn.commit()
        attempt, sections, pending = app.recompute_attempt(conn, attempt["id"])
        self.assertTrue(pending)
        self.assertIsNone(attempt["passed"])

    def test_export_rows(self):
        import app
        rows = app.export_rows(self.conn)
        self.assertEqual(rows[0][0], "نام")
        self.assertGreaterEqual(len(rows), 2)
        raw = app.export_raw_rows(self.conn)
        self.assertGreater(len(raw), 1)

    @classmethod
    def tearDownClass(cls):
        cls.conn.close()
        shutil.rmtree(TMP, ignore_errors=True)


class TestIntegrity(unittest.TestCase):
    def test_min_characters_rule(self):
        import integrity
        q = QUESTIONS_BY_ID["F1"]                     # تشریحی کوتاه
        self.assertTrue(integrity.text_fields(q))
        short = {"text": "خوب است"}
        long = {"text": "مسئلهٔ اصلی تیم پشتیبانی این است که " * 2}
        self.assertLess(integrity.text_length(q, short), integrity.MIN_TEXT_CHARS)
        self.assertGreaterEqual(integrity.text_length(q, long), integrity.MIN_TEXT_CHARS)
        short_ids = [x["id"] for x in integrity.short_questions(QUESTIONS, {"F1": short})]
        self.assertIn("F1", short_ids)
        self.assertNotIn("A1", short_ids)             # سوال گزینه‌ای حداقل کاراکتر ندارد

    def test_choice_questions_need_no_text(self):
        import integrity
        self.assertEqual(integrity.text_fields(QUESTIONS_BY_ID["A1"]), [])
        self.assertFalse(integrity.short_questions([QUESTIONS_BY_ID["A1"]], {}))

    def test_normalize_persian(self):
        import integrity
        self.assertEqual(integrity.normalize("كيک ۱۰۰٪"), integrity.normalize("کیک 100٪"))
        self.assertEqual(integrity.normalize("می‌رود"), "میرود")

    def test_similarity_levels(self):
        import integrity
        identical = "ریزش سگمنت C به دلیل نبود پیگیری مدرس بین جلسه‌ها بالاست و باید داشبورد پیگیری اضافه شود."
        self.assertGreaterEqual(integrity.similarity(identical, identical), 99)
        self.assertLess(integrity.similarity(identical, "پاسخ کاملاً متفاوت دربارهٔ قیمت و تبلیغات است."), 30)

        self.assertEqual(integrity.level(75), "medium")
        self.assertEqual(integrity.level(85), "high")
        self.assertEqual(integrity.level(95), "critical")
        self.assertEqual(integrity.level(40), "")

    def test_similarity_matrix_flags_pair(self):
        import integrity
        same = "پاسخ یکسان و طولانی دربارهٔ ریزش مشتری و داشبورد پیگیری مدرس که هر دو نفر نوشته‌اند." * 2
        other = "متن کاملاً بی‌ربط دربارهٔ سربه‌سر و حاشیهٔ سود با اعداد متفاوت و استدلال دیگر." * 2
        participants = [
            {"id": 1, "name": "الف", "texts": {"F1": same}},
            {"id": 2, "name": "ب", "texts": {"F1": same}},
            {"id": 3, "name": "ج", "texts": {"F1": other}},
        ]
        sims = integrity.similarity_matrix(participants, QUESTIONS)
        self.assertEqual(sims[1]["with"], "ب")
        self.assertGreaterEqual(sims[1]["max"], 90)
        self.assertEqual(sims[1]["level"], "critical")
        self.assertEqual(sims[3]["level"], "")


if __name__ == "__main__":
    unittest.main(verbosity=2)
