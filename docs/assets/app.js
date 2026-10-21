/* Hyperbolic replay viewer. Static: reads window.HYPERBOLIC_VIEWER_DATA from data/viewer.js.
   Live mode (`hyperbolic serve` only) feeds it growing data through window.HyperbolicViewer.render. */
(function () {
  "use strict";

  var DATA = window.HYPERBOLIC_VIEWER_DATA;
  var reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  var $ = function (id) { return document.getElementById(id); };
  var SIDES = ["baseline", "agent"];

  var state = {
    sc: null, t: 0, playing: false, speed: 10, building: null,
    lastHour: -1, lastFrame: 0, shown: {}, charts: [], events: []
  };

  // ---------- helpers ----------
  function el(tag, cls, text) {
    var e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text != null) e.textContent = text;
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
  function pad(n) { return String(n).padStart(2, "0"); }
  function pct(a, b) { return (b == null || a == null || Math.abs(b) < 1e-12) ? null : (a - b) / Math.abs(b) * 100; }
  function signed(v, d, unit) { return (v <= 0 ? "−" : "+") + fmt(Math.abs(v), d) + (unit || ""); }
  function bname(id) { return id.replace("_", " "); }
  // CityLearn hours run 1 to 24; hour h is the hour that ends at h:00.
  function dayHour(sc, i, atStart) {
    i = clamp(Math.round(i), 0, sc.hours - 1);
    var h = sc.hour_of_day[i], d = sc.day[i], hh;
    if (atStart) { hh = h - 1; }
    else { hh = h % 24; if (h === 24) d += 1; }
    return { day: d, label: "Day " + d + ", " + pad(hh) + ":00" };
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
    colorCache = {};
    if (state.sc) { drawCharts(); drawPriceStrip(); frame(true); }
  }

  // ---------- comfort color ----------
  var colorCache = {};
  function tileColor(temp, lo, hi, occupied) {
    var key = "k";
    if (!colorCache[key]) {
      colorCache[key] = {
        warm: d3.interpolateLab(css("--band"), css("--warm")),
        cool: d3.interpolateLab(css("--band"), css("--cool")),
        surface: css("--surface-2")
      };
    }
    var c = colorCache[key];
    var base, depth;
    if (temp > hi) { base = c.warm(clamp(0.4 + (temp - hi) / 3, 0.4, 1)); depth = 0.34 + clamp((temp - hi) / 3, 0, 1) * 0.22; }
    else if (temp < lo) { base = c.cool(clamp(0.4 + (lo - temp) / 3, 0.4, 1)); depth = 0.34 + clamp((lo - temp) / 3, 0, 1) * 0.22; }
    else {
      var p = (temp - lo) / Math.max(hi - lo, 0.1);
      base = p < 0.5 ? c.cool((0.5 - p) * 0.3) : c.warm((p - 0.5) * 0.3);
      depth = 0.26;
    }
    if (!occupied) depth *= 0.55;
    return d3.interpolateLab(c.surface, base)(depth);
  }

  // ---------- district tiles ----------
  var tiles = {};
  function buildTiles() {
    SIDES.forEach(function (side) {
      var host = $("tiles-" + side);
      host.textContent = "";
      tiles[side] = {};
      DATA.buildings.forEach(function (b) {
        var t = el("div", "tile");
        var head = el("div", "tile-head");
        head.appendChild(el("span", "tile-name", b.name));
        var occ = el("span", "occ"); occ.appendChild(el("i")); var occT = el("span", "", ""); occ.appendChild(occT);
        head.appendChild(occ);
        t.appendChild(head);
        var temp = el("div", "tile-temp");
        t.appendChild(temp);
        var gauge = el("div", "gauge"); var band = el("i", "band"); var mark = el("i", "mark");
        gauge.appendChild(band); gauge.appendChild(mark); t.appendChild(gauge);
        var gl = el("div", "gauge-labels"); var gLo = el("span"); var gHi = el("span"); gl.appendChild(gLo); gl.appendChild(gHi);
        t.appendChild(gl);
        var meters = el("div", "meters");
        var refs = {};
        [["battery", "Battery"], ["dhw", "Tank"]].forEach(function (m) {
          var row = el("div", "mrow"); row.appendChild(el("span", "", m[1]));
          var bar = el("span", "bar"); var fill = el("i"); bar.appendChild(fill); row.appendChild(bar);
          var val = el("b"); row.appendChild(val);
          meters.appendChild(row);
          refs[m[0]] = { fill: fill, val: val };
        });
        t.appendChild(meters);
        var gridline = el("div", "gridline"); var gLabel = el("span", "", "Grid"); var gVal = el("b");
        gridline.appendChild(gLabel); gridline.appendChild(gVal); t.appendChild(gridline);
        host.appendChild(t);
        tiles[side][b.id] = { tile: t, occ: occ, occT: occT, temp: temp, band: band, mark: mark, gLo: gLo, gHi: gHi,
          battery: refs.battery, dhw: refs.dhw, gLabel: gLabel, gVal: gVal };
      });
    });
  }
  function updateTiles() {
    var sc = state.sc, i = clamp(Math.round(state.t), 0, sc.hours - 1), band = DATA.comfort_band_k;
    SIDES.forEach(function (side) {
      DATA.buildings.forEach(function (b) {
        var r = tiles[side][b.id], s = sc[side].buildings[b.id];
        var sp = sample(sc.setpoint_c[b.id], state.t), lo = sp - band, hi = sp + band;
        var temp = sample(s.indoor_c, state.t), occupied = sc.occupied[b.id][i] === 1;
        r.tile.style.backgroundColor = tileColor(temp, lo, hi, occupied);
        var tt = fmt(temp, 1);
        if (r.temp.firstChild == null || r.temp.firstChild.textContent !== tt) {
          r.temp.textContent = tt; r.temp.appendChild(el("small", "", "°C"));
        }
        // Gauge spans setpoint +/- 2 x band.
        var gmin = sp - 2 * band, gmax = sp + 2 * band;
        var pos = function (v) { return clamp((v - gmin) / (gmax - gmin), 0, 1) * 100; };
        r.band.style.left = pos(lo) + "%"; r.band.style.width = (pos(hi) - pos(lo)) + "%";
        r.mark.style.left = pos(temp) + "%";
        r.gLo.textContent = fmt(lo, 1); r.gHi.textContent = fmt(hi, 1);
        r.occ.className = "occ" + (occupied ? " on" : "");
        r.occT.textContent = occupied ? "Occupied" : "Empty";
        ["battery", "dhw"].forEach(function (k) {
          var v = sample(s[k + "_soc"], state.t);
          r[k].fill.style.width = (clamp(v, 0, 1) * 100).toFixed(1) + "%";
          r[k].val.textContent = fmt(v * 100, 0) + "%";
        });
        var g = sample(s.grid_kwh, state.t);
        r.gLabel.textContent = g < 0 ? "Export" : "Grid";
        r.gVal.textContent = fmt(Math.abs(g), 2) + " kWh";
        r.gVal.className = g < 0 ? "exp" : "";
      });
    });
  }
  function pulse(node, kind) {
    var cls = kind === "fallback" ? "pulse-fallback" : "pulse-clamp";
    node.classList.remove("pulse-clamp", "pulse-fallback");
    void node.offsetWidth;  // restart the animation
    node.classList.add(cls);
  }

  // ---------- counters ----------
  var COUNTERS = [
    { key: "cost_usd", name: "Cost", d: 2, prefix: "$" },
    { key: "emission_kg", name: "Emissions (kg CO2)", d: 0 },
    { key: "discomfort_h", name: "Discomfort (building hours)", d: 0 }
  ];
  var counterEls = {};
  function buildCounters() {
    var host = $("counters");
    host.textContent = "";
    COUNTERS.forEach(function (c) {
      var card = el("div", "card counter");
      var head = el("div", "head");
      head.appendChild(el("span", "name", c.name));
      var gap = el("span", "gap", "");
      head.appendChild(gap);
      card.appendChild(head);
      var rows = el("div", "rows");
      var refs = { gap: gap };
      SIDES.forEach(function (side) {
        var r = el("div", "row " + side);
        var who = el("span", "who");
        who.appendChild(el("i", "key " + side));
        who.appendChild(document.createTextNode(side === "agent" ? "Agent" : "Base"));
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
      var finalMax = Math.max(Math.abs(sc.baseline[c.key][sc.hours - 1] || 0), Math.abs(sc.agent[c.key][sc.hours - 1] || 0), 1e-9);
      var k = (snap || reduceMotion) ? 1 : 1 - Math.exp(-dtMs / 140);
      SIDES.forEach(function (side) {
        var shown = state.shown[c.key][side];
        shown = Math.abs(target[side] - shown) < 1e-6 ? target[side] : shown + (target[side] - shown) * k;
        state.shown[c.key][side] = shown;
        var txt = (c.prefix || "") + fmt(shown, c.d);
        if (refs[side].val.textContent !== txt) refs[side].val.textContent = txt;
        refs[side].bar.style.width = clamp(shown / finalMax * 100, 0, 100).toFixed(2) + "%";
      });
      var b = state.shown[c.key].baseline, a = state.shown[c.key].agent, diff = a - b;
      var txt = "", cls = "gap";
      if (Math.abs(b) > 1e-6 || Math.abs(a) > 1e-6) {
        var p = pct(a, b);
        txt = signed(diff, c.d) + (p == null ? "" : "  (" + signed(p, 1, "%") + ")");
        if (c.prefix) txt = (diff <= 0 ? "−$" : "+$") + fmt(Math.abs(diff), c.d) + (p == null ? "" : "  (" + signed(p, 1, "%") + ")");
        cls += Math.abs(diff) < 1e-9 ? "" : diff < 0 ? " better" : " worse";
        if (Math.abs(diff) < Math.pow(10, -c.d) / 2) { txt = "even"; cls = "gap"; }
      }
      if (refs.gap.textContent !== txt) refs.gap.textContent = txt;
      refs.gap.className = cls;
    });
  }

  // ---------- charts (rolling window that follows the playhead) ----------
  function makeChart(hostId, height, series, opts) {
    opts = opts || {};
    var host = $(hostId);
    host.textContent = "";
    var width = Math.max(260, host.clientWidth || 600);
    var narrow = window.innerWidth < 640;
    var m = { t: 12, r: narrow ? 44 : 50, b: 24, l: 36 };
    var sc = state.sc;
    var plotW = width - m.l - m.r;
    var windowH = Math.max(1, Math.min(sc.hours - 1, narrow ? 48 : 72));
    var pph = plotW / windowH;
    var total = (sc.hours - 1) * pph;
    var xi = function (i) { return i * pph; };
    var vals = [];
    series.forEach(function (s) {
      if (s.kind === "band") { s.lower.forEach(function (v) { vals.push(v); }); s.upper.forEach(function (v) { vals.push(v); }); return; }
      s.values.forEach(function (v) { if (v != null) vals.push(v); });
    });
    var lo = opts.min != null ? opts.min : d3.min(vals), hi = opts.max != null ? opts.max : d3.max(vals);
    var padY = opts.pad != null ? opts.pad : 0.6;
    var y = d3.scaleLinear().domain([lo - padY, hi + padY]).range([height - m.b, m.t]).nice();
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
    var ticks = y.ticks(4);
    ticks.forEach(function (v) { g.append("line").attr("x1", m.l).attr("x2", width - m.r).attr("y1", y(v)).attr("y2", y(v)); });
    var ax = svg.append("g").attr("class", "axis");
    ticks.forEach(function (v) { ax.append("text").attr("x", m.l - 8).attr("y", y(v)).attr("dy", "0.32em").attr("text-anchor", "end").text(opts.tick ? opts.tick(v) : v); });
    var plot = svg.append("g").attr("clip-path", "url(#" + uid + "-plot)");
    var track = plot.append("g");
    var axisTrack = svg.append("g").attr("clip-path", "url(#" + uid + "-axis)").append("g");
    var midnights = track.append("g").attr("class", "grid");
    var tg = axisTrack.append("g").attr("class", "axis");
    for (var h = 0; h < sc.hours; h++) {
      if (sc.hour_of_day[h] === 24) {
        midnights.append("line").attr("x1", xi(h)).attr("x2", xi(h)).attr("y1", m.t).attr("y2", height - m.b);
        tg.append("text").attr("x", xi(h) + 4).attr("y", height - 7).text("Day " + (sc.day[h] + 1));
      } else if (sc.hour_of_day[h] === 12 && pph * 12 > 80) {
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
          var r = el("div", "r");
          r.appendChild(el("i", "key " + (s.keyCls || s.cls)));
          r.appendChild(el("span", "", s.tip));
          var v = s.kind === "band" ? null : s.values[i];
          r.appendChild(el("b", "", s.kind === "band" ? fmt(s.lower[i], 1) + " to " + fmt(s.upper[i], 1) + (opts.unit || "")
            : (v == null ? "n/a" : (opts.fmt ? opts.fmt(v) : fmt(v, 2)) + (opts.unit || ""))));
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
    var sc = state.sc, b = state.building, band = DATA.comfort_band_k;
    var narrow = window.innerWidth < 640, h = narrow ? 190 : 220;
    var lower = sc.setpoint_c[b].map(function (v) { return v - band; });
    var upper = sc.setpoint_c[b].map(function (v) { return v + band; });
    var name = bname(b);
    $("battery-sub").textContent = name;
    state.charts = [
      makeChart("chart-temp", h, [
        { kind: "band", lower: lower, upper: upper, values: [], tip: "Band", keyCls: "band" },
        { cls: "baseline", values: sc.baseline.buildings[b].indoor_c, label: "Base", tip: name + ", no control" },
        { cls: "agent", values: sc.agent.buildings[b].indoor_c, label: "Agent", tip: name + ", agent" }
      ], { unit: "°C", tick: function (v) { return v + "°"; }, fmt: function (v) { return fmt(v, 1); } }),
      makeChart("chart-grid", h, [
        { cls: "baseline", values: sc.baseline.district_grid_kwh, label: "Base", tip: "No control" },
        { cls: "agent", values: sc.agent.district_grid_kwh, label: "Agent", tip: "Agent" }
      ], { unit: " kWh", pad: 0.5 }),
      makeChart("chart-battery", h, [
        { cls: "baseline", values: sc.baseline.buildings[b].battery_soc.map(function (v) { return v * 100; }), label: "Base", tip: "No control" },
        { cls: "agent", values: sc.agent.buildings[b].battery_soc.map(function (v) { return v * 100; }), label: "Agent", tip: "Agent" }
      ], { unit: "%", min: 0, max: 100, pad: 0, tick: function (v) { return v + "%"; }, fmt: function (v) { return fmt(v, 0); } })
    ];
  }
  function updateCharts() {
    state.charts.forEach(function (c) {
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
      placed.sort(function (a, b) { return a.y - b.y; });
      for (var i = 1; i < placed.length; i++) if (placed[i].y - placed[i - 1].y < 13) placed[i].y = placed[i - 1].y + 13;
      placed.forEach(function (p) { c.labels[p.s.cls].attr("x", px + 8).attr("y", p.y); });
    });
  }

  // ---------- scrubber and price strip ----------
  function drawPriceStrip() {
    var sc = state.sc, svg = $("price-strip");
    svg.textContent = "";
    var n = sc.hours, w = 1000, h = 18;
    svg.setAttribute("viewBox", "0 0 " + w + " " + h);
    var max = d3.max(sc.price) || 1, min = d3.min(sc.price);
    if (max - min < 1e-9) min = max - 1;
    var x = function (i) { return i / Math.max(1, n - 1) * w; };
    var y = function (v) { return h - 1 - (v - min) / (max - min) * (h - 3); };
    var d = "M0," + h;
    for (var i = 0; i < n; i++) d += "L" + x(i).toFixed(2) + "," + y(sc.price[i]).toFixed(2) + "L" + x(i + 1 < n ? i + 1 : i).toFixed(2) + "," + y(sc.price[i]).toFixed(2);
    d += "L" + w + "," + h + "Z";
    var p = document.createElementNS("http://www.w3.org/2000/svg", "path");
    p.setAttribute("d", d);
    svg.appendChild(p);
  }
  function buildScrubber() {
    var sc = state.sc, host = $("scrub-ticks");
    host.textContent = "";
    var scr = $("scrubber");
    scr.setAttribute("aria-valuemax", String(sc.hours - 1));
    var narrow = window.innerWidth < 640;
    var labelEvery = sc.hours > 24 * 8 ? (narrow ? 7 : 3) : 1;
    for (var h = 0; h < sc.hours; h++) {
      if (sc.hour_of_day[h] !== 24 && h !== 0) continue;
      var day = h === 0 ? 1 : sc.day[h] + 1;
      var at = h === 0 ? 0 : h + 1;
      var t = el("div", "tick day");
      t.style.left = (at / (sc.hours - 1) * 100) + "%";
      host.appendChild(t);
      if ((day - 1) % labelEvery === 0 && at < sc.hours - 6) {
        var lab = el("div", "day-label", "D" + day);
        lab.style.left = (at / (sc.hours - 1) * 100) + "%";
        host.appendChild(lab);
      }
    }
    state.events = [];
    sc.agent.decisions.forEach(function (d, i) {
      if (d.status === "ok") return;
      state.events.push(i);
      var e = el("div", "ev " + d.status);
      e.style.left = (i / (sc.hours - 1) * 100) + "%";
      e.title = dayHour(sc, i, true).label + ": " + STATUS[d.status].label;
      host.appendChild(e);
    });
  }
  function scrubTo(clientX) {
    var r = $("scrubber").getBoundingClientRect();
    seek(clamp((clientX - r.left) / r.width, 0, 1) * (state.sc.hours - 1), false);
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
  function capitalize(s) { return s.charAt(0).toUpperCase() + s.slice(1); }
  function decisionText(d) {
    if (d.status === "fallback") return "No control actions held this hour. " + (d.fallback ? capitalize(d.fallback) + "." : "");
    return d.reason || "No change requested.";
  }
  function pointName(p) {
    var parts = p.split(".");
    var what = { cooling: "heat pump", dhw: "hot water tank", battery: "battery" }[parts[1]] || parts[1];
    return bname(parts[0]) + " " + what;
  }
  function renderReasons(hour) {
    var sc = state.sc, host = $("reasons");
    var show = window.innerWidth < 640 ? 3 : 4;
    host.textContent = "";
    for (var i = hour, k = 0; i >= 0 && k < show; i--, k++) {
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
          li.appendChild(el("code", "", c.requested == null ? "n/a" : fmt(c.requested, 2) + " → " + (c.applied == null ? "base" : fmt(c.applied, 2))));
          li.appendChild(el("span", "", pointName(c.point) + ": " + c.reason));
          ul.appendChild(li);
        });
        if (d.clamps.length > 5) ul.appendChild(el("li", "", "+" + (d.clamps.length - 5) + " more"));
        card.appendChild(ul);
      }
      host.appendChild(card);
      if (k === 0 && !reduceMotion) (function (c) { requestAnimationFrame(function () { c.classList.remove("enter"); }); })(card);
    }
  }

  // ---------- per-frame ----------
  function frame(snap, dtMs) {
    var sc = state.sc;
    var hour = clamp(Math.round(state.t), 0, sc.hours - 1);
    updateTiles();
    var f = state.t / (sc.hours - 1) * 100;
    $("scrub-fill").style.width = f + "%";
    $("scrub-thumb").style.left = f + "%";
    var scr = $("scrubber");
    scr.setAttribute("aria-valuenow", String(hour));
    scr.setAttribute("aria-valuetext", dayHour(sc, hour).label);
    updateCharts();
    updateCounters(dtMs || 16, snap);
    if (hour !== state.lastHour) {
      onHour(hour, snap);
      state.lastHour = hour;
    }
  }
  function fact(label, value) {
    var s = el("span"); s.appendChild(document.createTextNode(label + " ")); s.appendChild(el("b", "num", value)); return s;
  }
  function onHour(hour, snap) {
    var sc = state.sc, d = sc.agent.decisions[hour];
    $("clock-when").textContent = dayHour(sc, hour).label;
    var facts = $("clock-facts");
    facts.textContent = "";
    var hi = d3.max(sc.price), price = sc.price[hour];
    facts.appendChild(el("span", "occ-pill" + (price >= hi * 0.8 ? " peak" : ""), price >= hi * 0.8 ? "Peak price" : "Price " + (price <= d3.min(sc.price) * 1.05 ? "low" : "mid")));
    facts.appendChild(fact("Price", "$" + fmt(price, 3) + "/kWh"));
    facts.appendChild(fact("Outdoor", fmt(sc.outdoor_c[hour], 1) + "°C"));
    facts.appendChild(fact("Grid carbon", fmt(sc.carbon[hour], 3) + " kg/kWh"));
    var st = $("plan-status");
    st.textContent = "";
    st.appendChild(statusTag(d.status));
    renderReasons(hour);
    if (d.status !== "ok" && !snap) {
      if (d.status === "fallback") pulse($("district-agent"), "fallback");
      var hit = {};
      d.clamps.forEach(function (c) { hit[c.point.split(".")[0]] = 1; });
      Object.keys(hit).forEach(function (b) { if (tiles.agent[b]) pulse(tiles.agent[b].tile, "clamp"); });
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
    $("play-hero-label").textContent = on ? "Pause" : (state.t > 0 && state.t < state.sc.hours - 1 ? "Resume" : "Play the month");
    if (on) { state.lastFrame = 0; requestAnimationFrame(tick); }
  }
  function seek(t, snap) {
    state.t = clamp(t, 0, state.sc.hours - 1);
    frame(!!snap);
  }

  // ---------- static sections ----------
  function controllerName(r) {
    if (r.supervisor === "scripted") return "the rule-based controller (scripted replies, no model calls)";
    if (r.supervisor === "hold") return "the no-control actions held through the envelope";
    return r.model_id;
  }
  function renderHero() {
    var sc = state.sc, h = sc.headline, r = sc.agent_run;
    var eb = $("eyebrow");
    eb.textContent = "";
    if (sc.agent_sample) eb.appendChild(el("span", "tag sample", "Sample agent"));
    ["CityLearn 2023 challenge", DATA.buildings.length + " buildings", (sc.hours < 48 ? sc.hours + " hours" : Math.round(sc.hours / 24) + " days") + ", hourly"].forEach(function (s, i) {
      if (i) eb.appendChild(el("span", "dot"));
      eb.appendChild(el("span", "", s));
    });
    var h1 = $("headline");
    h1.textContent = "";
    h1.appendChild(el("span", h.tone === "loss" ? "tone-loss" : "", (sc.agent_sample ? "Sample: " : "") + h.text + "."));
    $("lede").textContent = "CityLearn's no-control reference versus " + controllerName(r) +
      " deciding every hour for all " + DATA.buildings.length + " buildings: heat pump, hot water tank and battery. " +
      "Every action passed a deterministic safety envelope: " + r.clamped_hours + " hours were clamped and " +
      r.fallback_hours + " fell back to the reference actions. Scores are CityLearn's own KPIs.";
    var host = $("deltas");
    host.textContent = "";
    [["Cost", h.cost_pct, "%"], ["Emissions", h.emissions_pct, "%"], ["Discomfort", h.discomfort_points, " pts"]].forEach(function (p) {
      var box = el("div", "delta");
      box.appendChild(el("div", "label", p[0]));
      box.appendChild(el("div", "value num", p[1] == null ? "n/a" : signed(p[1], 1, p[2])));
      var same = p[1] == null || Math.abs(p[1]) < 0.05, better = !same && p[1] < 0;
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
    var sc = state.sc, host = $("scorecard");
    host.textContent = "";
    var card = el("article", "card score");
    var head = el("div", "card-head");
    var title = el("div", "card-title", "District KPIs");
    if (sc.agent_sample) title.appendChild(el("span", "tag sample", "Sample agent"));
    head.appendChild(title);
    head.appendChild(el("span", "card-sub", sc.hours + " hours" + (sc.hours < (sc.episode_hours || sc.hours) ? ", partial" : "")));
    card.appendChild(head);
    var table = el("table"), thead = el("thead"), tr = el("tr");
    ["KPI", "Baseline", "Agent", "Change"].forEach(function (t) { tr.appendChild(el("th", "", t)); });
    thead.appendChild(tr); table.appendChild(thead);
    var tb = el("tbody");
    DATA.kpis.forEach(function (k) {
      var b = sc.baseline.kpi[k.id], a = sc.agent.kpi[k.id];
      if (b == null && a == null) return;
      var row = el("tr");
      var c0 = el("td"); c0.appendChild(document.createTextNode(k.name)); c0.appendChild(el("span", "unit", k.id + ", " + k.unit));
      row.appendChild(c0);
      row.appendChild(el("td", "", fmt(b, 3)));
      row.appendChild(el("td", "", fmt(a, 3)));
      var share = k.unit.indexOf("share") === 0;
      var change = a == null || b == null ? null : share ? (a - b) * 100 : pct(a, b);
      var cls = change == null || Math.abs(change) < 0.05 ? "" : change < 0 ? "better" : "worse";
      var td = el("td", "chg " + cls);
      if (cls) td.insertAdjacentHTML("afterbegin", cls === "better" ? ICON.down : ICON.up);
      td.appendChild(document.createTextNode(change == null ? "n/a" : cls ? signed(change, 1, share ? " pts" : "%") : "same"));
      row.appendChild(td);
      tb.appendChild(row);
    });
    table.appendChild(tb);
    card.appendChild(table);
    host.appendChild(card);

    var r = sc.agent_run, n = sc.hours - 1;
    var card2 = el("article", "card score");
    var head2 = el("div", "card-head");
    head2.appendChild(el("div", "card-title", "Run and totals"));
    head2.appendChild(el("span", "card-sub", "Totals are sums of CityLearn's hourly series"));
    card2.appendChild(head2);
    var t2 = el("table"), th2 = el("thead"), tr2 = el("tr");
    ["Total", "Baseline", "Agent"].forEach(function (t) { tr2.appendChild(el("th", "", t)); });
    th2.appendChild(tr2); t2.appendChild(th2);
    var tb2 = el("tbody");
    [["Electricity cost", "$", "cost_usd", 2], ["Emissions, kg CO2", "", "emission_kg", 0], ["Uncomfortable building hours", "", "discomfort_h", 0]].forEach(function (row) {
      var tr3 = el("tr");
      tr3.appendChild(el("td", "", row[0]));
      tr3.appendChild(el("td", "", row[1] + fmt(sc.baseline[row[2]][n], row[3])));
      tr3.appendChild(el("td", "", row[1] + fmt(sc.agent[row[2]][n], row[3])));
      tb2.appendChild(tr3);
    });
    t2.appendChild(tb2);
    card2.appendChild(t2);
    var facts = el("div", "facts");
    [["Model", r.supervisor === "scripted" ? "Rule-based, no API" : r.supervisor === "hold" ? "Baseline hold, no API" : r.model_id],
     ["Run cost", "$" + fmt(r.cost_usd, 2) + " / $" + fmt(r.budget_usd, 2)],
     ["Model calls", fmt(r.calls, 0)],
     ["Clamped hours", fmt(r.clamped_hours, 0)],
     ["Fallback hours", fmt(r.fallback_hours, 0)],
     ["Budget stop", r.budget_stopped ? "hit" : "not hit"]].forEach(function (f) {
      var d = el("div"); d.appendChild(el("div", "k", f[0])); d.appendChild(el("div", "v", f[1])); facts.appendChild(d);
    });
    card2.appendChild(facts);
    host.appendChild(card2);
  }
  function renderBuildingChips() {
    var host = $("building-chips");
    host.textContent = "";
    DATA.buildings.forEach(function (b, i) {
      var btn = el("button", "", "B" + (i + 1));
      btn.type = "button";
      btn.title = b.name;
      btn.setAttribute("aria-pressed", b.id === state.building ? "true" : "false");
      btn.addEventListener("click", function () { state.building = b.id; renderBuildingChips(); drawCharts(); frame(true); });
      host.appendChild(btn);
    });
  }

  // ---------- boot ----------
  var bound = false, tilesBuilt = false;
  function bindOnce() {
    if (bound) return;
    bound = true;
    bindScrubber();
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
      if (Math.abs(window.innerWidth - lastW) < 40 || !state.sc) return;
      lastW = window.innerWidth;
      buildScrubber(); drawCharts(); frame(true);
    });
    document.addEventListener("keydown", function (e) {
      if (e.key === " " && e.target === document.body && state.sc) { setPlaying(!state.playing); e.preventDefault(); }
    });
  }
  function showEmpty(title, text) {
    $("headline").textContent = title;
    $("lede").textContent = text;
    $("stage").hidden = true;
    document.querySelector(".race").hidden = true;
    $("play-hero").hidden = true;
  }
  // follow: jump to the newest hour and let it glow, as a live run does.
  function renderAll(follow) {
    state.sc = DATA.scenarios[0];
    if (!state.building || !DATA.buildings.some(function (b) { return b.id === state.building; })) state.building = DATA.buildings[0].id;
    $("stage").hidden = false;
    document.querySelector(".race").hidden = false;
    $("play-hero").hidden = false;
    if (follow && state.playing) setPlaying(false);
    renderHero(); renderScorecard(); renderBuildingChips();
    if (!tilesBuilt) { buildTiles(); buildCounters(); tilesBuilt = true; }
    buildScrubber(); drawPriceStrip(); drawCharts();
    bindOnce();
    if (follow) {
      var last = state.sc.hours - 1, changed = last !== state.lastHour;
      state.t = last;
      frame(true);
      if (changed) {
        var d = state.sc.agent.decisions[last];
        if (d && d.status !== "ok") {
          if (d.status === "fallback") pulse($("district-agent"), "fallback");
          d.clamps.forEach(function (c) { var b = c.point.split(".")[0]; if (tiles.agent[b]) pulse(tiles.agent[b].tile, "clamp"); });
        }
      }
    } else {
      frame(true);
    }
  }
  window.HyperbolicViewer = {
    render: function (data, opts) {
      if (!data || !data.scenarios || !data.scenarios.length || data.scenarios[0].hours < 2 || typeof d3 === "undefined") return false;
      DATA = data;
      renderAll(!!(opts && opts.follow));
      return true;
    },
    empty: showEmpty
  };
  function boot() {
    // The version comes from assets/version.js, which tests keep equal to the package version.
    var v = window.HYPERBOLIC_VERSION;
    if (v && $("app-version")) $("app-version").textContent = "Hyperbolic " + v;
    setTheme(document.documentElement.getAttribute("data-theme") === "light" ? "light" : "dark");
    $("theme-toggle").addEventListener("click", function () {
      setTheme(document.documentElement.getAttribute("data-theme") === "dark" ? "light" : "dark");
    });
    if (!DATA || !DATA.scenarios || !DATA.scenarios.length || typeof d3 === "undefined") {
      showEmpty(!DATA || !DATA.scenarios || !DATA.scenarios.length ? "No runs yet" : "Charts could not load",
        "Run the commands below to record a baseline and an agent run, then rebuild this page's data.");
      return;
    }
    renderAll(false);
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", boot); else boot();
})();
