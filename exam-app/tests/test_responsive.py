# -*- coding: utf-8 -*-
"""تست رسپانسیو بدون مرورگر: ساختار صفحه‌ها و قواعد چیدمان.

هدف: هیچ جدول عریضی بدون قاب اسکرول نماند، هیچ شبکه‌ای ستون ثابتِ بزرگ‌تر از
عرض صفحه نداشته باشد، و محافظ سرریز افقی سر جایش باشد.

اجرا:  python3 tests/test_responsive.py -v
"""
import http.cookiejar
import json
import os
import re
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
TMP = tempfile.mkdtemp(prefix="vazheban-responsive-")
DB_PATH = os.path.join(TMP, "exam.db")
CSS = open(os.path.join(APP_DIR, "static", "style.css"), encoding="utf-8").read()


class _LoopbackPolicy(http.cookiejar.DefaultCookiePolicy):
    def return_ok_secure(self, cookie, request):
        return True


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


class Client:
    def __init__(self, base):
        self.base = base
        self.opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(
                http.cookiejar.CookieJar(policy=_LoopbackPolicy())))

    def get(self, path):
        return self.opener.open(self.base + path, timeout=15)

    def post(self, path, data=None, raw=None):
        if raw is None:
            raw = urllib.parse.urlencode(data or {}).encode()
        req = urllib.request.Request(self.base + path, data=raw, method="POST")
        req.add_header("Content-Type",
                       "application/json" if data is None else "application/x-www-form-urlencoded")
        return self.opener.open(req, timeout=15)

    def html(self, path):
        with self.get(path) as r:
            return r.read().decode("utf-8")


def unwrapped_tables(html):
    """جدول‌هایی که بلافاصله داخل <div class="table-wrap..."> نیستند."""
    bad = []
    for m in re.finditer(r"<table\b", html):
        before = html[max(0, m.start() - 260):m.start()]
        if not re.search(r'<div class="(?:table-wrap[^"]*|tblwrap)"[^>]*>\s*$', before):
            bad.append(html[m.start():m.start() + 90])
    return bad


