/* Hyperbolic replay viewer. Static: reads window.HYPERBOLIC_VIEWER_DATA from data/viewer.js. */
(function () {
  "use strict";

  var DATA = window.HYPERBOLIC_VIEWER_DATA;
  var reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  var $ = function (id) { return document.getElementById(id); };
  var ZONE_ORDER = ["nor", "eas", "sou", "wes", "cor"];

  var state = {
    sc: null, idx: 0, t: 0, playing: false, speed: 10, zone: "cor",
    lastHour: -1, lastFrame: 0, shown: {}, charts: [], events: []
  };

  // ---------- helpers ----------
  function el(tag, cls, text) {
    var e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text != null) e.textContent = text;
    return e;
  }
  function svgEl(tag, attrs) {
    var e = document.createElementNS("http://www.w3.org/2000/svg", tag);
    for (var k in attrs) e.setAttribute(k, attrs[k]);
    return e;
  }
  function css(name) { return getComputedStyle(document.documentElement).getPropertyValue(name).trim(); }
  function clamp(v, a, b) { return Math.max(a, Math.min(b, v)); }
  function lerp(a, b, w) { return a + (b - a) * w; }
  function sample(arr, t) {
    var i = Math.floor(t), w = t - i;
    if (i >= arr.length - 1) return arr[arr.length - 1];
    var a = arr[i], b = arr[i + 1];
    if (a == null || b == null) return a == null ? b : a;
    return lerp(a, b, w);
  }
  function fmt(v, d) {
    if (v == null || isNaN(v)) return "n/a";
    return v.toLocaleString("en-US", { minimumFractionDigits: d, maximumFractionDigits: d });
  }
  function pct(a, b) { return (b == null || a == null || Math.abs(b) < 1e-12) ? null : (a - b) / Math.abs(b) * 100; }
  function dayHour(sc, i, atStart) {
    var t = sc.time_s[clamp(Math.round(i), 0, sc.hours - 1)] - (atStart ? 3600 : 0);
    var day = Math.floor((t - sc.start_time_s) / 86400) + 1;
    var hod = Math.round((t % 86400) / 3600) % 24;
    return { day: day, hour: hod, label: "Day " + day + ", " + String(hod).padStart(2, "0") + ":00" };
  }
  var ICON = {
    up: '<svg viewBox="0 0 12 12" aria-hidden="true"><path d="M6 2v8M2.5 5.5 6 2l3.5 3.5" stroke="currentColor" stroke-width="1.6" fill="none"/></svg>',
    down: '<svg viewBox="0 0 12 12" aria-hidden="true"><path d="M6 10V2M2.5 6.5 6 10l3.5-3.5" stroke="currentColor" stroke-width="1.6" fill="none"/></svg>',
    play: "M4 2.5v11l9-5.5z",
    pause: "M4 2.5h3v11H4zM9 2.5h3v11H9z"
  };
  var STATUS = {
    ok: { label: "OK", icon: "✓" },
    clamped: { label: "Clamped", icon: "▲" },
    fallback: { label: "Fallback", icon: "↺" }
  };
  function statusTag(status) {
    var s = STATUS[status] || STATUS.ok;
    var t = el("span", "tag " + status);
    t.setAttribute("aria-label", s.label);
    t.appendChild(el("span", "", s.icon));
    t.appendChild(el("span", "tag-label", s.label));
    return t;
  }

  // ---------- theme ----------
  function setTheme(theme) {
    document.documentElement.setAttribute("data-theme", theme);
    try { localStorage.setItem("hyperbolic-theme", theme); } catch (e) { /* storage may be blocked */ }
    $("theme-toggle").setAttribute("aria-label", theme === "dark" ? "Switch to light theme" : "Switch to dark theme");
    $("theme-icon").setAttribute("d", theme === "dark"
      ? "M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z"
      : "M12 4V2m0 20v-2m8-8h2M2 12h2m13.7-5.7 1.4-1.4M4.9 19.1l1.4-1.4m0-11.4L4.9 4.9m14.2 14.2-1.4-1.4M12 7a5 5 0 1 0 0 10 5 5 0 0 0 0-10z");
    document.querySelector('meta[name="theme-color"]').setAttribute("content", css("--bg"));
    if (state.sc) { buildPlans(); drawCharts(); frame(true); }
  }

  // ---------- zone color ----------
  var colorCache = {};
  function zoneColor(temp, lo, hi) {
    var key = css("--band") + css("--warm") + css("--cool") + css("--surface-1");
    if (!colorCache[key]) {
      colorCache[key] = {
        warm: d3.interpolateLab(css("--band"), css("--warm")),
        cool: d3.interpolateLab(css("--band"), css("--cool")),
        surface: css("--surface-1")
      };
    }
    var c = colorCache[key];
    var base, depth;
    if (temp > hi) { base = c.warm(clamp(0.4 + (temp - hi) / 3, 0.4, 1)); depth = 0.42 + clamp((temp - hi) / 3, 0, 1) * 0.24; }
    else if (temp < lo) { base = c.cool(clamp(0.4 + (lo - temp) / 3, 0.4, 1)); depth = 0.42 + clamp((lo - temp) / 3, 0, 1) * 0.24; }
    else {
      // Inside the band the tint leans a little cool near the lower limit and warm near the upper.
      var p = (temp - lo) / Math.max(hi - lo, 0.1);
      base = p < 0.5 ? c.cool((0.5 - p) * 0.32) : c.warm((p - 0.5) * 0.32);
      depth = 0.42;
    }
    return d3.interpolateLab(c.surface, base)(depth);
  }

  // ---------- floor plans ----------
  var W, H, D, GEOM;
  function geometry() {
    var narrow = window.innerWidth < 640;
    W = 320; H = narrow ? 260 : 214; D = narrow ? 84 : 62;
    GEOM = {
      nor: { pts: [[0, 0], [W, 0], [W - D, D], [D, D]], c: [W / 2, D / 2 + 1] },
      sou: { pts: [[0, H], [W, H], [W - D, H - D], [D, H - D]], c: [W / 2, H - D / 2 - 1] },
      wes: { pts: [[0, 0], [D, D], [D, H - D], [0, H]], c: [D / 2 - 1, H / 2] },
      eas: { pts: [[W, 0], [W - D, D], [W - D, H - D], [W, H]], c: [W - D / 2 + 1, H / 2] },
      cor: { pts: [[D, D], [W - D, D], [W - D, H - D], [D, H - D]], c: [W / 2, H / 2] }
    };
  }
  var plans = {};
  function buildPlans() {
    geometry();
    var zones = DATA.zones.reduce(function (m, z) { m[z.id] = z; return m; }, {});
    ["baseline", "agent"].forEach(function (side) {
      var host = $("plan-" + side);
      host.textContent = "";
      var svg = svgEl("svg", { viewBox: "-8 -8 " + (W + 16) + " " + (H + 16), class: "plan-svg", role: "img",
        "aria-label": (side === "agent" ? "Agent" : "Stock control") + " floor plan, zone temperatures" });
      var defs = svgEl("defs", {});
      var f = svgEl("filter", { id: "soft-glow", x: "-20%", y: "-20%", width: "140%", height: "140%" });
      f.appendChild(svgEl("feGaussianBlur", { stdDeviation: "3.2" }));
      defs.appendChild(f);
      svg.appendChild(defs);
      var parts = { zones: {}, temps: {}, glows: {} };
      ZONE_ORDER.forEach(function (z) {
        var pts = GEOM[z].pts.map(function (p) { return p.join(","); }).join(" ");
        var poly = svgEl("polygon", { points: pts, class: "zone" });
        var title = svgEl("title", {}); title.textContent = zones[z].name;
        poly.appendChild(title);
        svg.appendChild(poly);
        parts.zones[z] = poly;
        var glow = svgEl("polygon", { points: pts, class: "glow" });
        svg.appendChild(glow);
        parts.glows[z] = glow;
        var cx = GEOM[z].c[0], cy = GEOM[z].c[1];
        var vertical = z === "eas" || z === "wes";
        var narrowPlan = D > 70;
        var lift = vertical ? (narrowPlan ? 20 : 16) : (z === "cor" ? (narrowPlan ? 24 : 20) : (narrowPlan ? 15 : 11));
        var lbl = svgEl("text", { x: cx, y: cy - lift, class: "zone-label" });
        lbl.textContent = z === "cor" ? "CORE" : zones[z].name.charAt(0);
        svg.appendChild(lbl);
        var tt = svgEl("text", { x: cx, y: cy + (narrowPlan ? 9 : 6), class: "zone-temp" + (z === "cor" ? "" : " small") });
        svg.appendChild(tt);
        parts.temps[z] = tt;
      });
      var whole = svgEl("rect", { x: 0, y: 0, width: W, height: H, rx: 4, class: "glow" });
      svg.appendChild(whole);
      parts.whole = whole;
      host.appendChild(svg);
      plans[side] = parts;
    });
  }
  function pulse(node, kind) {
    node.classList.remove("pulse", "clamp", "fallback");
    void node.getBBox();  // restart the animation
    node.classList.add(kind === "fallback" ? "fallback" : "clamp", "pulse");
  }

  // ---------- counters ----------
  var COUNTERS = [
    { key: "energy_kwh", name: "Energy", unit: "kWh", d: 0 },
    { key: "cost_usd", name: "Cost", unit: "$", d: 2, prefix: true },
    { key: "discomfort_kh", name: "Discomfort", unit: "K h/zone", d: 1 }
  ];
  var counterEls = {};
  function buildCounters() {
    var host = $("counters");
    host.textContent = "";
    COUNTERS.forEach(function (c) {
      var card = el("div", "card counter");
      var head = el("div", "head");
      head.appendChild(el("span", "name", c.name + (c.unit === "$" ? "" : " (" + c.unit + ")")));
      var gap = el("span", "gap", "");
      head.appendChild(gap);
      card.appendChild(head);
      var rows = el("div", "rows");
      var refs = { gap: gap };
      ["baseline", "agent"].forEach(function (side) {
        var r = el("div", "row " + side);
        var who = el("span", "who");
        var key = el("i", "key " + side);
        who.appendChild(key);
        who.appendChild(document.createTextNode(side === "agent" ? "Agent" : "Stock"));
        r.appendChild(who);
        var meter = el("div", "meter"); var bar = el("i"); meter.appendChild(bar); r.appendChild(meter);
        var val = el("span", "val num", "0");
        r.appendChild(val);
        rows.appendChild(r);
        refs[side] = { bar: bar, val: val };
      });
      card.appendChild(rows);
      host.appendChild(card);
      counterEls[c.key] = refs;
      state.shown[c.key] = { baseline: 0, agent: 0 };
    });
  }
  function updateCounters(dtMs, snap) {
    var sc = state.sc;
    COUNTERS.forEach(function (c) {
      var refs = counterEls[c.key];
      var target = { baseline: sample(sc.baseline[c.key], state.t), agent: sample(sc.agent[c.key], state.t) };
      var finalMax = Math.max(sc.baseline[c.key][sc.hours - 1] || 0, sc.agent[c.key][sc.hours - 1] || 0, 1e-9);
      var k = (snap || reduceMotion) ? 1 : 1 - Math.exp(-dtMs / 140);
      ["baseline", "agent"].forEach(function (side) {
        var shown = state.shown[c.key][side];
        shown = Math.abs(target[side] - shown) < 1e-6 ? target[side] : shown + (target[side] - shown) * k;
        state.shown[c.key][side] = shown;
        var digits = c.key === "energy_kwh" && Math.max(target.baseline, target.agent) < 100 ? 1 : c.d;
        var txt = (c.prefix ? "$" : "") + fmt(shown, digits);
        if (refs[side].val.textContent !== txt) refs[side].val.textContent = txt;
        refs[side].bar.style.width = (shown / finalMax * 100).toFixed(2) + "%";
      });
      var b = state.shown[c.key].baseline, a = state.shown[c.key].agent;
      var diff = a - b;
      var txt = "";
      var cls = "gap";
      if (b > 1e-6 || a > 1e-6) {
        var p = pct(a, b);
        var gd = c.key === "energy_kwh" && Math.abs(diff) < 10 ? 1 : c.d;
        txt = (diff <= 0 ? "−" : "+") + (c.prefix ? "$" : "") + fmt(Math.abs(diff), gd) +
          (p == null ? "" : "  (" + (p <= 0 ? "−" : "+") + fmt(Math.abs(p), 1) + "%)");
        cls += Math.abs(diff) < 1e-9 ? "" : diff < 0 ? " better" : " worse";
      }
      if (refs.gap.textContent !== txt) refs.gap.textContent = txt;
      refs.gap.className = cls;
    });
  }

  // ---------- charts ----------
  function makeChart(hostId, height, series) {
    var host = $(hostId);
    host.textContent = "";
    var width = Math.max(260, host.clientWidth || 600);
    var narrow = window.innerWidth < 640;
    var m = { t: 12, r: narrow ? 44 : 50, b: 24, l: 34 };
    var sc = state.sc;
    var plotW = width - m.l - m.r;
    var windowH = Math.min(sc.hours - 1, narrow ? 48 : 72);
    var pph = plotW / windowH;  // pixels per hour
    var total = (sc.hours - 1) * pph;
    var xi = function (i) { return i * pph; };
    var vals = [];
    series.forEach(function (s) {
      if (s.kind === "band") { s.upper.forEach(function (v) { if (v < 27) vals.push(v); }); return; }
      if (s.step) return;
      s.values.forEach(function (v) { if (v != null) vals.push(v); });
    });
    var lo = d3.min(vals), hi = d3.max(vals);
    var y = d3.scaleLinear().domain([Math.floor(lo - 0.8), Math.ceil(hi + 0.8)]).range([height - m.b, m.t]).nice();
    var svg = d3.select(host).append("svg").attr("viewBox", "0 0 " + width + " " + height).attr("height", height);
    var uid = hostId + "-clip";
    var defs = svg.append("defs");
    defs.append("clipPath").attr("id", uid + "-plot").append("rect")
      .attr("x", m.l).attr("y", m.t).attr("width", plotW).attr("height", height - m.t - m.b);
    defs.append("clipPath").attr("id", uid + "-axis").append("rect")
      .attr("x", m.l).attr("y", 0).attr("width", plotW + m.r - 2).attr("height", height);
    var reveal = defs.append("clipPath").attr("id", uid + "-reveal").append("rect")
      .attr("x", -10).attr("y", 0).attr("height", height).attr("width", 0);
    var g = svg.append("g").attr("class", "grid");
    y.ticks(4).forEach(function (v) { g.append("line").attr("x1", m.l).attr("x2", width - m.r).attr("y1", y(v)).attr("y2", y(v)); });
    var ax = svg.append("g").attr("class", "axis");
    y.ticks(4).forEach(function (v) { ax.append("text").attr("x", m.l - 8).attr("y", y(v)).attr("dy", "0.32em").attr("text-anchor", "end").text(v + "°"); });
    var plot = svg.append("g").attr("clip-path", "url(#" + uid + "-plot)");
    var track = plot.append("g");
    var axisTrack = svg.append("g").attr("clip-path", "url(#" + uid + "-axis)").append("g");
    // The time axis rides with the data: day labels at midnight, hour labels at noon.
    var midnights = track.append("g").attr("class", "grid");
    var tg = axisTrack.append("g").attr("class", "axis");
    for (var h = 0; h < sc.hours; h++) {
      var dh = dayHour(sc, h);
      if (dh.hour === 0) {
        midnights.append("line").attr("x1", xi(h)).attr("x2", xi(h)).attr("y1", m.t).attr("y2", height - m.b);
        tg.append("text").attr("x", xi(h) + 4).attr("y", height - 7).text("Day " + dh.day);
      } else if (dh.hour === 12 && !narrow) {
        tg.append("text").attr("x", xi(h)).attr("y", height - 7).attr("text-anchor", "middle").attr("opacity", 0.6).text("12:00");
      }
    }
    var lineGen = d3.line().defined(function (d) { return d != null; }).x(function (d, i) { return xi(i); }).y(function (d) { return y(d); });
    series.forEach(function (s) {
      var gen = s.step ? lineGen.curve(d3.curveStepAfter) : lineGen.curve(d3.curveMonotoneX);
      if (s.kind === "band") {
        var area = d3.area().x(function (d, i) { return xi(i); }).y0(function (d, i) { return y(s.lower[i]); })
          .y1(function (d, i) { return y(s.upper[i]); }).curve(d3.curveStepAfter);
        track.append("path").attr("class", "band").attr("d", area(s.lower));
        track.append("path").attr("class", "band-edge").attr("d", lineGen.curve(d3.curveStepAfter)(s.lower));
        track.append("path").attr("class", "band-edge").attr("d", lineGen.curve(d3.curveStepAfter)(s.upper));
        return;
      }
      var d = gen(s.values);
      track.append("path").attr("class", "line ghost " + s.cls).attr("d", d);
      track.append("path").attr("class", "line " + s.cls).attr("d", d).attr("clip-path", "url(#" + uid + "-reveal)");
    });
    var playhead = svg.append("line").attr("class", "playhead").attr("y1", m.t).attr("y2", height - m.b);
    var cross = svg.append("line").attr("class", "crosshair").attr("y1", m.t).attr("y2", height - m.b);
    var dots = {}, labels = {};
    series.filter(function (s) { return s.label; }).forEach(function (s) {
      dots[s.cls] = svg.append("circle").attr("class", "dot " + s.cls).attr("r", 4);
      labels[s.cls] = svg.append("text").attr("class", "end-label " + s.cls).attr("dy", "0.32em").text(s.label);
    });
    var tip = el("div", "tooltip");
    host.appendChild(tip);
    var chart = { y: y, m: m, width: width, height: height, plotW: plotW, pph: pph, total: total, offset: 0,
      track: track, axisTrack: axisTrack, reveal: reveal, playhead: playhead, dots: dots, labels: labels, series: series };
    chart.toX = function (i) { return m.l + i * pph - chart.offset; };
    chart.toI = function (px) { return clamp(Math.round((px - m.l + chart.offset) / pph), 0, sc.hours - 1); };
    // Hover layer: the crosshair snaps to the nearest hour and one tooltip lists every series.
    svg.append("rect").attr("x", m.l).attr("y", 0).attr("width", plotW).attr("height", height)
      .attr("fill", "transparent").style("cursor", "crosshair")
      .on("pointermove", function (ev) {
        var p = d3.pointer(ev, svg.node());
        var scale = width / host.clientWidth;
        var i = chart.toI(p[0]);
        cross.attr("x1", chart.toX(i)).attr("x2", chart.toX(i)).style("opacity", 0.6);
        tip.textContent = "";
        tip.appendChild(el("div", "t", dayHour(sc, i).label));
        series.forEach(function (s) {
          if (!s.tip) return;
          var v = s.kind === "band" ? null : s.values[i];
          var r = el("div", "r");
          r.appendChild(el("i", "key " + (s.keyCls || s.cls)));
          r.appendChild(el("span", "", s.tip));
          r.appendChild(el("b", "", s.kind === "band" ? fmt(s.lower[i], 0) + " to " + fmt(s.upper[i], 0) + "°C"
            : (v == null ? "stock" : fmt(v, 1) + "°C")));
          tip.appendChild(r);
        });
        var px = chart.toX(i) / scale, left = px + 14;
        if (left + 180 > host.clientWidth) left = px - 194;
        tip.style.left = Math.max(0, left) + "px";
        tip.style.top = "8px";
        tip.style.opacity = 1;
      })
      .on("pointerleave", function () { cross.style("opacity", 0); tip.style.opacity = 0; })
      .on("click", function (ev) {
        var p = d3.pointer(ev, svg.node());
        setPlaying(false);
        seek(chart.toI(p[0]), true);
      });
    return chart;
  }
  function drawCharts() {
    var sc = state.sc, z = state.zone;
    var zoneName = DATA.zones.filter(function (d) { return d.id === z; })[0].name;
    var narrow = window.innerWidth < 640;
    state.charts = [
      makeChart("chart-zone", narrow ? 200 : 240, [
        { kind: "band", lower: sc.band_lower_c, upper: sc.band_upper_c, values: [], tip: "Band", keyCls: "band" },
        { cls: "baseline set", values: sc.baseline.heat_set_c[z], step: true },
        { cls: "agent set", values: sc.agent.heat_set_c[z], step: true },
        { cls: "baseline", values: sc.baseline.zone_temp_c[z], label: "Stock", tip: zoneName + " stock" },
        { cls: "agent", values: sc.agent.zone_temp_c[z], label: "Agent", tip: zoneName + " agent" }
      ]),
      makeChart("chart-supply", narrow ? 180 : 240, [
        { cls: "agent set", values: sc.agent.supply_air_set_c, step: true, tip: "Agent setpoint", keyCls: "agent" },
        { cls: "baseline", values: sc.baseline.supply_air_c, label: "Stock", tip: "Stock" },
        { cls: "agent", values: sc.agent.supply_air_c, label: "Agent", tip: "Agent" }
      ])
    ];
  }
  function updateCharts() {
    state.charts.forEach(function (c) {
      // The window scrolls once the playhead reaches three quarters of the plot.
      var head = state.t * c.pph;
      c.offset = clamp(head - c.plotW * 0.75, 0, Math.max(0, c.total - c.plotW));
      c.track.attr("transform", "translate(" + (c.m.l - c.offset) + ",0)");
      c.axisTrack.attr("transform", "translate(" + (c.m.l - c.offset) + ",0)");
      c.reveal.attr("width", head + 10);
      var px = c.m.l + head - c.offset;
      c.playhead.attr("x1", px).attr("x2", px);
      var placed = [];
      c.series.forEach(function (s) {
        if (!s.label) return;
        var v = sample(s.values, state.t);
        if (v == null) return;
        var yy = c.y(v);
        c.dots[s.cls].attr("cx", px).attr("cy", yy);
        placed.push({ s: s, y: yy });
      });
      // Keep the two end labels from colliding.
      placed.sort(function (a, b) { return a.y - b.y; });
      for (var i = 1; i < placed.length; i++) if (placed[i].y - placed[i - 1].y < 13) placed[i].y = placed[i - 1].y + 13;
      placed.forEach(function (p) { c.labels[p.s.cls].attr("x", px + 8).attr("y", p.y); });
    });
  }

  // ---------- scrubber ----------
  function buildScrubber() {
    var sc = state.sc, host = $("scrub-ticks");
    host.textContent = "";
    var scr = $("scrubber");
    scr.setAttribute("aria-valuemax", String(sc.hours - 1));
    var narrow = window.innerWidth < 640;
    var labelEvery = sc.hours > 24 * 8 ? (narrow ? 4 : 2) : 1;
    for (var h = 0; h < sc.hours; h += 6) {
      var day = h % 24 === 0;
      var t = el("div", "tick" + (day ? " day" : ""));
      t.style.left = (h / (sc.hours - 1) * 100) + "%";
      host.appendChild(t);
      if (day && (h / 24) % labelEvery === 0) {
        var lab = el("div", "day-label", "D" + (h / 24 + 1));
        lab.style.left = (h / (sc.hours - 1) * 100) + "%";
        host.appendChild(lab);
      }
    }
    state.events = [];
    sc.agent.decisions.forEach(function (d, i) {
      if (d.status === "ok") return;
      state.events.push(i);
      var e = el("div", "ev " + d.status);
      e.style.left = (i / (sc.hours - 1) * 100) + "%";
      e.title = dayHour(sc, i).label + ": " + STATUS[d.status].label;
      host.appendChild(e);
    });
  }
  function scrubTo(clientX) {
    var r = $("scrubber").getBoundingClientRect();
    var f = clamp((clientX - r.left) / r.width, 0, 1);
    seek(f * (state.sc.hours - 1), false);
  }
  function bindScrubber() {
    var scr = $("scrubber"), dragging = false;
    scr.addEventListener("pointerdown", function (e) { dragging = true; scr.setPointerCapture(e.pointerId); setPlaying(false); scrubTo(e.clientX); });
    scr.addEventListener("pointermove", function (e) { if (dragging) scrubTo(e.clientX); });
    scr.addEventListener("pointerup", function () { dragging = false; seek(Math.round(state.t), false); });
    scr.addEventListener("keydown", function (e) {
      var step = e.shiftKey ? 24 : 1;
      if (e.key === "ArrowRight") { seek(Math.round(state.t) + step, true); e.preventDefault(); }
      else if (e.key === "ArrowLeft") { seek(Math.round(state.t) - step, true); e.preventDefault(); }
      else if (e.key === "Home") { seek(0, true); e.preventDefault(); }
      else if (e.key === "End") { seek(state.sc.hours - 1, true); e.preventDefault(); }
      else if (e.key === " ") { setPlaying(!state.playing); e.preventDefault(); }
    });
  }

  // ---------- reasons ----------
  var reasonCards = [];
  function decisionText(d) {
    if (d.status === "fallback") return "Stock control held this hour. " + (d.fallback ? capitalize(d.fallback) + "." : "");
    return d.reason || "No change requested.";
  }
  function capitalize(s) { return s.charAt(0).toUpperCase() + s.slice(1); }
  function pointName(p) {
    var parts = p.split(".");
    var zone = DATA.zones.filter(function (z) { return z.id === parts[0]; })[0];
    var what = { heat_c: "heating", cool_c: "cooling" }[parts[1]] || "";
    return zone ? zone.name + " " + what : "Supply air";
  }
  function renderReasons(hour) {
    var sc = state.sc, host = $("reasons");
    var show = window.innerWidth < 640 ? 3 : 4;
    var items = [];
    for (var i = hour; i >= 0 && items.length < show; i--) items.push(i);
    host.textContent = "";
    items.forEach(function (i, k) {
      var d = sc.agent.decisions[i];
      var card = el("div", "reason-card " + (k === 0 ? "current " : "past ") + d.status + (k === 0 && !reduceMotion ? " enter" : ""));
      var meta = el("div", "meta");
      meta.appendChild(el("span", "num", dayHour(sc, i, true).label + " decision"));
      meta.appendChild(statusTag(d.status));
      card.appendChild(meta);
      card.appendChild(el("div", "text", decisionText(d)));
      if (d.clamps.length && k === 0) {
        var ul = el("ul");
        d.clamps.slice(0, 5).forEach(function (c) {
          var li = el("li");
          var code = el("code", "", c.requested == null ? "n/a" : fmt(c.requested, 1) + " → " + (c.applied == null ? "stock" : fmt(c.applied, 1)) + " C");
          li.appendChild(code);
          li.appendChild(el("span", "", pointName(c.point) + ": " + c.reason));
          ul.appendChild(li);
        });
        if (d.clamps.length > 5) ul.appendChild(el("li", "", "+" + (d.clamps.length - 5) + " more"));
        card.appendChild(ul);
      }
      host.appendChild(card);
      if (k === 0 && !reduceMotion) requestAnimationFrame(function () { card.classList.remove("enter"); });
    });
  }

  // ---------- per-frame ----------
  function frame(snap, dtMs) {
    var sc = state.sc;
    var hour = clamp(Math.round(state.t), 0, sc.hours - 1);
    var lo = sample(sc.band_lower_c, state.t), hi = sample(sc.band_upper_c, state.t);
    ["baseline", "agent"].forEach(function (side) {
      var p = plans[side];
      ZONE_ORDER.forEach(function (z) {
        var temp = sample(sc[side].zone_temp_c[z], state.t);
        p.zones[z].setAttribute("fill", zoneColor(temp, lo, hi));
        var txt = fmt(temp, 1) + "°";
        if (p.temps[z].textContent !== txt) p.temps[z].textContent = txt;
      });
    });
    var scr = $("scrubber");
    var f = state.t / (sc.hours - 1) * 100;
    $("scrub-fill").style.width = f + "%";
    $("scrub-thumb").style.left = f + "%";
    scr.setAttribute("aria-valuenow", String(hour));
    scr.setAttribute("aria-valuetext", dayHour(sc, hour).label);
    updateCharts();
    updateCounters(dtMs || 16, snap);
    if (hour !== state.lastHour) {
      onHour(hour, snap);
      state.lastHour = hour;
    }
  }
  function onHour(hour, snap) {
    var sc = state.sc, d = sc.agent.decisions[hour];
    var dh = dayHour(sc, hour);
    $("clock-when").textContent = dh.label;
    var facts = $("clock-facts");  // class clock-facts, not the scorecard .facts grid
    facts.textContent = "";
    var occupied = sc.band_lower_c[hour] >= 18;
    facts.appendChild(el("span", "occ-pill" + (occupied ? " on" : ""), occupied ? "Occupied" : "Unoccupied"));
    var o = el("span"); o.appendChild(document.createTextNode("Outdoor ")); o.appendChild(el("b", "num", fmt(sc.outdoor_c[hour], 1) + "°C")); facts.appendChild(o);
    var pr = el("span"); pr.appendChild(document.createTextNode("Price ")); pr.appendChild(el("b", "num", "$" + fmt(sc.price[hour], 3) + "/kWh")); facts.appendChild(pr);
    var bd = el("span"); bd.appendChild(document.createTextNode("Band ")); bd.appendChild(el("b", "num", fmt(sc.band_lower_c[hour], 0) + " to " + fmt(sc.band_upper_c[hour], 0) + "°C")); facts.appendChild(bd);
    var bh = sc.baseline.heat_set_c.cor[hour], bc = sc.baseline.cool_set_c.cor[hour];
    $("sp-baseline").textContent = fmt(bh, 0) + " / " + fmt(bc, 0) + " C";
    var sa = sc.agent.supply_air_set_c[hour];
    $("sp-agent").textContent = sa == null ? "stock" : fmt(sa, 1) + " C";
    var st = $("plan-status");
    st.textContent = "";
    st.appendChild(statusTag(d.status));
    renderReasons(hour);
    if (d.status !== "ok" && !snap) {
      var zones = {};
      d.clamps.forEach(function (c) { zones[c.point.split(".")[0]] = 1; });
      if (d.status === "fallback" || zones.supply_air_c) pulse(plans.agent.whole, d.status);
      ZONE_ORDER.forEach(function (z) { if (zones[z]) pulse(plans.agent.glows[z], d.status); });
    }
  }

  function tick(now) {
    if (!state.playing) return;
    var dt = state.lastFrame ? Math.min(100, now - state.lastFrame) : 16;
    state.lastFrame = now;
    state.t = Math.min(state.sc.hours - 1, state.t + dt / 1000 * state.speed);
    frame(false, dt);
    if (state.t >= state.sc.hours - 1) { setPlaying(false); return; }
    requestAnimationFrame(tick);
  }
  function setPlaying(on) {
    if (on && state.t >= state.sc.hours - 1) { state.t = 0; state.lastHour = -1; }
    state.playing = on;
    $("play-icon").setAttribute("d", on ? ICON.pause : ICON.play);
    $("play").setAttribute("aria-label", on ? "Pause" : "Play");
    $("play-hero-label").textContent = on ? "Pause" : (state.t > 0 && state.t < state.sc.hours - 1 ? "Resume" : "Play the two weeks");
    if (on) { state.lastFrame = 0; requestAnimationFrame(tick); }
  }
  function seek(t, snap) {
    state.t = clamp(t, 0, state.sc.hours - 1);
    frame(!!snap);
  }

  // ---------- static sections ----------
  function renderHero() {
    var sc = state.sc, h = sc.headline;
    var eb = $("eyebrow");
    eb.textContent = "";
    if (sc.sample) eb.appendChild(el("span", "tag sample", "Sample"));
    ["BOPTEST", sc.testcase, sc.name, sc.electricity_price + " price"].forEach(function (s, i) {
      if (i) eb.appendChild(el("span", "dot"));
      eb.appendChild(el("span", "", s));
    });
    var h1 = $("headline");
    h1.textContent = "";
    var span = el("span", h.tone === "loss" ? "tone-loss" : "", h.text + ".");
    h1.appendChild(span);
    var r = sc.agent_run;
    var days = Math.round(sc.hours / 24);
    $("lede").textContent = "Stock control versus " + (r.supervisor === "scripted" ? "scripted replies standing in for " : "") +
      r.model_id + " making one supervisory call an hour, " + sc.hours + " hours (" + days + " days) of the " + sc.name.toLowerCase() +
      " scenario. Every setpoint passed a deterministic safety envelope: " + r.clamped_hours + " hours were clamped and " +
      r.fallback_hours + " fell back to stock control.";
    var host = $("deltas");
    host.textContent = "";
    [["Cost", h.cost_pct], ["Energy", h.energy_pct], ["Discomfort", h.discomfort_pct]].forEach(function (p) {
      var box = el("div", "delta");
      box.appendChild(el("div", "label", p[0]));
      box.appendChild(el("div", "value num", p[1] == null ? "n/a" : (p[1] <= 0 ? "−" : "+") + fmt(Math.abs(p[1]), 1) + "%"));
      var better = p[1] != null && p[1] < 0, same = p[1] == null || Math.abs(p[1]) < 0.05;
      var v = el("div", "verdict " + (same ? "" : better ? "better" : "worse"));
      if (!same) v.innerHTML = better ? ICON.down : ICON.up;
      v.appendChild(document.createTextNode(same ? "no change" : better ? "better" : "worse"));
      box.appendChild(v);
      host.appendChild(box);
    });
    $("sample-banner").hidden = !DATA.sample;
    $("reasons-sub").textContent = r.calls + " calls, " + r.clamped_hours + " clamped, " + r.fallback_hours + " fallback";
  }
  function renderScorecard() {
    var host = $("scorecard");
    host.textContent = "";
    DATA.scenarios.forEach(function (sc) {
      var card = el("article", "card score");
      var head = el("div", "card-head");
      var title = el("div", "card-title", sc.name);
      if (sc.sample) title.appendChild(el("span", "tag sample", "Sample"));
      head.appendChild(title);
      head.appendChild(el("span", "card-sub", sc.hours + " h, " + sc.electricity_price + " price" + (sc.hours < (sc.scenario_hours || sc.hours) ? ", partial" : "")));
      card.appendChild(head);
      var table = el("table");
      var thead = el("thead"), tr = el("tr");
      ["KPI", "Stock", "Agent", "Change"].forEach(function (t) { tr.appendChild(el("th", "", t)); });
      thead.appendChild(tr); table.appendChild(thead);
      var tb = el("tbody");
      DATA.kpis.forEach(function (k) {
        var b = sc.baseline.kpi[k.id], a = sc.agent.kpi[k.id];
        if (b == null && a == null) return;
        if (k.id === "time_rat") return;
        var row = el("tr");
        var c0 = el("td"); c0.appendChild(document.createTextNode(k.name)); c0.appendChild(el("span", "unit", k.id + ", " + k.unit));
        row.appendChild(c0);
        var big = Math.max(Math.abs(a || 0), Math.abs(b || 0));
        var digits = big >= 10 ? 1 : big >= 1 ? 3 : 4;
        row.appendChild(el("td", "", fmt(b, digits)));
        row.appendChild(el("td", "", fmt(a, digits)));
        var p = pct(a, b);
        var cls = p == null || Math.abs(p) < 0.05 ? "" : p < 0 ? "better" : "worse";
        var td = el("td", "chg " + cls);
        if (cls) td.insertAdjacentHTML("afterbegin", cls === "better" ? ICON.down : ICON.up);
        td.appendChild(document.createTextNode(p == null ? (a === b ? "same" : "n/a") :
          cls ? (p <= 0 ? "−" : "+") + fmt(Math.abs(p), 1) + "%" : "same"));
        if (cls) td.appendChild(el("span", "word", cls));
        row.appendChild(td);
        tb.appendChild(row);
      });
      table.appendChild(tb);
      card.appendChild(table);
      var r = sc.agent_run;
      var facts = el("div", "facts");
      [["Model", r.supervisor === "scripted" ? "Scripted, no API" : r.model_id],
       ["Run cost", "$" + fmt(r.cost_usd, 2) + " / $" + fmt(r.budget_usd, 2)],
       ["Model calls", fmt(r.calls, 0)],
       ["Clamped hours", fmt(r.clamped_hours, 0)],
       ["Fallback hours", fmt(r.fallback_hours, 0)],
       ["Budget stop", r.budget_stopped ? "hit" : "not hit"]].forEach(function (f) {
        var d = el("div"); d.appendChild(el("div", "k", f[0])); d.appendChild(el("div", "v", f[1])); facts.appendChild(d);
      });
      card.appendChild(facts);
      host.appendChild(card);
    });
  }
  function renderTabs() {
    var host = $("scenario-tabs");
    host.textContent = "";
    DATA.scenarios.forEach(function (sc, i) {
      var b = el("button", "", sc.name);
      b.type = "button";
      b.setAttribute("role", "tab");
      b.setAttribute("aria-selected", i === state.idx ? "true" : "false");
      b.addEventListener("click", function () { selectScenario(i); });
      host.appendChild(b);
    });
  }
  function renderZoneChips() {
    var host = $("zone-chips");
    host.textContent = "";
    DATA.zones.forEach(function (z) {
      var b = el("button", "", z.id === "cor" ? "Core" : z.name.charAt(0));
      b.type = "button";
      b.title = z.name;
      b.setAttribute("aria-pressed", z.id === state.zone ? "true" : "false");
      b.addEventListener("click", function () { state.zone = z.id; renderZoneChips(); drawCharts(); frame(true); });
      host.appendChild(b);
    });
  }
  function selectScenario(i) {
    setPlaying(false);
    state.idx = i;
    state.sc = DATA.scenarios[i];
    state.t = 0; state.lastHour = -1;
    renderTabs(); renderHero(); buildPlans(); buildCounters(); buildScrubber(); drawCharts();
    frame(true);
  }

  // ---------- boot ----------
  function boot() {
    setTheme(document.documentElement.getAttribute("data-theme") === "light" ? "light" : "dark");
    $("theme-toggle").addEventListener("click", function () {
      setTheme(document.documentElement.getAttribute("data-theme") === "dark" ? "light" : "dark");
    });
    if (!DATA || !DATA.scenarios || !DATA.scenarios.length || typeof d3 === "undefined") {
      $("headline").textContent = !DATA || !DATA.scenarios || !DATA.scenarios.length ? "No runs yet" : "Charts could not load";
      $("lede").textContent = "Run the commands below to record a baseline and an agent run, then rebuild this page's data.";
      ["stage"].forEach(function (id) { $(id).hidden = true; });
      document.querySelector(".race").hidden = true;
      $("play-hero").hidden = true;
      return;
    }
    state.idx = 0;
    state.sc = DATA.scenarios[0];
    renderScorecard(); renderZoneChips(); bindScrubber();
    selectScenario(0);
    $("play").addEventListener("click", function () { setPlaying(!state.playing); });
    $("play-hero").addEventListener("click", function () {
      var go = !state.playing;
      if (go) $("stage").scrollIntoView({ behavior: reduceMotion ? "auto" : "smooth", block: "start" });
      setPlaying(go);
    });
    Array.prototype.forEach.call(document.querySelectorAll("#speed button"), function (b) {
      b.addEventListener("click", function () {
        state.speed = +b.getAttribute("data-speed");
        Array.prototype.forEach.call(document.querySelectorAll("#speed button"), function (o) { o.setAttribute("aria-pressed", o === b ? "true" : "false"); });
      });
    });
    $("next-event").addEventListener("click", function () {
      var cur = Math.round(state.t);
      var nxt = state.events.filter(function (e) { return e > cur; })[0];
      if (nxt != null) { setPlaying(false); seek(nxt, false); }
    });
    $("prev-event").addEventListener("click", function () {
      var cur = Math.round(state.t);
      var prv = state.events.filter(function (e) { return e < cur; }).pop();
      if (prv != null) { setPlaying(false); seek(prv, false); }
    });
    var lastW = window.innerWidth;
    window.addEventListener("resize", function () {
      if (Math.abs(window.innerWidth - lastW) < 40) return;
      lastW = window.innerWidth;
      buildScrubber(); drawCharts(); frame(true);
    });
    document.addEventListener("keydown", function (e) {
      if (e.key === " " && e.target === document.body) { setPlaying(!state.playing); e.preventDefault(); }
    });
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", boot); else boot();
})();
