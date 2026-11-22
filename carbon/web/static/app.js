/* CARBON web client. Vendored: cytoscape.js 3.35.0 (MIT), see vendor/. */
(function () {
  "use strict";
  var $ = function (id) { return document.getElementById(id); };
  function el(tag, cls, text) {
    var e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text != null) e.textContent = text;
    return e;
  }

  // Tool parameter forms. kind: int | num | str | bool | enum. Mirrors the server schemas.
  var WRITES = { can_inject: 1, can_replay: 1, uds_session: 1, uds_security_access: 1, uds_clear_dtc: 1 };
  var PARAMS = {
    can_sniff: [["count", "int"], ["timeout", "num"]],
    can_dump: [["path", "str", 1], ["count", "int"], ["timeout", "num"]],
    can_replay: [["path", "str", 1]],
    can_inject: [["arb_id", "int", 1], ["data_hex", "str"], ["extended", "bool"]],
    uds_scan: [],
    uds_session: [["session", "enum", 0, ["default", "extended"]]],
    uds_security_access: [["level", "int"]],
    uds_read_did: [["did", "int"]],
    uds_read_dtc: [["status_mask", "int"]],
    uds_clear_dtc: [["group", "int"]]
  };
  var LEGEND = [
    ["bus", "CAN bus", "<rect x='1' y='3' width='14' height='8' rx='3' fill='none' stroke='#e3a23b' stroke-width='1.5'/>"],
    ["ecu", "ECU on the bus", "<rect x='2' y='2' width='12' height='10' fill='none' stroke='#e4dfd1' stroke-width='1.5'/>"],
    ["service", "UDS service", "<circle cx='8' cy='7' r='4.5' fill='none' stroke='#6fae9c' stroke-width='1.5'/>"],
    ["level", "security level", "<path d='M8 1 15 7 8 13 1 7z' fill='none' stroke='#6fae9c' stroke-width='1.5'/>"],
    ["dtc", "fault code", "<path d='M8 1.5 14.5 12.5H1.5z' fill='none' stroke='#c8503c' stroke-width='1.5'/>"]
  ];

  var state = null, cy = null, selected = null, openTool = null;
  var jopen = {};

  // ---------- API ----------
  function runTool(name, params) {
    $("run-err").textContent = "";
    return fetch("/api/tool/" + encodeURIComponent(name), {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify(params || {})
    }).then(function (r) {
      return r.json().then(function (j) {
        if (!r.ok) $("run-err").textContent = name + ": " + (j.error || r.status);
        return j;
      });
    }).catch(function (e) { $("run-err").textContent = name + ": " + e; });
  }

  // ---------- map ----------
  function initCy() {
    cy = cytoscape({
      container: $("cy"), wheelSensitivity: 0.3, minZoom: 0.3, maxZoom: 2.5,
      style: [
        { selector: "node", style: {
          label: "data(label)", color: "#e4dfd1", "font-family": "IBM Plex Mono, Menlo, monospace",
          "font-size": 11, "text-valign": "bottom", "text-margin-y": 5,
          "background-color": "#1a1915", "border-width": 1.5, "border-color": "#e4dfd1",
          width: 26, height: 26 } },
        { selector: "node[type='bus']", style: { shape: "round-rectangle", width: 120, height: 22,
          "border-color": "#e3a23b", "text-valign": "center", "text-margin-y": 0, color: "#e3a23b" } },
        { selector: "node[type='ecu']", style: { shape: "rectangle", width: 34, height: 26 } },
        { selector: "node[type='service']", style: { shape: "ellipse", width: 20, height: 20, "border-color": "#6fae9c" } },
        { selector: "node[type='level']", style: { shape: "diamond", width: 30, height: 30, "border-color": "#6fae9c" } },
        { selector: "node[state='unlocked']", style: { "background-color": "#6fae9c" } },
        { selector: "node[type='dtc']", style: { shape: "triangle", width: 22, height: 22, "border-color": "#c8503c" } },
        { selector: "edge", style: { width: 1, "line-color": "#4a473b", "curve-style": "taxi",
          "taxi-direction": "downward", "target-arrow-shape": "none" } },
        { selector: "node.cur", style: { "border-color": "#e3a23b", "border-width": 3, color: "#e3a23b" } },
        { selector: "node:selected", style: { "underlay-color": "#e3a23b", "underlay-opacity": .18, "underlay-padding": 6 } }
      ]
    });
    cy.on("tap", "node", function (e) { select(e.target.id()); });
    cy.on("dbltap", "node", function (e) { runNode(e.target); });
    cy.on("tap", function (e) { if (e.target === cy) select(null); });
    $("cy").addEventListener("keydown", mapKey);
  }

  function svcCode(label) { var n = Number(label); return isNaN(n) ? null : n; }

  // node -> {tool, params, label}; null when nothing sensible to run.
  function actionFor(n) {
    var t = n.data("type"), c;
    if (t === "bus") return { tool: "can_sniff", params: { count: 20, timeout: 2 }, label: "Sniff the bus" };
    if (t === "ecu") return { tool: "uds_scan", params: {}, label: "Scan for UDS services" };
    if (t === "level") return { tool: "uds_security_access", params: {}, label: "Request security access" };
    if (t === "dtc") return { tool: "uds_read_dtc", params: {}, label: "Re-read fault codes" };
    if (t === "service") {
      c = svcCode(n.data("label"));
      if (c === 0x10) return { tool: "uds_session", params: { session: "extended" }, label: "Open extended session" };
      if (c === 0x27) return { tool: "uds_security_access", params: {}, label: "Request security access" };
      if (c === 0x19) return { tool: "uds_read_dtc", params: {}, label: "Read fault codes" };
      if (c === 0x22) return { tool: "uds_read_did", params: {}, label: "Read a data identifier" };
      if (c === 0x14) return { tool: "uds_clear_dtc", params: {}, label: "Clear fault codes" };
    }
    return null;
  }

  function runNode(n) {
    var a = n && actionFor(n);
    if (a) runTool(a.tool, a.params);
  }

  function select(id) {
    selected = id;
    if (cy) { cy.nodes().unselect(); if (id) cy.getElementById(id).select(); }
    renderSel();
  }

  function renderSel() {
    var body = $("sel-body"), n = selected && cy ? cy.getElementById(selected) : null;
    body.textContent = "";
    if (!n || n.empty()) { body.className = "meta"; body.textContent = "Click a node, or use the arrow keys."; return; }
    body.className = "";
    body.appendChild(el("div", "name", n.data("label")));
    var meta = n.data("type") + (n.data("state") ? "  /  " + n.data("state") : "") + "  /  " + n.id();
    body.appendChild(el("div", "meta mono", meta));
    var a = actionFor(n), row = el("div", "actions");
    if (a) {
      var b = el("button", "primary", a.label + "  (" + a.tool + ")");
      b.onclick = function () { runNode(n); };
      row.appendChild(b);
    } else row.appendChild(el("span", "meta", "No one-click action for this node."));
    body.appendChild(row);
  }

  function mapKey(e) {
    if (!cy) return;
    var dirs = { ArrowLeft: [-1, 0], ArrowRight: [1, 0], ArrowUp: [0, -1], ArrowDown: [0, 1] };
    if (e.key === "Enter") { var s = selected && cy.getElementById(selected); if (s && s.nonempty()) runNode(s); e.preventDefault(); return; }
    var d = dirs[e.key];
    if (!d) return;
    e.preventDefault();
    var cur = selected && cy.getElementById(selected), nodes = cy.nodes();
    if (!cur || cur.empty()) { if (nodes.nonempty()) select(nodes[0].id()); return; }
    var p = cur.position(), best = null, bs = Infinity;
    nodes.forEach(function (n) {
      if (n.id() === cur.id()) return;
      var q = n.position(), dx = q.x - p.x, dy = q.y - p.y;
      var along = dx * d[0] + dy * d[1], across = Math.abs(dx * d[1]) + Math.abs(dy * d[0]);
      if (along <= 1) return;
      var score = along + across * 2;
      if (score < bs) { bs = score; best = n; }
    });
    if (best) select(best.id());
  }

  var lastShape = "";
  function renderSurface(s) {
    $("empty").style.display = s.nodes.length > 1 ? "none" : "";
    var ids = {};
    cy.batch(function () {
      s.nodes.forEach(function (n) {
        ids[n.id] = 1;
        var ex = cy.getElementById(n.id);
        var d = { id: n.id, type: n.type, label: n.label, state: n.state || null };
        if (ex.empty()) cy.add({ group: "nodes", data: d }); else ex.data(d);
      });
      cy.nodes().forEach(function (n) { if (!ids[n.id()]) cy.remove(n); });
      var eids = {};
      s.edges.forEach(function (e) {
        var id = e.source + ">" + e.target; eids[id] = 1;
        if (cy.getElementById(id).empty()) cy.add({ group: "edges", data: { id: id, source: e.source, target: e.target } });
      });
      cy.edges().forEach(function (e) { if (!eids[e.id()]) cy.remove(e); });
      cy.nodes().removeClass("cur");
      if (s.current) cy.getElementById(s.current).addClass("cur");
    });
    var shape = s.nodes.map(function (n) { return n.id; }).sort().join("|");
    if (shape !== lastShape) {
      lastShape = shape;
      cy.layout({ name: "breadthfirst", directed: true, spacingFactor: 1.25, padding: 50,
        roots: cy.nodes("[type='bus']") }).run();
      cy.fit(undefined, 60);
      if (cy.zoom() > 1.4) { cy.zoom(1.4); cy.center(); }
    }
    if (selected && cy.getElementById(selected).empty()) selected = null;
    else if (selected) cy.getElementById(selected).select();
    renderSel();
  }

  // ---------- panels ----------
  function renderStatus(st) {
    var s = st.surface || {}, sess = s.session || {};
    $("s-bus").textContent = st.channel || "-";
    $("s-if").textContent = st.interface || "-";
    $("s-sess").textContent = sess.active || "none";
    $("s-sec").textContent = sess.unlocked ? "unlocked" : "locked";
  }

  function renderTools(names) {
    var ul = $("tools");
    ul.textContent = "";
    names.forEach(function (name) {
      var li = el("li"), row = el("div", "trow");
      var tn = el("span", "tn", name);
      tn.onclick = function () { openTool = openTool === name ? null : name; renderTools(names); };
      row.appendChild(tn);
      if (WRITES[name]) row.appendChild(el("span", "tag", "WRITES"));
      var go = el("button", null, "Run");
      row.appendChild(go);
      li.appendChild(row);
      var spec = PARAMS[name] || [], inputs = {};
      if (openTool === name && spec.length) {
        var f = el("div", "tform");
        spec.forEach(function (p) {
          f.appendChild(el("label", null, p[0] + (p[2] ? " *" : "")));
          var i;
          if (p[1] === "enum") {
            i = el("select");
            p[3].forEach(function (o) { var op = el("option", null, o); op.value = o; i.appendChild(op); });
          } else if (p[1] === "bool") { i = el("input"); i.type = "checkbox"; }
          else { i = el("input"); i.type = "text"; i.placeholder = p[1] === "int" ? "e.g. 0x7e0 or 2016" : ""; }
          inputs[p[0]] = i;
          f.appendChild(i);
        });
        li.appendChild(f);
      }
      go.onclick = function () {
        var body = {}, bad = null;
        spec.forEach(function (p) {
          var i = inputs[p[0]];
          if (!i) { if (p[2]) bad = p[0]; return; }
          var v;
          if (p[1] === "bool") { if (i.checked) body[p[0]] = true; return; }
          v = i.value.trim();
          if (v === "") { if (p[2]) bad = p[0]; return; }
          if (p[1] === "int" || p[1] === "num") { v = Number(v); if (isNaN(v)) bad = p[0]; }
          body[p[0]] = v;
        });
        if (bad) {
          if (openTool !== name) { openTool = name; renderTools(names); }
          $("run-err").textContent = name + ": fill in " + bad; return;
        }
        runTool(name, body);
      };
      ul.appendChild(li);
    });
  }

  function renderJournal(hist) {
    var ul = $("journal"), q = $("filter").value.toLowerCase();
    ul.textContent = "";
    hist.slice().reverse().forEach(function (h, idx) {
      var key = h.started_at + h.tool;
      var text = (h.tool + " " + h.summary).toLowerCase();
      if (q && text.indexOf(q) < 0) return;
      var li = el("li");
      li.appendChild(el("span", "t", (h.started_at || "").slice(11, 19)));
      li.appendChild(el("span", h.ok ? "ok" : "err", h.ok ? "OK " : "ERR"));
      li.appendChild(document.createTextNode(" "));
      li.appendChild(el("span", "tool", h.tool));
      li.appendChild(el("span", "sum", h.summary || ""));
      if (jopen[key]) li.appendChild(el("pre", null, JSON.stringify(h.data, null, 2)));
      li.onclick = function () { jopen[key] = !jopen[key]; renderJournal(hist); };
      ul.appendChild(li);
    });
  }

  function renderLegend() {
    var ul = $("legend-list");
    LEGEND.forEach(function (l) {
      var li = el("li"), s = el("span");
      s.innerHTML = "<svg viewBox='0 0 16 14' aria-hidden='true'>" + l[2] + "</svg>"; // static literals only
      li.appendChild(s.firstChild);
      li.appendChild(el("span", "k", l[0]));
      li.appendChild(el("span", null, l[1]));
      ul.appendChild(li);
    });
    var cur = el("li");
    cur.appendChild(el("span", null, "■")).style.color = "#e3a23b";
    cur.appendChild(el("span", "k", "amber"));
    cur.appendChild(el("span", null, "last thing you touched"));
    ul.appendChild(cur);
  }

  function apply(st) {
    state = st;
    renderStatus(st);
    renderSurface(st.surface || { nodes: [], edges: [], current: null });
    renderTools(st.tools || []);
    renderJournal(st.history || []);
  }

  // ---------- approvals ----------
  var modals = {}; // id -> element (dedupe)
  function showApproval(a) {
    if (modals[a.id]) return;
    var m = el("div", "modal");
    m.setAttribute("role", "alertdialog");
    m.appendChild(el("h2", null, "Approval required"));
    m.appendChild(el("div", "tool", a.tool));
    m.appendChild(el("div", "why", "This action was requested and will not run until you decide."));
    m.appendChild(el("pre", null, JSON.stringify(a.params, null, 2)));
    var row = el("div", "row");
    row.appendChild(el("span", "q", "a approve / d deny"));
    var deny = el("button", "danger", "Deny"), ok = el("button", "primary", "Approve");
    function decide(d) {
      deny.disabled = ok.disabled = true;
      fetch("/api/approvals/" + encodeURIComponent(a.id), {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ decision: d })
      }).then(function (r) { if (!r.ok) dismiss(a.id); }).catch(function () { deny.disabled = ok.disabled = false; });
    }
    deny.onclick = function () { decide("deny"); };
    ok.onclick = function () { decide("approve"); };
    m._decide = decide;
    row.appendChild(deny); row.appendChild(ok);
    m.appendChild(row);
    modals[a.id] = m;
    $("modals").appendChild(m);
    deny.focus(); // safe default: Enter never approves by accident
  }
  function dismiss(id) {
    var m = modals[id];
    if (!m) return;
    delete modals[id];
    m.remove();
    var rest = $("modals").lastElementChild;
    if (rest) { var b = rest.querySelector("button"); if (b) b.focus(); }
  }
  document.addEventListener("keydown", function (e) {
    var top = $("modals").lastElementChild;
    if (top && !e.ctrlKey && !e.metaKey) {
      if (e.key === "a") { top._decide("approve"); e.preventDefault(); }
      else if (e.key === "d" || e.key === "Escape") { top._decide("deny"); e.preventDefault(); }
      return;
    }
    if (/^(INPUT|SELECT|TEXTAREA)$/.test(e.target.tagName)) {
      if (e.key === "Escape") e.target.blur();
      return;
    }
    if (e.key === "/") { $("filter").focus(); e.preventDefault(); }
    else if (e.key === "?") $("legend").classList.toggle("min");
  });

  // ---------- SSE ----------
  function connect() {
    var es = new EventSource("/api/events");
    es.onopen = function () { $("link").className = "kv up"; $("link").textContent = "live"; };
    es.onerror = function () { $("link").className = "kv"; $("link").textContent = "reconnecting"; };
    es.addEventListener("state", function (e) { apply(JSON.parse(e.data)); });
    es.addEventListener("approval", function (e) { showApproval(JSON.parse(e.data)); });
    es.addEventListener("pending", function (e) {
      var list = JSON.parse(e.data), keep = {};
      list.forEach(function (a) { keep[a.id] = 1; showApproval(a); });
      Object.keys(modals).forEach(function (id) { if (!keep[id]) dismiss(id); }); // resolved while disconnected
    });
    es.addEventListener("resolved", function (e) { dismiss(JSON.parse(e.data).id); });
  }

  initCy();
  renderLegend();
  $("filter").addEventListener("input", function () { if (state) renderJournal(state.history || []); });
  fetch("/api/state").then(function (r) { return r.json(); }).then(apply).catch(function () {});
  connect();
})();
