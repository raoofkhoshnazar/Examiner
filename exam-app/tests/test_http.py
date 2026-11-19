# -*- coding: utf-8 -*-
"""تست انتها-به-انتها روی HTTP: ورود، آزمون، ذخیره، ارسال، تصحیح، خروجی CSV.

سرور را در پورت آزمایشی بالا می‌آورد و پس از تست می‌بندد.
اجرا:  python3 tests/test_http.py
"""
import http.cookiejar
import json
import os
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.error
import urllib.parse
import urllib.request

APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if APP_DIR not in sys.path:
    sys.path.insert(0, APP_DIR)
TMP = tempfile.mkdtemp(prefix="vazheban-http-")
DB_PATH = os.path.join(TMP, "exam.db")
os.environ["VAZHEBAN_DB"] = DB_PATH


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


class _LoopbackPolicy(http.cookiejar.DefaultCookiePolicy):
    def return_ok_secure(self, cookie, request):
        return True


class Client:
    def __init__(self, base):
        self.base = base
        # کوکی نشست در سرور Secure است؛ در تست HTTP محلی آن را منتقل می‌کنیم
        self.jar = http.cookiejar.CookieJar(policy=_LoopbackPolicy())
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.jar))

    def get(self, path):
        return self.opener.open(self.base + path, timeout=15)

    def post(self, path, data=None, raw=None):
        if raw is None:
            raw = urllib.parse.urlencode(data or {}).encode()
        req = urllib.request.Request(self.base + path, data=raw, method="POST")
        req.add_header("Content-Type", "application/json" if data is None else "application/x-www-form-urlencoded")
        return self.opener.open(req, timeout=15)

    def get_text(self, path):
        with self.get(path) as r:
            return r.status, r.read().decode("utf-8")

    def post_text(self, path, data=None):
        with self.post(path, data) as r:
            return r.status, r.read().decode("utf-8")


