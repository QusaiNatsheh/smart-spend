/* Smart Spend — front-end behaviour: theme, toasts, command palette, chat. */
(function () {
  "use strict";

  // --- Theme (persisted in a cookie so it survives navigation) ---
  function setCookie(name, value) {
    document.cookie = name + "=" + value + ";path=/;max-age=" + 60 * 60 * 24 * 365 + ";SameSite=Lax";
  }
  window.toggleTheme = function () {
    var root = document.documentElement;
    var next = root.getAttribute("data-theme") === "light" ? "dark" : "light";
    root.setAttribute("data-theme", next);
    setCookie("theme", next);
    var icon = document.getElementById("theme-icon");
    if (icon) icon.className = next === "light" ? "ti ti-moon" : "ti ti-sun";
  };

  // --- Toasts: auto-dismiss ---
  document.querySelectorAll(".toast").forEach(function (t) {
    setTimeout(function () {
      t.style.transition = "opacity .3s, transform .3s";
      t.style.opacity = "0";
      t.style.transform = "translateY(8px)";
      setTimeout(function () { t.remove(); }, 320);
    }, 4200);
  });

  // --- Command palette ---
  var commands = [
    { label: "Go to dashboard", icon: "ti-layout-dashboard", url: "/dashboard/" },
    { label: "View all transactions", icon: "ti-list", url: "/transactions/" },
    { label: "Open insights", icon: "ti-sparkles", url: "/insights/" },
    { label: "Monthly report", icon: "ti-report", url: "/report/" },
    { label: "Settings", icon: "ti-settings", url: "/settings/" },
    { label: "Export expenses to CSV", icon: "ti-download", url: "/export/" },
    { label: "Import expenses from CSV", icon: "ti-upload", url: "/import/" },
    { label: "Add expense (focus quick-add)", icon: "ti-plus", action: "quickadd" },
  ];
  var scrim, listEl, inputEl, activeIndex = 0, filtered = commands;

  function buildPalette() {
    scrim = document.createElement("div");
    scrim.className = "cmdk-scrim";
    scrim.innerHTML =
      '<div class="cmdk" role="dialog" aria-label="Command palette">' +
      '<input type="text" placeholder="Type a command or search…" aria-label="Command search" />' +
      '<div class="cmdk-list"></div></div>';
    document.body.appendChild(scrim);
    inputEl = scrim.querySelector("input");
    listEl = scrim.querySelector(".cmdk-list");
    scrim.addEventListener("click", function (e) { if (e.target === scrim) closePalette(); });
    inputEl.addEventListener("input", function () { render(inputEl.value); });
    inputEl.addEventListener("keydown", onKey);
  }

  function render(q) {
    q = (q || "").toLowerCase();
    filtered = commands.filter(function (c) { return c.label.toLowerCase().indexOf(q) !== -1; });
    activeIndex = 0;
    if (!filtered.length) { listEl.innerHTML = '<div class="cmdk-empty">No matching commands</div>'; return; }
    listEl.innerHTML = filtered.map(function (c, i) {
      return '<div class="cmdk-item' + (i === 0 ? " active" : "") + '" data-i="' + i + '">' +
        '<i class="ti ' + c.icon + '" aria-hidden="true"></i>' + c.label + "</div>";
    }).join("");
    listEl.querySelectorAll(".cmdk-item").forEach(function (el) {
      el.addEventListener("click", function () { run(filtered[+el.dataset.i]); });
    });
  }

  function highlight() {
    listEl.querySelectorAll(".cmdk-item").forEach(function (el, i) {
      el.classList.toggle("active", i === activeIndex);
    });
  }

  function onKey(e) {
    if (e.key === "ArrowDown") { e.preventDefault(); activeIndex = Math.min(activeIndex + 1, filtered.length - 1); highlight(); }
    else if (e.key === "ArrowUp") { e.preventDefault(); activeIndex = Math.max(activeIndex - 1, 0); highlight(); }
    else if (e.key === "Enter") { e.preventDefault(); if (filtered[activeIndex]) run(filtered[activeIndex]); }
    else if (e.key === "Escape") { closePalette(); }
  }

  function run(cmd) {
    closePalette();
    if (!cmd) return;
    if (cmd.action === "quickadd") {
      var input = document.getElementById("quick-add-input");
      if (input) input.focus();
      return;
    }
    window.location.href = cmd.url;
  }

  window.openPalette = function () {
    if (!scrim) buildPalette();
    render("");
    scrim.classList.add("open");
    inputEl.value = "";
    setTimeout(function () { inputEl.focus(); }, 20);
  };
  function closePalette() { if (scrim) scrim.classList.remove("open"); }

  document.addEventListener("keydown", function (e) {
    if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") { e.preventDefault(); window.openPalette(); }
  });

  // --- Chat ---
  function getCsrf() {
    var el = document.querySelector("[name=csrfmiddlewaretoken]");
    return el ? el.value : "";
  }
  window.sendChatMessage = function () {
    var input = document.getElementById("chat-input");
    var log = document.getElementById("chat-log");
    if (!input || !log) return;
    var q = input.value.trim();
    if (!q) return;
    log.insertAdjacentHTML("beforeend", '<div class="bubble me"></div>');
    log.lastChild.textContent = q;
    input.value = "";
    var id = "thinking-" + Date.now();
    log.insertAdjacentHTML("beforeend", '<div id="' + id + '" class="bubble ai">Thinking…</div>');
    log.scrollTop = log.scrollHeight;
    fetch("/chat/", {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-CSRFToken": getCsrf() },
      body: JSON.stringify({ question: q }),
    })
      .then(function (r) { return r.json(); })
      .then(function (d) {
        var el = document.getElementById(id);
        el.textContent = d.answer || d.error || "No response.";
        log.scrollTop = log.scrollHeight;
      })
      .catch(function () { document.getElementById(id).textContent = "Connection error. Try again."; });
  };

  document.addEventListener("DOMContentLoaded", function () {
    var log = document.getElementById("chat-log");
    if (log) log.scrollTop = log.scrollHeight;
    var chatInput = document.getElementById("chat-input");
    if (chatInput) chatInput.addEventListener("keypress", function (e) { if (e.key === "Enter") window.sendChatMessage(); });
  });
})();
