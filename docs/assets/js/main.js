/* main.js — nav state, copy-to-clipboard, hero reveal, demo lazy-load.
   No external deps; safe to run before GSAP/Three load. */
(function () {
  "use strict";

  /* ---------- nav: stick + blur after a little scroll ---------- */
  var nav = document.getElementById("nav");
  function onScroll() {
    if (!nav) return;
    nav.classList.toggle("is-stuck", window.scrollY > 24);
  }
  window.addEventListener("scroll", onScroll, { passive: true });
  onScroll();

  /* ---------- hero reveal (runs even when 3D is disabled) ---------- */
  var hero = document.getElementById("hero");
  function readyHero() { if (hero) hero.classList.add("is-ready"); }
  // defer script runs after DOM parse — reveal immediately so the H1 (the LCP element)
  // is never gated behind window.load / the three.js module download.
  if (document.readyState !== "loading") readyHero();
  else document.addEventListener("DOMContentLoaded", readyHero);

  /* ---------- reveal safety: if scroll.js 404s / fails, show all content ---------- */
  setTimeout(function () {
    if (!window.__keelScrollReady) {
      document.querySelectorAll("[data-reveal], [data-scene]").forEach(function (el) { el.classList.add("is-in"); });
    }
  }, 2500);

  /* ---------- copy-to-clipboard (install chips + terminal) ---------- */
  function flash(el) {
    var original = el.getAttribute("data-label-original");
    if (original === null) {
      original = labelText(el);
      el.setAttribute("data-label-original", original);
    }
    el.classList.add("is-copied");
    setLabel(el, "Copied ✓");
    var live = document.getElementById("copy-live");
    if (live) live.textContent = "Copied to clipboard";
    window.clearTimeout(el._copyT);
    el._copyT = window.setTimeout(function () {
      el.classList.remove("is-copied");
      setLabel(el, original);
    }, 1600);
  }

  // elements mark their label node with [data-copy-label]; fall back to the button itself
  function labelNode(el) { return el.querySelector("[data-copy-label]") || el; }
  function labelText(el) { return labelNode(el).textContent; }
  function setLabel(el, txt) {
    var n = labelNode(el);
    // keep inner <code> if present (inline install button)
    var code = n.querySelector && n.querySelector("code");
    if (code) { code.textContent = txt; } else { n.textContent = txt; }
  }

  function doCopy(text, el) {
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(text).then(function () { flash(el); }).catch(function () { legacy(text, el); });
    } else { legacy(text, el); }
  }
  function legacy(text, el) {
    try {
      var ta = document.createElement("textarea");
      ta.value = text; ta.setAttribute("readonly", "");
      ta.style.position = "absolute"; ta.style.left = "-9999px";
      document.body.appendChild(ta); ta.select();
      document.execCommand("copy"); document.body.removeChild(ta);
      flash(el);
    } catch (e) { /* no-op */ }
  }

  document.querySelectorAll("[data-copy]").forEach(function (el) {
    el.addEventListener("click", function () { doCopy(el.getAttribute("data-copy"), el); });
  });

  /* ---------- demo video: only pull bytes once near viewport ---------- */
  var video = document.querySelector(".demo__video");
  if (video && "IntersectionObserver" in window) {
    var io = new IntersectionObserver(function (entries) {
      entries.forEach(function (e) {
        if (e.isIntersecting) { video.preload = "metadata"; io.disconnect(); }
      });
    }, { rootMargin: "400px" });
    io.observe(video);
  }
})();