class TestHTTP(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.port = free_port()
        env = dict(os.environ, VAZHEBAN_DB=DB_PATH, PORT=str(cls.port))
        env["PYTHONPATH"] = APP_DIR
        # ساخت کاربران آزمایشی
        subprocess.run([sys.executable, "manage.py", "create-users", "--participants", "3",
                        "--grader", "t_grader", "--grader-password", "graderpass"],
                       cwd=APP_DIR, env=env, check=True, capture_output=True)
        subprocess.run([sys.executable, "manage.py", "upsert-user", "t_admin",
                        "--password", "adminpass", "--name", "مدیر آزمون", "--role", "admin"],
                       cwd=APP_DIR, env=env, check=True, capture_output=True)
        cls.env = env
        cls.proc = subprocess.Popen([sys.executable, "app.py"], cwd=APP_DIR, env=env,
                                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        cls.base = f"http://127.0.0.1:{cls.port}"
        for _ in range(80):
            try:
                with urllib.request.urlopen(cls.base + "/health", timeout=1) as r:
                    if r.status == 200:
                        break
            except Exception:
                time.sleep(0.1)
        else:
            raise RuntimeError("سرور بالا نیامد")

    @classmethod
    def tearDownClass(cls):
        cls.proc.send_signal(signal.SIGTERM)
        cls.proc.wait(timeout=10)
        shutil.rmtree(TMP, ignore_errors=True)

    def login(self, username, password):
        c = Client(self.base)
        try:
            c.post("/login", {"username": username, "password": password})
        except urllib.error.HTTPError as err:
            self.assertNotEqual(err.code, 401, "ورود ناموفق")
        return c

    def test_01_bad_login(self):
        c = Client(self.base)
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            c.post("/login", {"username": "sup01", "password": "wrong"})
        self.assertEqual(ctx.exception.code, 401)

    def test_02_full_participant_flow(self):
        c = self.login("sup01", self._password("sup01"))
        status, html = c.get_text("/exam")
        self.assertEqual(status, 200)
        self.assertIn("شروع آزمون", html)
        c.post("/exam/start")
        status, html = c.get_text("/exam")
        self.assertEqual(status, 200)
        self.assertIn("کیس واژه‌بان", html)          # پنل کیس کنار سوال
        self.assertIn("۳.۷ جعبهٔ فرمول", html)        # فرمول‌ها داخل کیس
        self.assertIn("/static/exam.js", html)

        answers = {
            "A1": {"choice": "ب"}, "A2": {"choice": "ج"}, "A3": {"choice": "ب"},
            "A4": {"choice": "ج"}, "A5": {"choice": "ب"}, "A6": {"choice": "الف"},
            "A7": {"choice": "ج"}, "A8": {"choice": "ب"},
            "B1": {"choices": ["الف", "ب", "د", "ه"]},
            "C1": {"tf": False, "explain": "سود شرکت به پوشش هزینهٔ ثابت بستگی دارد و حاشیهٔ سود به‌تنهایی کافی نیست."},
            "C2": {"tf": True, "explain": "ماندگاری دو برابر می‌شود و ارزش عمر مشتری هم به همان نسبت بالا می‌رود."},
            "C3": {"tf": False, "explain": "TAM اندازهٔ فرصت بازار است نه سودآوری واقعی شرکت در کوتاه‌مدت."},
            "D1": {"choice": "ب"}, "D2": {"choice": "د"}, "D3": {"choice": "الف"},
            "D4": {"choice": "ه"}, "D5": {"choice": "ج"},
            "E1": {"cac": "۳٬۰۰۰٬۰۰۰", "work": "۶۰۰ میلیون تومان هزینهٔ بازاریابی تقسیم بر ۲۰۰ مشتری جدید = ۳ میلیون تومان"},
            "E2": {"ltv_a": "۲۱۰۰۰۰۰۰", "ltv_c": "۲۸۳۵۰۰۰", "conclusion": "1",
                   "work": "حاشیهٔ سود ۰.۷ ضرب در میانگین ماندگاری ماه برای دو سگمنت محاسبه شد"},
            "F1": {"text": "مسئلهٔ سگمنت C عینی و قابل اندازه‌گیری است اما درد اصلی احساسی و تجربی است "
                          "و با داده‌های فعلی کیس نمی‌توان اندازه‌اش گرفت."},
            "F2": {"text": "زبان‌لند رقیب مستقیم نیست بلکه جایگزین ارزان‌تر است و باید با تمایز تجربه "
                          "و نتیجهٔ یادگیری پاسخ داده شود نه با کاهش قیمت."},
            "G1": {"feature": "قابلیت ۲", "segment": "کاهش C", "price": "نه", "metric": "ریزش زیر ۶٪"},
            "H1": {"situation": "دانشجو", "trigger": "ددلاین", "barriers": "ساعت و شهریه",
                   "success": "پیشرفت رایتینگ", "quote": "ساعت ۱۹ با شیفتم نمی‌خوره"},
            "I1": {"claims": ["2", "4"],
                   "notes": "خطای ترکیبی و بزرگ‌نمایی TAM در استدلال دیده می‌شود؛ باید ادعا با دادهٔ کیس سنجیده شود."},
            "J1": {"segments": "A، B، C", "value": "نمره در زمان کمتر", "channels": "پرفورمنس",
                   "relation": "پشتیبانی چت", "revenue": "اشتراک ماهانه", "resources": "مدرسان",
                   "activities": "کلاس زنده", "partners": "دانشگاه", "costs": "دستمزد مدرس"},
        }
        for qid, payload in answers.items():
            c.post("/api/answer", raw=json.dumps({"qid": qid, "payload": payload}).encode())

        # ذخیره واقعی: صفحه دوباره خوانده شود و پاسخ‌ها برگردند
        _, html = c.get_text("/exam")
        self.assertIn("۳٬۰۰۰٬۰۰۰", html)  # در state ذخیره‌شده
        c.post("/api/submit")
        status, html = c.get_text("/exam")
        self.assertEqual(status, 200)
        self.assertIn("نتیجهٔ آزمون", html)
        self.assertIn("در حال تصحیح", html)

        # تلاش دوم پس از ارسال ممنوع
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            c.post("/api/answer", raw=json.dumps({"qid": "A1", "payload": {"choice": "الف"}}).encode())
        self.assertEqual(ctx.exception.code, 403)
        with c.get("/exam") as r:
            self.assertIn("نتیجهٔ آزمون", r.read().decode("utf-8"))

        # مصحح وارد شود و همهٔ سوال‌های دستی را نمره دهد
        g = self.login("t_grader", "graderpass")
        status, ghtml = g.get_text("/grader")
        self.assertEqual(status, 200)
        self.assertIn("کارشناس پشتیبانی ۰۱", ghtml)
        import re
        m = re.search(r"/grader/attempt/(\d+)", ghtml)
        self.assertIsNotNone(m)
        aid = int(m.group(1))
        status, page = g.get_text(f"/grader/attempt/{aid}")
        self.assertEqual(status, 200)
        self.assertIn("روبریک تصحیح", page)
        self.assertIn("پاسخ مرجع نمونه", page)

        import db as dbmod
        from exam_data import QUESTIONS
        os.environ["VAZHEBAN_DB"] = DB_PATH
        conn = dbmod.connect()
        for q in QUESTIONS:
            if q["manual"]:
                scores = {c_["key"]: c_["max"] for c_ in q["rubric"]}
                g.post("/api/score", raw=json.dumps(
                    {"attempt_id": aid, "qid": q["id"], "scores": scores}).encode())
        row = conn.execute("SELECT total_score, passed FROM attempts WHERE id=?", (aid,)).fetchone()
        conn.close()
        self.assertEqual(row["total_score"], 100)
        self.assertEqual(row["passed"], 1)

        # شرکت‌کننده نتیجهٔ نهایی را ببیند
        _, final = c.get_text("/exam")
        self.assertIn("نتیجهٔ نهایی است", final)
        self.assertIn("قبول", final)

        # خروجی CSV
        with g.get("/grader/export.csv") as r:
            data = r.read().decode("utf-8")
        self.assertIn("نام کاربری", data)
        self.assertIn("sup01", data)
        self.assertIn("100", data)
        with g.get("/grader/export-answers.csv") as r:
            raw = r.read().decode("utf-8")
        self.assertIn("C1", raw)

    def test_03_participant_blocked_from_grader(self):
        c = self.login("sup02", self._password("sup02"))
        try:
            with c.get("/grader") as r:
                body = r.read().decode("utf-8")
                status = r.status
        except urllib.error.HTTPError as err:
            body, status = err.read().decode("utf-8"), err.code
        self.assertNotIn("پنل مصحح", body)
        self.assertEqual(status, 404)

    def test_04_timer_is_serverside(self):
        c = self.login("sup02", self._password("sup02"))
        c.post("/exam/start")
        with c.get("/exam/time") as r:
            data = json.loads(r.read().decode())
        self.assertTrue(data["active"])
        self.assertLessEqual(data["remaining"], 60 * 60)
        self.assertGreater(data["remaining"], 59 * 60)

    def test_05_persian_and_latin_numbers(self):
        c = self.login("sup02", self._password("sup02"))
        r = c.post("/api/answer", raw=json.dumps({"qid": "E1", "payload": {"cac": "3,000,000"}}).encode())
        data = json.loads(r.read().decode())
        self.assertEqual(data["auto"], 5)
        r = c.post("/api/answer", raw=json.dumps({"qid": "E1", "payload": {"cac": "۳۰۰۰۰۰۰"}}).encode())
        data = json.loads(r.read().decode())
        self.assertEqual(data["auto"], 5)

    def _set_attempt_times(self, username, started_ago, deadline_in):
        import sqlite3
        now = int(time.time())
        conn = sqlite3.connect(DB_PATH, timeout=10)
        uid = conn.execute("SELECT id FROM users WHERE username=?", (username,)).fetchone()[0]
        conn.execute("UPDATE attempts SET started_at=?, deadline=? WHERE user_id=? AND submitted_at IS NULL",
                     (now - started_ago, now + deadline_in, uid))
        conn.commit()
        conn.close()

    def test_06_resume_keeps_timer_running(self):
        """قطع اتصال و بازگشت: پاسخ‌ها می‌مانند و زمان از شروع ادامه دارد."""
        c = self.login("sup02", self._password("sup02"))
        c.post("/api/answer", raw=json.dumps({"qid": "A1", "payload": {"choice": "ب"}}).encode())
        self._set_attempt_times("sup02", started_ago=300, deadline_in=3300)
        again = self.login("sup02", self._password("sup02"))   # نشست تازه = برگشتن از قطعی
        status, html = again.get_text("/exam")
        self.assertEqual(status, 200)
        self.assertIn("ادامهٔ آزمون", html)
        self.assertIn('"choice": "ب"', html)                    # پاسخ ذخیره‌شده برگشته
        with again.get("/exam/time") as r:
            data = json.loads(r.read().decode())
        self.assertTrue(data["active"])
        self.assertLessEqual(data["remaining"], 3301)           # زمان متوقف نشده
        self.assertGreater(data["remaining"], 3290)

    def test_07_auto_submit_when_time_is_over(self):
        """پایان زمان: ارسال خودکار، ذخیرهٔ پاسخ‌ها و پیام «وقت تمام شد»."""
        c = self.login("sup02", self._password("sup02"))
        self._set_attempt_times("sup02", started_ago=3600, deadline_in=-5)
        with c.get("/exam/time") as r:
            self.assertFalse(json.loads(r.read().decode())["active"])
        status, html = c.get_text("/exam")
        self.assertEqual(status, 200)
        self.assertIn("وقت آزمون تمام شد", html)
        import sqlite3
        conn = sqlite3.connect(DB_PATH, timeout=10)
        row = conn.execute(
            "SELECT a.status, a.submitted_at FROM attempts a JOIN users u ON u.id=a.user_id "
            "WHERE u.username='sup02'").fetchone()
        ans = conn.execute(
            "SELECT COUNT(*) FROM answers WHERE attempt_id=(SELECT id FROM attempts WHERE user_id="
            "(SELECT id FROM users WHERE username='sup02'))").fetchone()[0]
        conn.close()
        self.assertEqual(row[0], "expired")
        self.assertIsNotNone(row[1])
        self.assertGreaterEqual(ans, 1)                         # پاسخ‌ها پاک نشدند

    def test_08_login_lists_usernames(self):
        with urllib.request.urlopen(self.base + "/login", timeout=10) as r:
            html = r.read().decode("utf-8")
        self.assertIn('<select name="username"', html)
        self.assertIn('<option value="sup01">sup01</option>', html)
        self.assertNotIn('size="6"', html)                      # فهرست بسته است، پس از انتخاب باز می‌شود

    def test_09_short_answers_block_submit(self):
        """پاسخ تشریحی کمتر از ۳۰ کاراکتر مانع ارسال است."""
        c = self.login("sup03", self._password("sup03"))
        c.post("/exam/start")
        c.post("/api/answer", raw=json.dumps({"qid": "A1", "payload": {"choice": "ب"}}).encode())
        c.post("/api/answer", raw=json.dumps({"qid": "F1", "payload": {"text": "کوتاه"}}).encode())
        c.post("/api/event", raw=json.dumps({"kind": "paste", "detail": "F1"}).encode())
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            c.post("/api/submit", raw=b"{}")
        self.assertEqual(ctx.exception.code, 400)
        body = json.loads(ctx.exception.read().decode())
        self.assertEqual(body["error"], "short_answers")
        self.assertIn("F1", [x["id"] for x in body["short"]])
        # با پاسخ بلند، ارسال انجام می‌شود
        long_text = "این پاسخ نمونه دربارهٔ مسئلهٔ اصلی کیس و دلیل آن نوشته شده است تا حداقل کاراکتر رعایت شود."
        for qid, field in (("C1", "explain"), ("C2", "explain"), ("C3", "explain"),
                           ("F1", "text"), ("F2", "text")):
            payload = {field: long_text}
            if qid.startswith("C"):
                payload["tf"] = True
            c.post("/api/answer", raw=json.dumps({"qid": qid, "payload": payload}).encode())
        c.post("/api/answer", raw=json.dumps(
            {"qid": "I1", "payload": {"claims": ["2", "4"], "notes": long_text}}).encode())
        c.post("/api/submit", raw=b"{}")
        status, html = c.get_text("/exam")
        self.assertEqual(status, 200)
        self.assertIn("نتیجهٔ آزمون", html)

    def test_10_single_device_session(self):
        """ورود از دستگاه دوم، نشست دستگاه اول را می‌بندد."""
        first = self.login("sup03", self._password("sup03"))
        self.login("sup03", self._password("sup03"))
        status, html = first.get_text("/login")
        self.assertEqual(status, 200)
        # نشست اول باطل شده: درخواست به /exam به صفحهٔ ورود هدایت می‌شود
        with first.get("/exam") as r:
            final = r.read().decode("utf-8")
            final_url = r.url
        self.assertIn("/login", final_url)
        self.assertIn("خوش آمدید", final)

    def test_11_grader_sees_health_report(self):
        g = self.login("t_grader", "graderpass")
        status, html = g.get_text("/grader")
        self.assertEqual(status, 200)
        self.assertIn("تشابه", html)
        self.assertIn("سلامت", html)
        import re
        aid = re.search(r"/grader/attempt/(\d+)", html).group(1)
        status, page = g.get_text(f"/grader/attempt/{aid}")
        self.assertEqual(status, 200)
        self.assertIn("گزارش سلامت آزمون", page)
        self.assertIn("زمان‌سنجی هر سوال", page)
        self.assertIn("تشابه پاسخ‌ها", page)
        self.assertIn("تلاش چسباندن", page)
        self.assertIn("پاسخ‌های نادرست", page)
        self.assertIn("پاسخ مرجع نمونه", page)      # کلید فقط برای مصحح
        # شرکت‌کننده هیچ کلیدی نمی‌بیند
        c = self.login("sup03", self._password("sup03"))
        _, own = c.get_text("/exam")
        self.assertNotIn("پاسخ مرجع نمونه", own)
        self.assertNotIn("کلید:", own)

    def test_12_service_worker_served_at_root_scope(self):
        """Service Worker از ریشه سرو می‌شود و صفحهٔ آفلاین و ثبت آن در دسترس است."""
        with urllib.request.urlopen(self.base + "/sw.js", timeout=10) as r:
            body = r.read().decode("utf-8")
            self.assertEqual(r.status, 200)
            self.assertIn("javascript", r.headers["Content-Type"])
            self.assertEqual(r.headers.get("Service-Worker-Allowed"), "/")
        self.assertIn("addEventListener('fetch'", body)
        self.assertIn("/static/offline.html", body)
        with urllib.request.urlopen(self.base + "/static/offline.html", timeout=10) as r:
            self.assertIn("text/html", r.headers["Content-Type"])
        with urllib.request.urlopen(self.base + "/offline", timeout=10) as r:
            offline = r.read().decode("utf-8")
        self.assertIn("اتصال اینترنتتان قطع است", offline)
        with urllib.request.urlopen(self.base + "/login", timeout=10) as r:
            login = r.read().decode("utf-8")
        self.assertIn("/static/register-sw.js", login)

    def test_12b_session_cookie_is_secure(self):
        """کوکی نشست با Secure، HttpOnly و SameSite ست می‌شود."""
        req = urllib.request.Request(self.base + "/login",
                                     data=urllib.parse.urlencode(
                                         {"username": "sup03", "password": self._password("sup03")}).encode(),
                                     method="POST")
        opener = urllib.request.build_opener(_NoRedirect())
        try:
            opener.open(req, timeout=10)
            cookies = ""
        except urllib.error.HTTPError as err:
            cookies = err.headers.get_all("Set-Cookie") or []
        sc = " ".join(cookies)
        self.assertIn("vb_session=", sc)
        for flag in ("HttpOnly", "Secure", "SameSite=Lax"):
            self.assertIn(flag, sc)

    def test_13_friendly_error_page(self):
        c = self.login("sup01", self._password("sup01"))
        # کاربر واردشده: صفحهٔ عادی ۴۰۴؛ کاربر ناشناس: هدایت به ورود (همان رفتار قبلی)
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            c.get("/this-page-does-not-exist")
        self.assertEqual(ctx.exception.code, 404)
        body = ctx.exception.read().decode("utf-8")
        self.assertIn("این صفحه پیدا نشد", body)
        self.assertIn("بازگشت به آزمون", body)
        self.assertNotIn("Not found", body)

    def test_14_admin_live_status_and_audit_log(self):
        a = self.login("t_admin", "adminpass")
        status, html = a.get_text("/admin/live")
        self.assertEqual(status, 200)
        for text in ("وضعیت زندهٔ آزمون", "در حال آزمون", "تمام‌کرده", "منقضی",
                     "نیمه‌کاره خارج‌شده", "لاگ ورودها و عملیات", "کارشناس پشتیبانی ۰۱"):
            self.assertIn(text, html)
        self.assertIn("لپ‌تاپ", html)   # دستگاه درخواست‌های تست، مرورگر دسکتاپ است
        self.assertIn("ورود", html)    # ثبت ورودها
        # شرکت‌کننده به صفحهٔ مدیر دسترسی ندارد
        c = self.login("sup01", self._password("sup01"))
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            c.get("/admin/live")
        self.assertEqual(ctx.exception.code, 404)
        self.assertIn("این صفحه پیدا نشد", ctx.exception.read().decode("utf-8"))

    def test_15_downloadable_report_card(self):
        c = self.login("sup01", self._password("sup01"))
        _, html = c.get_text("/exam")
        import re
        m = re.search(r"/report/(\d+)", html)
        self.assertIsNotNone(m, "لینک کارنامه روی صفحهٔ نتیجه نیست")
        aid = m.group(1)
        status, card = c.get_text(f"/report/{aid}")
        self.assertEqual(status, 200)
        for text in ("کارنامهٔ آزمون کیس‌محور", "نتیجه به تفکیک بخش",
                     "مباحثی که مسلط شده‌اید", "مباحثی که باید بیشتر بخوانید",
                     "برنامهٔ بهبود"):
            self.assertIn(text, card)
        with c.get(f"/report/{aid}?download=1") as r:
            self.assertIn("attachment", r.headers.get("Content-Disposition", ""))
            self.assertIn("vazheban-report-sup01", r.headers.get("Content-Disposition", ""))
        # کارنامهٔ دیگران برای این شرکت‌کننده باز نیست
        other = self.login("sup02", self._password("sup02"))
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            other.get(f"/report/{aid}")
        self.assertEqual(ctx.exception.code, 404)

    def test_16_admin_can_delete_user(self):
        """ادمین می‌تواند کاربر را با تمام سوابقش حذف کند؛ حذف خودش ممنوع است."""
        a = self.login("t_admin", "adminpass")
        a.post("/admin/create-user", {"username": "t_todelete", "display_name": "کاربر موقت",
                                      "password": "temppass"})
        victim = self.login("t_todelete", "temppass")
        victim.post("/exam/start")
        victim.post("/api/answer", raw=json.dumps(
            {"qid": "A1", "payload": {"choice": "ب"}}).encode())

        import sqlite3
        def count(sql):
            conn = sqlite3.connect(DB_PATH)
            try:
                return conn.execute(sql).fetchone()[0]
            finally:
                conn.close()

        uid = count("SELECT id FROM users WHERE username='t_todelete'")
        self.assertGreater(uid, 0)
        self.assertGreater(count("SELECT COUNT(*) FROM attempts WHERE user_id=%d" % uid), 0)

        # حذف حساب خودِ مدیر باید رد شود
        admin_id = count("SELECT id FROM users WHERE username='t_admin'")
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            a.post("/admin/delete-user", {"user_id": str(admin_id)})
        self.assertEqual(ctx.exception.code, 400)
        self.assertEqual(count("SELECT COUNT(*) FROM users WHERE id=%d" % admin_id), 1)

        status, html = a.post_text("/admin/delete-user", {"user_id": str(uid)})
        self.assertEqual(status, 200)
        self.assertIn("حذف شد", html)

        self.assertEqual(count("SELECT COUNT(*) FROM users WHERE id=%d" % uid), 0)
        self.assertEqual(count("SELECT COUNT(*) FROM attempts WHERE user_id=%d" % uid), 0)
        self.assertEqual(count("SELECT COUNT(*) FROM sessions WHERE user_id=%d" % uid), 0)
        self.assertEqual(count(
            "SELECT COUNT(*) FROM answers WHERE attempt_id NOT IN (SELECT id FROM attempts)"), 0)
        self.assertEqual(count(
            "SELECT COUNT(*) FROM events WHERE attempt_id NOT IN (SELECT id FROM attempts)"), 0)
        self.assertGreater(count(
            "SELECT COUNT(*) FROM audit WHERE action='admin_delete_user'"), 0)

        # کاربر حذف‌شده دیگر نمی‌تواند وارد شود
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            Client(self.base).post("/login", {"username": "t_todelete", "password": "temppass"})
        self.assertEqual(ctx.exception.code, 401)
        # نشست قبلی کاربر حذف‌شده هم باطل شده است
        with victim.get("/exam") as r:
            self.assertIn("/login", r.url)

    def test_17_choice_groups_are_per_question(self):
        """هر سوال چهارگزینه‌ای گروه رادیوی خودش را دارد.

        نام مشترک «answer» همهٔ سوال‌ها را یک گروه می‌کرد: انتخاب گزینه در یک
        سوال، انتخاب سوال‌های قبلی را از بین می‌برد و بعد از رفرش هم فقط یکی
        بازیابی می‌شد.
        """
        import re
        admin = self.login("t_admin", "adminpass")
        admin.post("/admin/create-user", {"username": "t_choice", "display_name": "گروه گزینه‌ها",
                                          "password": "choicepass"})
        c = self.login("t_choice", "choicepass")
        c.post("/exam/start")
        _, html = c.get_text("/exam")
        names = re.findall(r'<input type="radio" name="([^"]+)" value="[^"]*" data-qid="([^"]+)"', html)
        self.assertTrue(names, "گزینهٔ رادیویی روی صفحهٔ آزمون نیست")
        bad = [(n, q) for n, q in names if not n.endswith("_" + q)]
        self.assertEqual(bad, [], "نام گروه رادیو به سوال خودش گره نخورده: %s" % bad[:3])
        # هیچ نامِ عمومی بی‌مالک باقی نمانده باشد
        self.assertNotIn('name="answer"', html)
        self.assertNotIn('name="answer_multi"', html)
        # هر گروه فقط در یک سوال تکرار می‌شود
        by_name = {}
        for n, q in names:
            by_name.setdefault(n, set()).add(q)
        self.assertEqual([n for n, qs in by_name.items() if len(qs) > 1], [])
        # تعداد گروه‌ها = تعداد سوال‌های تک‌گزینه‌ای
        multi = re.findall(r'<input type="checkbox" name="answer_multi_', html)
        self.assertTrue(multi, "سوال چندانتخابی گروه خودش را ندارد")

    @staticmethod
    def _password(username):
        # رمزها هنگام ساخت کاربران به تصادف تولید می‌شوند؛ در setUpClass نگه داشته می‌شوند
        return TestHTTP.passwords[username]


def main():
    env = dict(os.environ, VAZHEBAN_DB=DB_PATH)
    out = subprocess.run([sys.executable, "manage.py", "create-users", "--participants", "3",
                          "--grader", "t_grader", "--grader-password", "graderpass"],
                         cwd=APP_DIR, env=env, check=True, capture_output=True, text=True).stdout
    passwords = {}
    for line in out.strip().splitlines()[1:]:
        parts = line.split(",")
        if len(parts) >= 2:
            passwords[parts[0]] = parts[1]
    TestHTTP.passwords = passwords
    unittest.main(module=__name__, argv=[sys.argv[0], "-v"])


class TestWrongAnswers(unittest.TestCase):
    def test_wrong_list_flags_wrong_and_missing(self):
        from types import SimpleNamespace
        import json as _json
        import app as appmod
        from exam_data import QUESTIONS_BY_ID

        class Row(dict):
            __getattr__ = dict.__getitem__

        answers = {
            "A1": Row(auto_score=0, payload=_json.dumps({"choice": "الف"})),
            "B1": Row(auto_score=0, payload=_json.dumps({"choices": ["الف"]})),
            "C1": Row(auto_score=2, payload=_json.dumps({"tf": False, "explain": "x" * 40})),
        }
        wrong = appmod.wrong_list(answers)
        ids = [w["id"] for w in wrong]
        self.assertIn("A1", ids)
        self.assertIn("B1", ids)
        self.assertNotIn("C1", ids)                       # تشخیص درست نمرهٔ کامل گرفته
        self.assertNotIn("F1", ids)                       # سوال دستی در این فهرست نیست
        a1 = next(w for w in wrong if w["id"] == "A1")
        self.assertIn(QUESTIONS_BY_ID["A1"].get("correct"), a1["note"])
        b1 = next(w for w in wrong if w["id"] == "B1")
        self.assertIn("جاافتاده", b1["note"])


if __name__ == "__main__":
    main()
