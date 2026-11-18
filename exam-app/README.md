# آزمون کیس‌محور «واژه‌بان» — سامانهٔ آزمون آنلاین

سامانهٔ تک‌آزمونی برای کارشناسان پشتیبانی مؤسسهٔ سرخ، ساخته‌شده دقیقاً بر پایهٔ
`exam-vazheban-case.md` (نسخهٔ ۲.۰): همان ۲۵ سوال در ۱۰ بخش، همان کلید پاسخ، همان روبریک،
همان بارم ۱۰۰ و همان شرط قبولی (۶۵ از ۱۰۰ + حداقل ۶ از ۱۰ در بخش محاسبه).

## نقش‌ها

| نقش | دسترسی |
|---|---|
| شرکت‌کننده (پشتیبان) | ورود با نام کاربری و رمز اختصاصی، دیدن کیس کنار سوال، پاسخ‌دهی، ارسال، دیدن کارنامه |
| مصحح | دیدن همهٔ تلاش‌های ارسال‌شده، تصحیح بخش‌های باز با روبریک، دانلود CSV نتایج |
| مدیر | پنل `/admin`: ساخت شرکت‌کننده، تغییر رمز، بازنشانی تلاش، دسترسی به پنل مصحح |

## اجرا

```bash
python3 manage.py create-users --participants 10 --prefix sup
# خروجی: username,password,role  (رمزها را به پشتیبان‌ها بدهید)

python3 app.py                  # سرور روی 127.0.0.1:8090
python3 manage.py list          # فهرست کاربران
python3 manage.py reset-password sup03
python3 manage.py export --out results.csv
```

فهرست رسمی پشتیبان‌ها (۵۷ نفر) از یک فایل TSV با ستون‌های `UserName` و `Password` ساخته می‌شود.
`--replace` همهٔ شرکت‌کننده‌های قبلی و پاسخ‌هایشان را پاک می‌کند و فهرست تازه را می‌سازد
(کاربران مدیر و مصحح دست‌نخورده می‌مانند):

```bash
python3 manage.py import-users --file ../exam-users.tsv --replace
```

مدت آزمون ۶۰ دقیقه است (`EXAM["duration_minutes"]` در `exam_data.py`) و همهٔ متن‌های
راهنما و صفحهٔ ورود از همان مقدار خوانده می‌شوند.

هیچ وابستگی خارجی لازم نیست؛ فقط پایتون ۳.۱۰ به بالا و SQLite.

## ساختار

- `exam_data.py` — متن کیس، ۲۵ سوال، کلیدها، روبریک‌ها، پاسخ‌های مرجع
- `grading.py` — موتور نمره‌دهی خودکار (A، B، تشخیص C، D، E)
- `app.py` — سرور HTTP، صفحات RTL، پنل کیس، تایمر سمت سرور، پنل مصحح، CSV
- `db.py` — SQLite
- `tests/` — تست واحد و تست HTTP انتها-به-انتها
- `deploy/` — سرویس systemd، کانفیگ nginx (پورت ۸۴۴۴)، اسکریپت دیپلوی

## نمره‌دهی

**خودکار (۵۱ نمره):** A (۲۴) · B (۶ با نمرهٔ جزئی ۳ برای سه‌از‌چهار) · تشخیص C (۶) · D (۵) · E (۱۰ با بازهٔ ۲٪)
**دستی با روبریک (۴۹ نمره):** تصحیح جملهٔ C (۶) · F (۱۶) · G (۱۰) · H (۵) · I (۶) · J (۶)

تا وقتی همهٔ سوال‌های دستی تصحیح نشده‌اند، نتیجهٔ قبولی «قطعی» اعلام نمی‌شود.

## تست

```bash
python3 -m unittest tests.test_exam -v
python3 tests/test_http.py -v
```

## استقرار

```bash
bash deploy/deploy.sh
```

سپس کاربران را روی سرور بسازید:

```bash
ssh root@46.34.163.254 'cd /opt/vazheban-exam && sudo -u www-data python3 manage.py create-users --participants 20 --prefix sup --grader momarres --grader-password "RAMZ-MOSAHHEH"'
```

آدرس: `https://exam.46-34-163-254.sslip.io/` (گواهی Let's Encrypt روی ۴۴۳)

ساخت/هم‌سان‌سازی کاربر:

```bash
python3 manage.py upsert-user admin --password 8843 --name "مدیر آزمون" --role admin
python3 manage.py upsert-user poshitban --password 1234 --name "کارشناس پشتیبان" --role participant
```
