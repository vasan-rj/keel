// Approve page for the device-code connect flow.
// Firebase/Google sign-in is optional: if window.KEEL_FIREBASE is configured we use
// it to obtain an ID token; otherwise the "paste an ID token" field is the fallback.
(function () {
  "use strict";
  var idToken = null;
  var $ = function (id) { return document.getElementById(id); };
  var status = $("status");
  function setStatus(msg, cls) { status.textContent = msg; status.className = cls || ""; }
  function refreshApproveEnabled() {
    var manual = ($("idtoken") && $("idtoken").value.trim()) || "";
    $("approve").disabled = !(idToken || manual);
  }

  if ($("idtoken")) $("idtoken").addEventListener("input", refreshApproveEnabled);

  var cfg = window.KEEL_FIREBASE;
  if (cfg && window.firebase) {
    try {
      firebase.initializeApp(cfg);
      $("google").addEventListener("click", function () {
        var provider = new firebase.auth.GoogleAuthProvider();
        firebase.auth().signInWithPopup(provider).then(function (res) {
          return res.user.getIdToken();
        }).then(function (tok) {
          idToken = tok;
          $("who").textContent = "signed in";
          refreshApproveEnabled();
        }).catch(function (e) { setStatus("sign-in failed: " + e.message, "err"); });
      });
    } catch (e) {
      setStatus("Firebase init failed; use the ID-token field below.", "err");
    }
  } else {
    $("google").disabled = true;
    $("who").textContent = "Google sign-in not configured — use the ID-token field below.";
  }

  $("approve").addEventListener("click", function () {
    var code = $("user_code").value.trim().toUpperCase();
    var scope = $("scope").value;
    var tok = idToken || ($("idtoken") ? $("idtoken").value.trim() : "");
    if (!code) { setStatus("enter the device code", "err"); return; }
    if (!tok) { setStatus("sign in or paste an ID token", "err"); return; }
    $("approve").disabled = true;
    setStatus("approving…");
    fetch("/connect/approve", {
      method: "POST",
      headers: { "Authorization": "Bearer " + tok, "Content-Type": "application/json" },
      body: JSON.stringify({ user_code: code, scope: scope })
    }).then(function (r) {
      return r.json().then(function (b) { return { ok: r.ok, body: b }; });
    }).then(function (res) {
      if (res.ok) {
        setStatus("Approved. The agent now holds a " + res.body.agent.scope + " token.", "ok");
      } else {
        setStatus("failed: " + (res.body.error || "unknown"), "err");
        $("approve").disabled = false;
      }
    }).catch(function (e) {
      setStatus("request failed: " + e.message, "err");
      $("approve").disabled = false;
    });
  });
})();
