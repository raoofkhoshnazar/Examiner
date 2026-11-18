/* سامانهٔ آزمون واژه‌بان — پنل تصحیح */
(function () {
  "use strict";
  const FA = ["۰", "۱", "۲", "۳", "۴", "۵", "۶", "۷", "۸", "۹"];
  const fa = (n) => String(n).replace(/[0-9]/g, (d) => FA[+d]);
  const attemptId = window.ATTEMPT_ID;

  document.querySelectorAll(".save-score").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const qid = btn.dataset.qid;
      const scores = {};
      let missing = false;
      document.querySelectorAll(`.rubric-select[data-qid="${qid}"]`).forEach((sel) => {
        if (sel.value === "") missing = true;
        else scores[sel.dataset.key] = Number(sel.value);
      });
      if (missing) {
        btn.textContent = "همهٔ معیارها را نمره دهید";
        setTimeout(() => { btn.textContent = "ثبت نمرهٔ این سوال"; }, 2000);
        return;
      }
      btn.disabled = true;
      try {
        const res = await fetch("/api/score", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ attempt_id: attemptId, qid, scores }),
        });
        const data = await res.json();
        if (res.ok) {
          const flag = document.getElementById("flag-" + qid);
          if (flag) flag.textContent = "ثبت‌شده: " + fa(data.total);
          btn.textContent = "ثبت شد ✓";
          const sum = document.getElementById("gradeSummary");
          if (sum) {
            sum.textContent = `نمرهٔ کل فعلی: ${fa(Math.round(data.attempt_total))} از ۱۰۰ · ` +
              (data.pending ? "بخش‌های باز باقی مانده است" : (data.passed ? "قبول" : "زیر حد قبولی"));
          }
          setTimeout(() => { btn.textContent = "ثبت نمرهٔ این سوال"; btn.disabled = false; }, 1400);
        } else {
          btn.textContent = "خطا — دوباره بزنید";
          btn.disabled = false;
        }
      } catch (err) {
        btn.textContent = "خطای شبکه";
        btn.disabled = false;
      }
    });
  });
})();
