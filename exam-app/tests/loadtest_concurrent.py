# -*- coding: utf-8 -*-
"""آزمون بار: شبیه‌سازی N کاربر هم‌زمان روی یک نمونهٔ جداگانه از سامانه.

سرور را با دیتابیس موقت در پورت آزاد بالا می‌آورد (به دادهٔ واقعی دست نمی‌زند)،
همهٔ کاربران را با یک سد هم‌زمان آزاد می‌کند و زمان پاسخ هر مرحله را می‌سنجد.

اجرا روی سرور:
    python3 tests/loadtest_concurrent.py --users 50 --questions 25
"""
import argparse
import http.cookiejar
import json
import os
import re
import shutil
import signal
import socket
import statistics
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if APP_DIR not in sys.path:
    sys.path.insert(0, APP_DIR)


class _LoopbackPolicy(http.cookiejar.DefaultCookiePolicy):
    def return_ok_secure(self, cookie, request):
        return True


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


class Result:
    def __init__(self):
        self.lock = threading.Lock()
        self.lat = {}          # نام مرحله -> فهرست میلی‌ثانیه
        self.errors = []
        self.logged_in = 0
        self.submitted = 0

    def add(self, name, ms):
        with self.lock:
            self.lat.setdefault(name, []).append(ms)

    def err(self, who, what):
        with self.lock:
            self.errors.append(f"{who}: {what}")


def client(base):
    return urllib.request.build_opener(
        urllib.request.HTTPCookieProcessor(
            http.cookiejar.CookieJar(policy=_LoopbackPolicy())))


def timed(res, name, fn):
    t0 = time.perf_counter()
    try:
        out = fn()
        res.add(name, (time.perf_counter() - t0) * 1000)
        return out
    except urllib.error.HTTPError as e:
        res.add(name, (time.perf_counter() - t0) * 1000)
        raise RuntimeError(f"HTTP {e.code}") from e
    finally:
        pass


def parse_state(html):
    m = re.search(r"window\.EXAM_STATE\s*=\s*(\{.*?\});", html, re.S)
    if not m:
        m = re.search(r"EXAM_STATE\s*=\s*(\{.*?\})\s*;", html, re.S)
    if not m:
        raise RuntimeError("EXAM_STATE در صفحهٔ آزمون پیدا نشد")
    return json.loads(m.group(1))


SAMPLE_ANSWER = {
    "A1": {"choice": "ب"},
    "B1": {"choices": ["الف", "ب"]},
    "C1": {"tf": False, "explain": "سود به پوشش هزینهٔ ثابت بستگی دارد و حاشیهٔ سود تنها کافی نیست."},
    "C2": {"tf": True, "explain": "ماندگاری دو برابر می‌شود و ارزش عمر مشتری هم به همان نسبت بالا می‌رود."},
    "C3": {"tf": False, "explain": "TAM اندازهٔ فرصت بازار است نه سودآوری واقعی شرکت در کوتاه‌مدت."},
    "E1": {"cac": "۳۰۰۰۰۰۰", "work": "۶۰۰ میلیون تقسیم بر ۲۰۰ مشتری"},
    "F1": {"text": "مسئلهٔ عینی با داده‌های کیس قابل اندازه‌گیری است اما درد احساسی نیست و نیاز به شاهد دارد."},
    "F2": {"text": "زبان‌لند جایگزین ارزان‌تر است و باید با تمایز تجربه پاسخ داده شود نه با کاهش قیمت."},
    "I1": {"claims": ["2", "4"], "notes": "خطای ترکیبی و بزرگ‌نمایی TAM در استدلال دیده می‌شود و باید با دادهٔ کیس سنجیده شود."},
}


def answer_for(qid, i):
    if qid in SAMPLE_ANSWER:
        return SAMPLE_ANSWER[qid]
    return {"choice": "الف"} if i % 2 else {"response": "پاسخ آزمایشی بار برای این سوال."}


def user_flow(base, idx, password, res, barrier, questions, spread=0.0):
    who = f"u{idx}"
    op = client(base)
    try:
        barrier.wait(timeout=120)                       # همه با هم شروع می‌کنند
        if spread > 0:                                  # ورود پخش‌شده و نامنظم
            time.sleep((idx % 100) / 100.0 * spread)
        timed(res, "login", lambda: op.open(
            base + "/login",
            data=urllib.parse.urlencode({"username": f"sup{idx:02d}", "password": password}).encode(),
            timeout=60).read())
        with res.lock:
            res.logged_in += 1
        timed(res, "guide", lambda: op.open(base + "/guide", timeout=60).read())
        timed(res, "start", lambda: op.open(base + "/exam/start", data=b"", timeout=60).read())
        html = timed(res, "exam_page", lambda: op.open(base + "/exam", timeout=60).read()).decode()
        state = parse_state(html)
        qids = state.get("qids") or []

        for n, qid in enumerate(qids[:questions]):
            body = json.dumps({"qid": qid, "payload": answer_for(qid, n)}).encode()
            req = urllib.request.Request(base + "/api/answer", data=body, method="POST")
            req.add_header("Content-Type", "application/json")
            timed(res, "answer", lambda r=req: op.open(r, timeout=60).read())
            if n % 3 == 0:                              # هر سه سوال یک بار نظرسنجی زمان
                timed(res, "time", lambda: op.open(base + "/exam/time", timeout=60).read())
            time.sleep(0.15)                            # فاصلهٔ کوتاه پاسخ‌دهی

        # ارسال با کمی پخش‌شدگی تا شبیه رفتار واقعی باشد
        time.sleep((idx % 10) * 0.4)
        timed(res, "submit", lambda: op.open(
            base + "/api/submit", data=b"{}", timeout=120).read())
        with res.lock:
            res.submitted += 1
    except Exception as exc:                            # noqa: BLE001
        res.err(who, str(exc))