class TestResponsive(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.port = free_port()
        env = dict(os.environ, VAZHEBAN_DB=DB_PATH, PORT=str(cls.port), PYTHONPATH=APP_DIR)
        out = subprocess.run([sys.executable, "manage.py", "create-users", "--participants", "2",
                              "--grader", "t_grader", "--grader-password", "graderpass"],
                             cwd=APP_DIR, env=env, check=True, capture_output=True, text=True).stdout
        cls.passwords = {}
        for line in out.strip().splitlines()[1:]:
            parts = line.split(",")
            if len(parts) >= 2:
                cls.passwords[parts[0]] = parts[1]
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
        cls._seed()

    @classmethod
    def tearDownClass(cls):
        cls.proc.send_signal(signal.SIGTERM)
        cls.proc.wait(timeout=10)
        shutil.rmtree(TMP, ignore_errors=True)

    # ------------------------------------------------------------ seed
    @classmethod
    def _seed(cls):
        """یک تلاش ارسال‌شده (برای صفحهٔ نتیجه/کارنامه) و یک تلاش جاری."""
        done = Client(cls.base)
        done.post("/login", {"username": "sup01", "password": cls.passwords["sup01"]})
        done.post("/exam/start")
        answers = {
            "A1": {"choice": "ب"}, "B1": {"choices": ["الف", "ب"]},
            "C1": {"tf": False, "explain": "سود به پوشش هزینهٔ ثابت بستگی دارد و حاشیهٔ سود تنها کافی نیست."},
            "E1": {"cac": "۳۰۰۰۰۰۰", "work": "۶۰۰ میلیون تقسیم بر ۲۰۰ مشتری"},
            "F1": {"text": "مسئلهٔ عینی با داده‌های کیس قابل اندازه‌گیری است اما درد احساسی نیست و نیاز به شاهد دارد."},
            "C2": {"tf": True, "explain": "ماندگاری دو برابر می‌شود و ارزش عمر مشتری هم به همان نسبت بالا می‌رود."},
            "C3": {"tf": False, "explain": "TAM اندازهٔ فرصت بازار است نه سودآوری واقعی شرکت در کوتاه‌مدت."},
            "F2": {"text": "زبان‌لند جایگزین ارزان‌تر است و باید با تمایز تجربه پاسخ داده شود نه با کاهش قیمت."},
            "I1": {"claims": ["2", "4"],
                   "notes": "خطای ترکیبی و بزرگ‌نمایی TAM در استدلال دیده می‌شود و باید با دادهٔ کیس سنجیده شود."},
        }
        for qid, payload in answers.items():
            done.post("/api/answer", raw=json.dumps({"qid": qid, "payload": payload}).encode())
        done.post("/api/submit", raw=b"{}")
        cls.done = done

        live = Client(cls.base)
        live.post("/login", {"username": "sup02", "password": cls.passwords["sup02"]})
        live.post("/exam/start")
        live.post("/api/answer", raw=json.dumps({"qid": "A1", "payload": {"choice": "ب"}}).encode())
        cls.live = live

        cls.admin = Client(cls.base)
        cls.admin.post("/login", {"username": "t_admin", "password": "adminpass"})
        grader_html = cls.admin.html("/grader")
        m = re.search(r"/grader/attempt/(\d+)", grader_html)
        cls.attempt_id = m.group(1) if m else None

    # ------------------------------------------------------------ helpers
    def pages(self):
        """(نام صفحه، کلاینت، مسیر) برای همهٔ صفحه‌های کاربری."""
        items = [
            ("ورود", None, "/login"),
            ("راهنما", self.live, "/guide"),
            ("آزمون جاری", self.live, "/exam"),
            ("نتیجه", self.done, "/exam"),
            ("کارنامه", self.done, f"/report/{self.attempt_id}"),
            ("مصحح", self.admin, "/grader"),
            ("تصحیح", self.admin, f"/grader/attempt/{self.attempt_id}"),
            ("مدیریت", self.admin, "/admin"),
            ("وضعیت زنده", self.admin, "/admin/live"),
            ("خطای ۴۰۴", self.admin, "/no-such-page-xyz"),
            ("آفلاین", None, "/offline"),
        ]
        return items

    # ------------------------------------------------------------ tests
    def test_01_every_table_has_scroll_wrapper(self):
        problems = []
        for name, client, path in self.pages():
            if client is None:
                opener = urllib.request.build_opener()
                try:
                    with opener.open(self.base + path, timeout=10) as r:
                        html = r.read().decode("utf-8")
                except urllib.error.HTTPError as err:
                    html = err.read().decode("utf-8")
            else:
                try:
                    html = client.html(path)
                except urllib.error.HTTPError as err:
                    html = err.read().decode("utf-8")
            bad = unwrapped_tables(html)
            if bad:
                problems.append(f"{name} ({path}): {bad[:2]}")
        self.assertEqual(problems, [], "جدول بدون قاب اسکرول:\n" + "\n".join(problems))

    def test_02_pages_have_viewport_and_no_fixed_page_width(self):
        for name, client, path in self.pages():
            opener = urllib.request.build_opener()
            try:
                with opener.open(self.base + path, timeout=10) as r:
                    html = r.read().decode("utf-8")
            except urllib.error.HTTPError as err:
                html = err.read().decode("utf-8")
            self.assertIn('name="viewport"', html, name)
            self.assertNotIn('width=1024', html, name)
            # هیچ عنصری با عرض ثابت بزرگ‌تر از ۳۲۰ پیکسل به‌صورت inline نباشد
            for m in re.finditer(r'style="[^"]*\bwidth:\s*(\d{3,})px', html):
                self.assertLess(int(m.group(1)), 320, f"{name}: عرض ثابت {m.group(1)}px")

    def test_03_layout_guards_present(self):
        rules = re.findall(r"\nbody\s*\{([^}]*)\}", CSS)
        guard = [r for r in rules if "overflow-x: clip" in r]
        self.assertTrue(guard, "محافظ سرریز افقی body")
        # بدون محور عمودی صریح، clip می‌تواند اسکرول عمودی را قطع کند
        self.assertIn("overflow-y: auto", guard[-1], "محور عمودی باید auto بماند")
        self.assertRegex(CSS, r"\.table-wrap\s*\{[^}]*overflow-x:\s*auto", "قاب اسکرول جدول")
        self.assertRegex(CSS, r"\.case-pane\s*\{[^}]*min-width:\s*0", "کارت کیس باید کوچک‌شدنی باشد")
        self.assertRegex(CSS, r"\.exam-main\s*\{[^}]*min-width:\s*0")
        self.assertIn("overflow-wrap: break-word", CSS)

    def test_04_auth_grid_columns_can_shrink(self):
        block = re.search(r"\.auth-main\s*\{([^}]*)\}", CSS).group(1)
        cols = re.search(r"grid-template-columns:([^;]+);", block).group(1)
        tracks = [t.strip() for t in cols.split(") ") if t.strip()]
        for track in tracks:
            self.assertRegex(track, r"^minmax\(0,",
                             f"ستون ثابت در صفحهٔ ورود می‌تواند سرریز کند: {track}")
        self.assertIn("clamp(", block, "فاصلهٔ ستون‌ها باید کشسان باشد")

    def test_05_breakpoints_cover_all_widths(self):
        for width in (1280, 1080, 900, 820, 640, 560, 400):
            self.assertIn(f"max-width: {width}px", CSS, f"نقطهٔ شکست {width}px")
        self.assertIn("min-width: 901px", CSS)

    def test_05b_no_ios_input_zoom(self):
        """فیلدهای فرم در موبایل ۱۶ پیکسل‌اند تا iOS زوم نکند."""
        block = re.search(r"@media \(max-width: 900px\) \{[^@]*font-size: 16px", CSS)
        self.assertIsNotNone(block)

    def test_06_match_table_stacks_on_phones(self):
        self.assertRegex(CSS, r"@media \(max-width: 560px\)[^@]*\.match-table thead\s*\{\s*display:\s*none")
        self.assertRegex(CSS, r"@media \(max-width: 560px\)[^@]*\.match-table td\s*\{[^}]*display:\s*block")

    def test_07_case_tables_scroll_on_mobile(self):
        self.assertRegex(CSS, r"\.case-body \.table-wrap > table\s*\{[^}]*min-width:\s*500px")
        self.assertRegex(CSS, r"\.case-pane \.case-body\s*\{[^}]*overflow-x:\s*auto")

    def test_08_report_card_has_scroll_wrapper(self):
        sys.path.insert(0, APP_DIR)
        os.environ["VAZHEBAN_DB"] = DB_PATH
        import db
        import reportcard
        db.init_db()
        conn = db.connect()
        row = conn.execute(
            "SELECT a.*, u.display_name AS owner, u.username AS owner_username FROM attempts a "
            "JOIN users u ON u.id=a.user_id WHERE a.submitted_at IS NOT NULL LIMIT 1").fetchone()
        html = reportcard.render_report(conn, row, row["owner"])
        conn.close()
        self.assertEqual(unwrapped_tables(html), [])
        self.assertIn("overflow-x:auto", html.replace(" ", ""))
        self.assertIn("overflow-x:clip", html.replace(" ", ""))

    def test_09_sticky_offsets_do_not_overlap_topbar(self):
        """نوار تایمر نباید زیر سرصفحهٔ چسبیده پنهان شود."""
        topbar = re.search(r"body\.taking-exam \.topbar \{ padding: (\d+)px", CSS)
        timer = re.search(r"body\.taking-exam \.timerbar \{\s*top: (\d+)px", CSS)
        self.assertIsNotNone(topbar)
        self.assertIsNotNone(timer)
        # سرصفحه: ۲×padding + ارتفاع خط ≈ ۲۵px + ۱px خط پایین
        self.assertGreaterEqual(int(timer.group(1)), 2 * int(topbar.group(1)) + 25)


if __name__ == "__main__":
    unittest.main(verbosity=2)
