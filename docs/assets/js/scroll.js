/* scroll.js — scroll-driven motion: reveals, live-scene stagger, a top
   progress bar, parallax, and a pipeline that fills step-by-step as you
   scrub past it. GSAP+Lenis when present, IntersectionObserver fallback,
   no-op under reduced motion. */
(function () {
  "use strict";

  window.__keelScrollReady = true;
  var root = document.documentElement;
  var reduced = root.classList.contains("reduced");
  var reveals = [].slice.call(document.querySelectorAll("[data-reveal], [data-scene]"));
  var steps = [].slice.call(document.querySelectorAll(".pipe__step"));
  var bar = document.getElementById("scrollbar");

  function showAll() { reveals.forEach(function (el) { el.classList.add("is-in"); }); }
  function litUpTo(n) { steps.forEach(function (s, i) { s.classList.toggle("is-lit", i < n); }); }

  if (reduced) { showAll(); litUpTo(steps.length); return; }

  var hasGSAP = !!(window.gsap && window.ScrollTrigger);

  /* ---- Lenis ---- */
  var lenis = null;
  if (window.Lenis) {
    try { lenis = new window.Lenis({ lerp: 0.1, smoothWheel: true, wheelMultiplier: 0.9 }); root.classList.add("lenis"); }
    catch (e) { lenis = null; }
  }

  /* anchor links routed through Lenis (CSS smooth-scroll is intentionally off) */
  document.querySelectorAll('a[href^="#"]').forEach(function (a) {
    a.addEventListener("click", function (e) {
      var id = a.getAttribute("href"); if (id.length < 2) return;
      var target = document.querySelector(id); if (!target) return;
      e.preventDefault();
      if (lenis) lenis.scrollTo(target, { offset: -76 }); else target.scrollIntoView();
      history.pushState(null, "", id);
    });
  });

  function setBar(p) { if (bar) bar.style.transform = "scaleX(" + p + ")"; }

  if (hasGSAP) {
    var gsap = window.gsap, ST = window.ScrollTrigger;
    gsap.registerPlugin(ST);

    if (lenis) {
      lenis.on("scroll", ST.update);
      gsap.ticker.add(function (t) { lenis.raf(t * 1000); });
      gsap.ticker.lagSmoothing(0);
    }

    // staggered reveals
    ST.batch("[data-reveal], [data-scene]", {
      start: "top 88%",
      onEnter: function (b) { b.forEach(function (el, i) { setTimeout(function () { el.classList.add("is-in"); }, i * 80); }); }
    });

    // top progress bar
    ST.create({ start: 0, end: "max", onUpdate: function (self) { setBar(self.progress); } });

    // hero copy drifts as you leave
    gsap.to(".hero__inner", { yPercent: 10, opacity: 0.55, ease: "none",
      scrollTrigger: { trigger: ".hero", start: "top top", end: "bottom top", scrub: true } });

    // problem band: quote and body move at different speeds
    if (document.querySelector(".band")) {
      gsap.to(".band__quote", { yPercent: -14, ease: "none",
        scrollTrigger: { trigger: ".band", start: "top bottom", end: "bottom top", scrub: true } });
      gsap.to(".band__body", { yPercent: 6, ease: "none",
        scrollTrigger: { trigger: ".band", start: "top bottom", end: "bottom top", scrub: true } });
    }

    // jobs: each row slides its number + text in from the left on enter
    gsap.utils.toArray(".job").forEach(function (job) {
      gsap.from(job.querySelector(".job__n"), {
        scrollTrigger: { trigger: job, start: "top 85%" },
        x: -24, opacity: 0, duration: 0.6, ease: "power2.out"
      });
    });

    // pipeline fills step-by-step as the section scrubs past
    if (steps.length) {
      ST.create({ trigger: ".how", start: "top 68%", end: "bottom 78%", scrub: 0.4,
        onUpdate: function (self) { litUpTo(Math.round(self.progress * steps.length)); } });
    }

    ST.refresh();
    return;
  }

  /* ---- fallback: IntersectionObserver ---- */
  setBar(0);
  window.addEventListener("scroll", function () {
    var h = document.documentElement, max = h.scrollHeight - h.clientHeight;
    setBar(max > 0 ? h.scrollTop / max : 0);
  }, { passive: true });

  if ("IntersectionObserver" in window) {
    var io = new IntersectionObserver(function (entries) {
      entries.forEach(function (e) { if (e.isIntersecting) { e.target.classList.add("is-in"); io.unobserve(e.target); } });
    }, { rootMargin: "0px 0px -12% 0px" });
    reveals.forEach(function (el) { io.observe(el); });

    var pipe = document.querySelector(".pipe");
    if (pipe) new IntersectionObserver(function (es) { if (es[0].isIntersecting) litUpTo(steps.length); },
      { threshold: 0.3 }).observe(pipe);
  } else { showAll(); litUpTo(steps.length); }
})();