def pct(values, p):
    if not values:
        return 0.0
    data = sorted(values)
    k = max(0, min(len(data) - 1, int(round((p / 100) * (len(data) - 1)))))
    return data[k]


def rss_of(pid):
    try:
        with open(f"/proc/{pid}/status", encoding="utf-8") as fh:
            for line in fh:
                if line.startswith("VmRSS:"):
                    return int(line.split()[1]) / 1024
    except OSError:
        pass
    return 0.0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--users", type=int, default=50)
    ap.add_argument("--questions", type=int, default=25)
    ap.add_argument("--spread", type=float, default=0.0,
                    help="ورودها در این تعداد ثانیه پخش شوند (۰ = همه با هم)")
    ap.add_argument("--keep", action="store_true")
    args = ap.parse_args()

    tmp = tempfile.mkdtemp(prefix="vazheban-load-")
    db_path = os.path.join(tmp, "exam.db")
    port = free_port()
    env = dict(os.environ, VAZHEBAN_DB=db_path, PORT=str(port), PYTHONPATH=APP_DIR)
    base = f"http://127.0.0.1:{port}"

    print(f"→ ساخت {args.users} کاربر آزمایشی …")
    out = subprocess.run([sys.executable, "manage.py", "create-users",
                          "--participants", str(args.users)],
                         cwd=APP_DIR, env=env, check=True, capture_output=True, text=True).stdout
    passwords = {}
    for line in out.strip().splitlines()[1:]:
        parts = [p.strip() for p in line.split(",")]
        if len(parts) >= 2:
            passwords[parts[0]] = parts[1]

    proc = subprocess.Popen([sys.executable, "app.py"], cwd=APP_DIR, env=env,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        for _ in range(100):
            try:
                with urllib.request.urlopen(base + "/health", timeout=1) as r:
                    if r.status == 200:
                        break
            except Exception:                          # noqa: BLE001
                time.sleep(0.1)
        else:
            raise SystemExit("سرور بالا نیامد")

        rss_idle = rss_of(proc.pid)
        res = Result()
        barrier = threading.Barrier(args.users + 1)
        threads = [threading.Thread(target=user_flow,
                                    args=(base, i, passwords[f"sup{i:02d}"], res, barrier,
                                          args.questions, args.spread))
                   for i in range(1, args.users + 1)]
        for t in threads:
            t.start()
        t0 = time.perf_counter()
        barrier.wait(timeout=60)
        peak = rss_idle
        for t in threads:
            t.join(timeout=600)
            peak = max(peak, rss_of(proc.pid))
        elapsed = time.perf_counter() - t0

        print(f"\n{'مرحله':<12}{'تعداد':>7}{'میانگین':>10}{'p50':>9}{'p95':>9}{'بیشینه':>9}")
        print("-" * 56)
        for name in ("login", "guide", "exam_page", "start", "answer", "time", "submit"):
            v = res.lat.get(name, [])
            print(f"{name:<12}{len(v):>7}{statistics.mean(v) if v else 0:>9.0f}ms"
                  f"{pct(v, 50):>8.0f}ms{pct(v, 95):>8.0f}ms{max(v) if v else 0:>8.0f}ms")

        answers = len(res.lat.get("answer", []))
        print(f"\nورود موفق: {res.logged_in}/{args.users}   "
              f"ارسال موفق: {res.submitted}/{args.users}   "
              f"پاسخ ثبت‌شده: {answers}")
        print(f"زمان کل اجرای سناریو: {elapsed:.1f} ثانیه")
        print(f"حافظهٔ سرور: بیکار {rss_idle:.0f}MB → اوج {peak:.0f}MB")
        if res.errors:
            print(f"\nخطاها ({len(res.errors)}):")
            for e in res.errors[:15]:
                print("  -", e)
        else:
            print("\nبدون خطا.")
    finally:
        proc.send_signal(signal.SIGTERM)
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
        if not args.keep:
            shutil.rmtree(tmp, ignore_errors=True)
        else:
            print("دیتابیس تست:", db_path)


if __name__ == "__main__":
    main()
