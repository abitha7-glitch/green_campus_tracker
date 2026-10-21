// Small bits of behaviour. Everything still works with JS off,
// the server checks every form again anyway.

document.addEventListener("DOMContentLoaded", () => {
  // mobile menu
  const menuBtn = document.querySelector("[data-menu]");
  if (menuBtn) {
    menuBtn.addEventListener("click", () => {
      const nav = document.getElementById("nav");
      const open = nav.classList.toggle("open");
      menuBtn.setAttribute("aria-expanded", open);
    });
  }

  // close flash messages
  document.querySelectorAll("[data-dismiss]").forEach(btn =>
    btn.addEventListener("click", () => btn.parentElement.remove()));

  // quick filter on list pages (only filters what's already on screen)
  document.querySelectorAll("[data-filter]").forEach(input => {
    const table = document.querySelector(input.dataset.filter);
    const noMatch = table.parentElement.querySelector(".no-match");
    input.addEventListener("input", () => {
      const term = input.value.trim().toLowerCase();
      let shown = 0;
      table.querySelectorAll("tbody tr").forEach(tr => {
        const hit = tr.textContent.toLowerCase().includes(term);
        tr.hidden = !hit;
        if (hit) shown++;
      });
      if (noMatch) noMatch.hidden = shown > 0;
    });
  });

  // click a header to sort
  document.querySelectorAll("table.sortable").forEach(table => {
    table.querySelectorAll("th[data-sort]").forEach((th, idx) => {
      th.addEventListener("click", () => sortTable(table, th, idx));
    });
  });

  // client-side validation
  document.querySelectorAll("form[data-validate]").forEach(form => {
    form.addEventListener("submit", e => {
      if (!checkForm(form)) {
        e.preventDefault();
        const first = form.querySelector(".has-error input, .has-error select");
        if (first) first.focus();
      }
    });
    form.querySelectorAll("input, select").forEach(el =>
      el.addEventListener("change", () => clearError(el)));
  });

  // copy SQL on the queries page
  document.querySelectorAll("[data-copy]").forEach(btn => {
    btn.addEventListener("click", () => {
      const code = btn.parentElement.querySelector("code").textContent;
      navigator.clipboard.writeText(code).then(() => {
        btn.textContent = "Copied";
        setTimeout(() => (btn.textContent = "Copy"), 1500);
      });
    });
  });

  // ctrl+enter runs the console query
  const sqlBox = document.getElementById("sql");
  if (sqlBox) {
    sqlBox.addEventListener("keydown", e => {
      if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) sqlBox.form.submit();
    });
  }

  // live CO2e estimate on the reading form. The real value comes from the trigger,
  // this is just so you can see roughly what you're about to log.
  const calc = document.querySelector("[data-calc]");
  if (calc && window.METER_FACTORS) {
    const meter = document.getElementById("meter_id");
    const amount = document.getElementById("consumption_value");
    const out = calc.querySelector("[data-calc-out]");
    const update = () => {
      const f = window.METER_FACTORS[meter.value];
      const v = parseFloat(amount.value);
      if (!f || isNaN(v) || v < 0) { calc.hidden = true; return; }
      calc.hidden = false;
      out.textContent = (v * f[0]).toLocaleString("en-IN", { maximumFractionDigits: 2 }) + " kg";
      calc.querySelector("span").textContent = `Estimated CO₂e (${v} ${f[1]} × ${f[0]})`;
    };
    meter.addEventListener("change", update);
    amount.addEventListener("input", update);
    update();
  }
});


function sortTable(table, th, idx) {
  const tbody = table.tBodies[0];
  const rows = Array.from(tbody.rows);
  const asc = th.getAttribute("aria-sort") !== "ascending";
  table.querySelectorAll("th").forEach(h => h.removeAttribute("aria-sort"));
  th.setAttribute("aria-sort", asc ? "ascending" : "descending");

  const value = tr => {
    const text = (tr.cells[idx]?.textContent || "").trim();
    const n = parseFloat(text.replace(/,/g, ""));
    // dates like "01 Sep 2026"
    const d = Date.parse(text);
    if (/^\d{2} \w{3} \d{4}/.test(text) && !isNaN(d)) return d;
    return isNaN(n) ? text.toLowerCase() : n;
  };
  rows.sort((a, b) => {
    const x = value(a), y = value(b);
    if (x < y) return asc ? -1 : 1;
    if (x > y) return asc ? 1 : -1;
    return 0;
  });
  rows.forEach(r => tbody.appendChild(r));
}


function showError(el, msg) {
  const field = el.closest(".field");
  if (!field) return;
  field.classList.add("has-error");
  let p = field.querySelector(".err");
  if (!p) {
    p = document.createElement("p");
    p.className = "err";
    field.appendChild(p);
  }
  p.textContent = msg;
  const hint = field.querySelector(".hint");
  if (hint) hint.hidden = true;
}

function clearError(el) {
  const field = el.closest(".field");
  if (!field) return;
  field.classList.remove("has-error");
  const p = field.querySelector(".err");
  if (p) p.remove();
  const hint = field.querySelector(".hint");
  if (hint) hint.hidden = false;
}

function checkForm(form) {
  let ok = true;
  form.querySelectorAll("input, select").forEach(el => {
    if (el.type === "search" || el.type === "hidden") return;
    clearError(el);
    const label = el.closest(".field")?.querySelector("label")?.textContent.trim() || "This field";
    const v = el.value.trim();

    if (el.required && !v) { showError(el, `${label} is required.`); ok = false; return; }
    if (!v) return;

    if (el.type === "number") {
      const n = Number(v);
      if (isNaN(n)) { showError(el, `${label} has to be a number.`); ok = false; return; }
      if (el.min !== "" && n < Number(el.min)) {
        showError(el, Number(el.min) === 0 ? `${label} can't be negative.` : `${label} must be at least ${el.min}.`);
        ok = false; return;
      }
      if (el.max !== "" && n > Number(el.max)) { showError(el, `${label} can be at most ${el.max}.`); ok = false; return; }
      if (el.step === "1" && !Number.isInteger(n)) { showError(el, `${label} has to be a whole number.`); ok = false; return; }
    }
    if (el.type === "email" && !/^[^@\s]+@[^@\s]+\.[A-Za-z]{2,}$/.test(v)) {
      showError(el, "That doesn't look like an email address."); ok = false; return;
    }
    if (el.pattern && !new RegExp(`^(?:${el.pattern})$`).test(v)) {
      showError(el, "Use letters, digits and dashes, like ELEC-MAB-02."); ok = false; return;
    }
    if (el.type === "date") {
      if (el.max && v > el.max) { showError(el, "That date is in the future."); ok = false; return; }
      if (el.dataset.after) {
        const other = form.querySelector(el.dataset.after);
        if (other && other.value && v < other.value) {
          showError(el, "This has to be on or after the start date."); ok = false; return;
        }
      }
    }
  });
  return ok;
}
