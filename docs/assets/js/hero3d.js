/* hero3d.js — the signature: an instrument-deck constellation that tells
   the Keel story. Session nodes (labeled) orbit a central ledger. On a loop:
   a decision pulses in to the core, the core logs it, propagation pulses out,
   and once per cycle two sessions on the same scope collide — the conflict.

   Desktop only (skipped on small screens, deliberately). No postprocessing:
   glow is additive sprites. Capped fps, offscreen-paused, reduced-motion aware. */

import * as THREE from "three";

const root = document.documentElement;
const canvas = document.getElementById("hero-canvas");
const labelHost = document.getElementById("hero-labels");
const small = window.matchMedia("(max-width: 860px)").matches;

if (canvas && labelHost && !small && !root.classList.contains("reduced")) {
  try { boot(); }
  catch (err) { console.warn("[keel] hero 3D disabled:", err && err.message); }
}

function glowTexture() {
  const c = document.createElement("canvas"); c.width = c.height = 128;
  const g = c.getContext("2d");
  const grd = g.createRadialGradient(64, 64, 0, 64, 64, 64);
  grd.addColorStop(0, "rgba(255,255,255,1)");
  grd.addColorStop(0.25, "rgba(255,255,255,0.55)");
  grd.addColorStop(0.55, "rgba(255,255,255,0.14)");
  grd.addColorStop(1, "rgba(255,255,255,0)");
  g.fillStyle = grd; g.fillRect(0, 0, 128, 128);
  const t = new THREE.CanvasTexture(c); t.colorSpace = THREE.SRGBColorSpace; return t;
}

