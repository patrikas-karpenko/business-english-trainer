// Theme, paste blocking, timers and response times. No external libraries except the local htmx.
(function () {
  "use strict";

  // ---- theme: "light" | "dark" | "system" (stored per browser)
  function applyTheme(choice) {
    var root = document.documentElement;
    if (choice === "light" || choice === "dark") root.setAttribute("data-theme", choice);
    else root.removeAttribute("data-theme");
    document.querySelectorAll("[data-theme-set]").forEach(function (b) {
      b.setAttribute("aria-pressed", String(b.getAttribute("data-theme-set") === (choice || "system")));
    });
  }
  function storedTheme() { try { return localStorage.getItem("theme") || "system"; } catch (e) { return "system"; } }
  document.addEventListener("click", function (e) {
    var b = e.target.closest("[data-theme-set]");
    if (!b) return;
    var choice = b.getAttribute("data-theme-set");
    try { localStorage.setItem("theme", choice); } catch (err) {}
    applyTheme(choice);
  });
  document.addEventListener("click", function (e) {
    var b = e.target.closest("[data-theme-toggle]");
    if (!b) return;
    var dark = document.documentElement.getAttribute("data-theme") === "dark" ||
      (!document.documentElement.getAttribute("data-theme") && window.matchMedia("(prefers-color-scheme: dark)").matches);
    var choice = dark ? "light" : "dark";
    try { localStorage.setItem("theme", choice); } catch (err) {}
    applyTheme(choice);
  });

  // ---- toast
  function toast(msg) {
    var t = document.getElementById("toast");
    if (!t) return;
    t.textContent = msg;
    t.classList.add("show");
    clearTimeout(t._h);
    t._h = setTimeout(function () { t.classList.remove("show"); }, 2200);
  }

  // ---- paste blocking: the app trains writing without copy-paste or AI
  document.addEventListener("paste", function (e) {
    var el = e.target.closest && e.target.closest("[data-nopaste]");
    if (!el) return;
    e.preventDefault();
    var form = el.form || el.closest("form");
    var counter = form && form.querySelector("input[name=pasted]");
    if (counter) counter.value = String((parseInt(counter.value, 10) || 0) + 1);
    toast("Pasting is off here — type it yourself.");
  });

  // ---- response time and timers (re-armed after every htmx swap)
  function arm(root) {
    root.querySelectorAll("form[data-timed]").forEach(function (f) {
      if (f._armed) return;
      f._armed = true;
      f._start = Date.now();
      var ms = f.querySelector("input[name=response_ms]");
      f.addEventListener("submit", function () { if (ms) ms.value = String(Date.now() - f._start); });
      f.addEventListener("htmx:configRequest", function (ev) {
        if (ms) ev.detail.parameters.response_ms = String(Date.now() - f._start);
      });
      var secs = parseInt(f.getAttribute("data-seconds") || "0", 10);
      var out = f.querySelector("[data-countdown]");
      if (secs && out) {
        var end = f._start + secs * 1000;
        var tick = function () {
          var left = Math.max(0, Math.round((end - Date.now()) / 1000));
          out.textContent = Math.floor(left / 60) + ":" + String(left % 60).padStart(2, "0");
          if (left === 0) {
            var flag = f.querySelector("input[name=timed_out]");
            if (flag) flag.value = "1";
            out.textContent = "Time's up — send what you have";
            return;
          }
          f._t = setTimeout(tick, 250);
        };
        tick();
      }
      var first = f.querySelector("[autofocus], .gap-input, textarea, input[type=text]");
      if (first && root !== document) first.focus({ preventScroll: false });
    });
  }
  document.addEventListener("DOMContentLoaded", function () { applyTheme(storedTheme()); arm(document); });
  document.addEventListener("htmx:afterSwap", function (e) { arm(e.target.parentNode || document); });
  document.addEventListener("htmx:afterSettle", function (e) { arm(document); });
})();