function boot() {
  const TEAL = new THREE.Color("#38e8d0");
  const VIOLET = new THREE.Color("#8a7bf7");
  const AMBER = new THREE.Color("#f2b55c");
  const HEART = new THREE.Color(0xcffff6);   // cached: avoid per-frame allocation

  const renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: true, powerPreference: "high-performance" });
  renderer.setClearColor(0x000000, 0);
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 1.75));

  const scene = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(50, 1, 0.1, 100);
  camera.position.set(0, 0, 15.5);

  const rig = new THREE.Group();   // offset to the right, behind nothing
  scene.add(rig);
  const world = new THREE.Group();  // gently oscillates
  rig.add(world);

  const glow = glowTexture();

  /* ---- session nodes (labeled). A & B share api:orders → the conflict pair ---- */
  const nodes = [
    { name: "session A · api:orders", p: new THREE.Vector3(-3.3, 1.7, 1.0), conflict: true },
    { name: "session B · api:orders", p: new THREE.Vector3(-3.6, -1.9, 0.2), conflict: true },
    { name: "design · ui:checkout", p: new THREE.Vector3(2.7, 2.3, -0.6) },
    { name: "PM · spec", p: new THREE.Vector3(3.1, -1.7, 0.9) },
  ];

  /* core: ring + glow + heart */
  world.add(new THREE.Mesh(
    new THREE.TorusGeometry(1.7, 0.028, 8, 56),
    new THREE.MeshBasicMaterial({ color: TEAL, transparent: true, opacity: 0.55 })
  ));
  const coreGlow = new THREE.Sprite(new THREE.SpriteMaterial({ map: glow, color: TEAL, transparent: true, opacity: 0.85, blending: THREE.AdditiveBlending, depthWrite: false, depthTest: false }));
  coreGlow.scale.setScalar(4.6); world.add(coreGlow);
  const heart = new THREE.Mesh(new THREE.SphereGeometry(0.4, 18, 18), new THREE.MeshBasicMaterial({ color: 0xcffff6 }));
  world.add(heart);

  /* node glow sprites + spokes */
  const nodeSprites = [];
  const spokePts = [];
  nodes.forEach((n) => {
    const col = n.conflict ? TEAL : (i % 2 ? VIOLET : TEAL);   // deterministic per load
    const s = new THREE.Sprite(new THREE.SpriteMaterial({ map: glow, color: col, transparent: true, opacity: 0.95, blending: THREE.AdditiveBlending, depthWrite: false, depthTest: false }));
    s.scale.setScalar(1.15); s.position.copy(n.p); world.add(s);
    n.sprite = s; nodeSprites.push(s);
    spokePts.push(0, 0, 0, n.p.x, n.p.y, n.p.z);
  });
  const spokeGeo = new THREE.BufferGeometry();
  spokeGeo.setAttribute("position", new THREE.Float32BufferAttribute(spokePts, 3));
  world.add(new THREE.LineSegments(spokeGeo, new THREE.LineBasicMaterial({ color: TEAL, transparent: true, opacity: 0.16 })));

  /* conflict link A↔B (amber, flashes during the beat) */
  const aP = nodes[0].p, bP = nodes[1].p;
  const linkGeo = new THREE.BufferGeometry();
  linkGeo.setAttribute("position", new THREE.Float32BufferAttribute([aP.x, aP.y, aP.z, bP.x, bP.y, bP.z], 3));
  const linkMat = new THREE.LineBasicMaterial({ color: AMBER, transparent: true, opacity: 0 });
  world.add(new THREE.LineSegments(linkGeo, linkMat));

  /* ambient faint dots for depth */
  const AMB = 36;
  const ambArr = new Float32Array(AMB * 3);
  for (let i = 0; i < AMB; i++) {
    const rr = 7 + Math.random() * 9, th = Math.random() * Math.PI * 2, ph = Math.acos(2 * Math.random() - 1);
    ambArr[i * 3] = rr * Math.sin(ph) * Math.cos(th);
    ambArr[i * 3 + 1] = rr * Math.sin(ph) * Math.sin(th);
    ambArr[i * 3 + 2] = rr * Math.cos(ph);
  }
  const ambGeo = new THREE.BufferGeometry();
  ambGeo.setAttribute("position", new THREE.BufferAttribute(ambArr, 3));
  const amb = new THREE.Points(ambGeo, new THREE.PointsMaterial({ color: 0x8fb0c0, size: 0.05, transparent: true, opacity: 0.4, depthWrite: false }));
  rig.add(amb);

  /* reusable pulse sprites (world space) */
  function mkPulse() {
    const s = new THREE.Sprite(new THREE.SpriteMaterial({ map: glow, color: TEAL, transparent: true, opacity: 0, blending: THREE.AdditiveBlending, depthWrite: false, depthTest: false }));
    s.scale.setScalar(0.7); scene.add(s); return s;
  }
  const pulses = [mkPulse(), mkPulse(), mkPulse()];

  /* ---- DOM labels ---- */
  const labels = nodes.map((n) => {
    const d = document.createElement("div");
    d.className = "hero__label"; d.textContent = n.name;
    labelHost.appendChild(d); n.label = d; return d;
  });

  /* ---- sizing + right offset ---- */
  const tmp = new THREE.Vector3();
  function layout() {
    const w = canvas.clientWidth || window.innerWidth, h = canvas.clientHeight || window.innerHeight;
    renderer.setSize(w, h, false);
    camera.aspect = w / h; camera.updateProjectionMatrix();
    const halfW = Math.tan((camera.fov * Math.PI / 180) / 2) * camera.position.z * camera.aspect;
    rig.position.x = Math.min(6.4, halfW * 0.44);   // push constellation to the right
  }
  layout();
  let rt; window.addEventListener("resize", () => { clearTimeout(rt); rt = setTimeout(layout, 150); });

  /* pointer parallax */
  const ptr = { x: 0, y: 0, tx: 0, ty: 0 };
  window.addEventListener("pointermove", (e) => {
    ptr.tx = (e.clientX / window.innerWidth - 0.5) * 2;
    ptr.ty = (e.clientY / window.innerHeight - 0.5) * 2;
  }, { passive: true });

  /* scroll: dolly the constellation back + sink as you leave the hero */
  let scrollTarget = 0, scrollP = 0;
  const BASE_Z = 15.5;
  window.addEventListener("scroll", () => {
    const hh = canvas.clientHeight || window.innerHeight;
    scrollTarget = Math.min(1, (window.scrollY || window.pageYOffset || 0) / hh);
  }, { passive: true });

  /* offscreen pause */
  let visible = true;
  if ("IntersectionObserver" in window) {
    new IntersectionObserver((e) => { visible = e[0].isIntersecting; if (visible) kick(); }, { threshold: 0.01 }).observe(canvas);
  }

  /* ---- narrative timeline (seconds), loops ---- */
  const CYCLE = 10;
  function easeIO(x) { return x < 0.5 ? 2 * x * x : 1 - Math.pow(-2 * x + 2, 2) / 2; }
  function worldOf(localVec) { return world.localToWorld(localVec.clone()); }

  function runPhases(tc) {
    pulses.forEach((p) => (p.material.opacity = 0));
    let coreBoost = 0, linkFlash = 0, amberNodes = false;

    // record: node A → core
    if (tc >= 1.6 && tc < 3.2) {
      const f = easeIO((tc - 1.6) / 1.6);
      const p = pulses[0];
      p.material.color.copy(TEAL);
      p.position.copy(worldOf(nodes[0].p).lerp(worldOf(new THREE.Vector3(0, 0, 0)), f));
      p.material.opacity = Math.sin(f * Math.PI) * 0.95;
      p.scale.setScalar(0.55 + f * 0.25);
    }
    // core logs it
    if (tc >= 3.2 && tc < 3.9) coreBoost = Math.sin(((tc - 3.2) / 0.7) * Math.PI);

    // propagate: core → nodes C and D (violet)
    if (tc >= 3.9 && tc < 5.6) {
      const f = easeIO((tc - 3.9) / 1.7);
      [2, 3].forEach((ni, k) => {
        const p = pulses[k + 1]; p.material.color.copy(VIOLET);
        p.position.copy(worldOf(new THREE.Vector3(0, 0, 0)).lerp(worldOf(nodes[ni].p), f));
        p.material.opacity = Math.sin(f * Math.PI) * 0.9; p.scale.setScalar(0.5 + f * 0.2);
      });
    }
    // conflict: A↔B link flashes amber, A/B labels amber, amber pulse along link
    if (tc >= 6.3 && tc < 8.0) {
      const f = (tc - 6.3) / 1.7;
      linkFlash = Math.sin(f * Math.PI) * 0.85; amberNodes = true;
      const p = pulses[0]; p.material.color.copy(AMBER);
      p.position.copy(worldOf(nodes[0].p).lerp(worldOf(nodes[1].p), easeIO(f)));
      p.material.opacity = Math.sin(f * Math.PI) * 0.95; p.scale.setScalar(0.6);
    }

    linkMat.opacity = linkFlash;
    heart.material.color.copy(amberNodes ? AMBER : HEART);
    coreGlow.material.color.copy(amberNodes ? AMBER : TEAL);
    nodes[0].sprite.material.color.copy(amberNodes ? AMBER : TEAL);
    nodes[1].sprite.material.color.copy(amberNodes ? AMBER : TEAL);
    nodes[0].label.classList.toggle("amber", amberNodes);
    nodes[1].label.classList.toggle("amber", amberNodes);
    return coreBoost;
  }

  /* ---- loop ---- */
  const FRAME = 1000 / 40;
  let firstFrame = true, last = 0, raf = 0;
  const clock = new THREE.Clock();

  function kick() { if (!raf) raf = requestAnimationFrame(frame); }
  function frame(now) {
    raf = 0;
    if (!visible || document.hidden) return;
    raf = requestAnimationFrame(frame);
    if (now - last < FRAME) return;
    last = now;

    const t = clock.getElapsedTime();
    ptr.x += (ptr.tx - ptr.x) * 0.05; ptr.y += (ptr.ty - ptr.y) * 0.05;
    scrollP += (scrollTarget - scrollP) * 0.08;
    camera.position.z = BASE_Z + scrollP * 8;          // dolly back on scroll
    rig.position.y = scrollP * -1.6;                    // and sink slightly
    world.rotation.y = Math.sin(t * 0.14) * 0.3 + ptr.x * 0.22 + scrollP * 0.5;
    world.rotation.x = Math.sin(t * 0.1) * 0.06 + ptr.y * 0.16;
    amb.rotation.y = t * 0.02;

    const coreBoost = runPhases(t % CYCLE);
    const breathe = 1 + Math.sin(t * 1.4) * 0.05;
    heart.scale.setScalar(breathe + coreBoost * 0.5);
    coreGlow.scale.setScalar(4.6 * (1 + Math.sin(t * 1.4) * 0.04) + coreBoost * 1.4);

    renderer.render(scene, camera);

    // project labels to screen
    const w = canvas.clientWidth, h = canvas.clientHeight;
    nodes.forEach((n) => {
      n.sprite.getWorldPosition(tmp); tmp.project(camera);
      const x = (tmp.x * 0.5 + 0.5) * w, y = (-tmp.y * 0.5 + 0.5) * h;
      n.label.style.left = x + "px";
      n.label.style.top = (y - 22) + "px";
      if (tmp.z < 1) n.label.classList.add("on"); else n.label.classList.remove("on");
    });

    if (firstFrame) { firstFrame = false; canvas.classList.add("is-live"); }
  }

  document.addEventListener("visibilitychange", () => { if (!document.hidden) kick(); });
  kick();

  window.addEventListener("pagehide", () => { if (raf) cancelAnimationFrame(raf); renderer.dispose(); }, { once: true });
}
