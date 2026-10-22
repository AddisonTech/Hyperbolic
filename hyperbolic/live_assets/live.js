/* Hyperbolic live mode. Loaded only by `hyperbolic serve`, never by the published replay.
   Builds the viewer's scenario hour by hour from the server's event stream and hands it to
   window.HyperbolicViewer.render, so the live page is the same viewer as the replay. */
(function () {
  "use strict";
  if (!window.HYPERBOLIC_LIVE) return;

  var $ = function (id) { return document.getElementById(id); };
  var cfg = null, source = null, data = null, sc = null, names = [], ui = {};
  var renderPending = false, lastRender = 0, phase = "idle", lastFinished = false;
  var LOG_MAX = 400;

  function el(tag, cls, text) {
    var e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text != null) e.textContent = text;
    return e;
  }
  function fmt(v, d) {
    if (v == null || isNaN(v)) return "n/a";
    return v.toLocaleString("en-US", { minimumFractionDigits: d, maximumFractionDigits: d });
  }
  function money(v) { return "$" + fmt(v, v < 0.1 ? 4 : 2); }
  function pad(n) { return String(n).padStart(2, "0"); }
  function hourLabel(day, hourOfDay) { return "Day " + day + ", " + pad(hourOfDay - 1) + ":00"; }
  function post(path, body) {
    return fetch(path, {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-Hyperbolic-Live": "1" },
      body: JSON.stringify(body || {})
    }).then(function (r) { return r.json().then(function (j) { return { ok: r.ok, body: j }; }); });
  }

  // ---------- panel ----------
  function field(label, control) {
    var f = el("label", "live-field");
    f.appendChild(el("span", "live-label", label));
    f.appendChild(control);
    return f;
  }
  function button(id, text, cls) {
    var b = el("button", "live-btn " + (cls || ""), text);
    b.type = "button"; b.id = id;
    return b;
  }
  function buildPanel() {
    var section = el("section", "live");
    section.id = "live";
    section.setAttribute("aria-labelledby", "live-title");
    var card = el("article", "card live-card");
    var head = el("div", "card-head");
    var title = el("div", "card-title", "Live run");
    title.id = "live-title";
    title.appendChild(el("span", "live-dot"));
    head.appendChild(title);
    ui.state = el("span", "live-state", "Idle");
    ui.state.id = "live-state";
    ui.state.setAttribute("aria-live", "polite");
    head.appendChild(ui.state);
    card.appendChild(head);

    var body = el("div", "live-body");
    var row = el("div", "live-controls");
    ui.duration = el("select"); ui.duration.id = "live-duration";
    cfg.durations.forEach(function (d) { var o = el("option", "", d.label); o.value = String(d.hours); ui.duration.appendChild(o); });
    var custom = el("option", "", "Custom hours"); custom.value = "custom"; ui.duration.appendChild(custom);
    ui.hours = el("input"); ui.hours.id = "live-hours"; ui.hours.type = "number"; ui.hours.min = "1";
    ui.hours.max = String(cfg.episode_hours); ui.hours.value = "47"; ui.hours.hidden = true;
    ui.hours.setAttribute("aria-label", "Custom hour count");
    var dur = el("span", "live-inline"); dur.appendChild(ui.duration); dur.appendChild(ui.hours);
    row.appendChild(field("Duration", dur));

    ui.controller = el("select"); ui.controller.id = "live-controller";
    cfg.controllers.forEach(function (c) {
      var o = el("option", "", c.label + (c.available ? "" : " (needs API key)"));
      o.value = c.id; o.disabled = !c.available; ui.controller.appendChild(o);
    });
    var first = cfg.controllers.filter(function (c) { return c.available; })[0];
    if (first) ui.controller.value = first.id;
    row.appendChild(field("Controller", ui.controller));

    ui.budget = el("input"); ui.budget.id = "live-budget"; ui.budget.type = "number"; ui.budget.min = "0.01";
    ui.budget.step = "0.5"; ui.budget.max = String(cfg.max_budget_usd); ui.budget.value = fmt(cfg.default_budget_usd, 2);
    row.appendChild(field("Budget, USD", ui.budget));

    var btns = el("div", "live-buttons");
    ui.start = button("live-start", "Start", "primary");
    ui.pause = button("live-pause", "Pause");
    ui.resume = button("live-resume", "Resume");
    ui.stop = button("live-stop", "Stop", "danger");
    [ui.start, ui.pause, ui.resume, ui.stop].forEach(function (b) { btns.appendChild(b); });
    row.appendChild(btns);
    body.appendChild(row);

    ui.estimate = el("p", "live-note"); ui.estimate.id = "live-estimate";
    body.appendChild(ui.estimate);
    if (!cfg.key.present) {
      ui.keynote = el("p", "live-note warn", "No API key found on this computer, so the Claude options are off. " +
        "Set " + cfg.key.variables[1] + " and restart `hyperbolic serve` to use them. The rule-based and baseline controllers work without one.");
      body.appendChild(ui.keynote);
    }
    ui.message = el("p", "live-note warn"); ui.message.hidden = true;
    body.appendChild(ui.message);

    var stats = el("div", "live-stats");
    function stat(label) {
      var s = el("div", "live-stat"); s.appendChild(el("span", "k", label)); var v = el("span", "v num", "n/a"); s.appendChild(v);
      stats.appendChild(s); return v;
    }
    ui.progress = stat("Hour");
    var spend = el("div", "live-stat wide");
    spend.appendChild(el("span", "k", "API spend"));
    ui.spend = el("span", "v num", "$0.00");
    spend.appendChild(ui.spend);
    var meter = el("span", "live-meter"); ui.meter = el("i"); meter.appendChild(ui.meter); spend.appendChild(meter);
    ui.meter.parentNode.id = "live-cost-meter";
    stats.appendChild(spend);
    ui.peak = stat("District draw vs peak target");
    ui.counts = stat("Calls, clamped, fallback");
    body.appendChild(stats);

    ui.result = el("div", "live-result"); ui.result.hidden = true;
    body.appendChild(ui.result);
    card.appendChild(body);
    section.appendChild(card);

    var logCard = el("article", "card live-log-card");
    var lh = el("div", "card-head");
    lh.appendChild(el("div", "card-title", "Live log"));
    ui.logSub = el("span", "card-sub", "The agent's reason for every hour, newest first");
    lh.appendChild(ui.logSub);
    logCard.appendChild(lh);
    ui.log = el("ol", "live-log"); ui.log.id = "live-log"; ui.log.setAttribute("aria-live", "polite");
    logCard.appendChild(ui.log);
    var main = $("main"), hero = document.querySelector(".hero");
    main.insertBefore(section, hero);
    // The log sits right under the district tiles, so both are in view while a run plays.
    var logSection = el("section", "live live-log-section");
    logSection.setAttribute("aria-label", "Live log");
    logSection.appendChild(logCard);
    main.insertBefore(logSection, document.querySelector(".race"));

    ui.duration.addEventListener("change", function () { ui.hours.hidden = ui.duration.value !== "custom"; updateEstimate(); });
    [ui.hours, ui.budget, ui.controller].forEach(function (c) { c.addEventListener("input", updateEstimate); c.addEventListener("change", updateEstimate); });
    ui.start.addEventListener("click", start);
    ui.pause.addEventListener("click", function () { post("/api/pause"); });
    ui.resume.addEventListener("click", function () { post("/api/resume"); });
    ui.stop.addEventListener("click", function () { post("/api/stop"); });
    updateEstimate();
    setPhase("idle");
  }

  function chosenHours() {
    return ui.duration.value === "custom" ? parseInt(ui.hours.value, 10) : parseInt(ui.duration.value, 10);
  }
  function hoursProblem(h) {
    if (!h || h < 1 || h > cfg.episode_hours) return "Pick between 1 and " + cfg.episode_hours + " hours.";
    if (h + 1 >= 48 && (h + 1) % 24 !== 0) return cfg.hours_rule;
    return null;
  }
  function updateEstimate() {
    var h = chosenHours(), budget = parseFloat(ui.budget.value), c = ui.controller.value, est = cfg.estimates[c];
    var problem = hoursProblem(h);
    if (problem) { ui.estimate.textContent = problem; ui.estimate.className = "live-note warn"; return; }
    ui.estimate.className = "live-note";
    if (!est || est.per_hour === 0) { ui.estimate.textContent = "No model calls, so no API cost. " + h + " hours."; return; }
    var total = est.per_hour * h, text = "Estimated cost about " + money(total) + " for " + h + " hours (" + money(est.per_hour) + " per hour, from " + est.source + ").";
    if (budget > 0 && total > budget) {
      text += " The budget stop would end model calls near hour " + Math.max(1, Math.floor(budget / est.per_hour)) + "; the hours after it keep the baseline action.";
      ui.estimate.className = "live-note warn";
    }
    ui.estimate.textContent = text;
  }

  function setPhase(p, detail) {
    phase = p;
    var busy = p === "starting" || p === "baseline" || p === "running" || p === "paused" || p === "stopping";
    [ui.duration, ui.hours, ui.controller, ui.budget, ui.start].forEach(function (c) { c.disabled = busy; });
    ui.pause.disabled = p !== "running";
    ui.resume.disabled = p !== "paused";
    ui.stop.disabled = !(p === "running" || p === "paused" || p === "baseline");
    var labels = { idle: "Idle", starting: "Starting", baseline: "Simulating the baseline", running: "Running", paused: "Paused",
      stopping: "Stopping", finished: lastFinished ? "Finished" : "Stopped, saved as partial", error: "Error" };
    ui.state.textContent = (labels[p] || p) + (detail ? ": " + detail : "");
    ui.state.className = "live-state " + p;
    document.getElementById("live").classList.toggle("busy", busy);
  }

  function start() {
    var h = chosenHours(), problem = hoursProblem(h);
    if (problem) { showMessage(problem); return; }
    ui.message.hidden = true;
    setPhase("starting");
    post("/api/start", { hours: h, controller: ui.controller.value, budget_usd: parseFloat(ui.budget.value) }).then(function (r) {
      if (!r.ok) { showMessage(r.body.error || "Could not start."); setPhase("idle"); }
    });
  }
  function showMessage(text) { ui.message.textContent = text; ui.message.hidden = false; }

  // ---------- scenario, one hour at a time ----------
  function side() {
    var o = { buildings: {}, district_grid_kwh: [], cost_usd: [], emission_kg: [], discomfort_h: [], kpi: {}, run: "", steps: 0, complete: false };
    names.forEach(function (b) { o.buildings[b] = { indoor_c: [], battery_soc: [], dhw_soc: [], grid_kwh: [] }; });
    return o;
  }
  function onStart(ev) {
    names = ev.shell.buildings.map(function (b) { return b.id; });
    sc = {
      id: ev.shell.dataset, name: ev.dataset_name, hours: 0, episode_hours: ev.hours,
      baseline_sample: false, agent_sample: ev.sample, hour_of_day: [], day: [], price: [], carbon: [], outdoor_c: [],
      setpoint_c: {}, occupied: {}, baseline: side(), agent: side(),
      agent_run: { supervisor: ev.supervisor.kind, model_key: ev.supervisor.model_key, model_id: ev.supervisor.model_id,
        budget_usd: ev.budget_usd, cost_usd: 0, calls: 0, clamped_hours: 0, fallback_hours: 0, budget_stopped: false, envelope: null },
      headline: { tone: "mixed", text: "Starting", cost_pct: null, emissions_pct: null, discomfort_points: null }
    };
    sc.baseline.run = ev.baseline_run; sc.agent.run = ev.agent_run;
    sc.agent.decisions = []; sc.agent.actions = {};
    names.forEach(function (b) { sc.setpoint_c[b] = []; sc.occupied[b] = []; sc.agent.actions[b] = { cooling: [], dhw: [], battery: [] }; });
    data = { schema: ev.shell.schema, dataset: ev.shell.dataset, comfort_band_k: ev.shell.comfort_band_k,
      buildings: ev.shell.buildings, kpis: ev.shell.kpis, sample: ev.sample, scenarios: [sc] };
    ui.log.textContent = "";
    ui.result.hidden = true; ui.result.textContent = "";
    ui.logSub.textContent = ev.label + ", " + ev.hours + " hours, budget " + money(ev.budget_usd);
    ui.progress.textContent = "0 of " + ev.hours;
    ui.spend.textContent = money(0) + " of " + money(ev.budget_usd);
    ui.meter.style.width = "0%";
    ui.peak.textContent = "n/a"; ui.counts.textContent = "0, 0, 0";
    var sub = document.querySelector("#score-title + .card-sub");
    if (sub) sub.textContent = "Running estimates from hourly outcomes while the run goes; CityLearn's own evaluate() when it finishes.";
    window.HyperbolicViewer.empty("Live run starting", ev.label + " for " + ev.hours + " hours. The first hours appear here as soon as they finish.");
  }
  function onHour(row) {
    if (!sc) return;
    sc.hours += 1;
    sc.hour_of_day.push(row.hour_of_day); sc.day.push(row.day); sc.price.push(row.price);
    sc.carbon.push(row.carbon); sc.outdoor_c.push(row.outdoor_c);
    names.forEach(function (b) { sc.setpoint_c[b].push(row.setpoint_c[b]); sc.occupied[b].push(row.occupied[b]); });
    ["baseline", "agent"].forEach(function (k) {
      var r = row[k], s = sc[k];
      names.forEach(function (b) { ["indoor_c", "battery_soc", "dhw_soc", "grid_kwh"].forEach(function (f) { s.buildings[b][f].push(r.buildings[b][f]); }); });
      ["district_grid_kwh", "cost_usd", "emission_kg", "discomfort_h"].forEach(function (f) { s[f].push(r[f]); });
      s.kpi = row.kpi[k]; s.steps = sc.hours;
    });
    sc.agent.decisions.push(row.agent.decision);
    names.forEach(function (b) { ["cooling", "dhw", "battery"].forEach(function (d) { sc.agent.actions[b][d].push(row.agent.actions[b][d]); }); });
    sc.headline = row.headline;
    var sp = row.spend, run = sc.agent_run;
    run.cost_usd = sp.usd; run.calls = sp.calls; run.clamped_hours = sp.clamped; run.fallback_hours = sp.fallback; run.budget_stopped = sp.budget_stopped;

    ui.progress.textContent = sc.hours + " of " + sc.episode_hours;
    ui.spend.textContent = money(sp.usd) + " of " + money(sp.budget_usd) + (sp.budget_stopped ? ", budget stop hit" : "");
    ui.meter.style.width = Math.min(100, sp.usd / sp.budget_usd * 100).toFixed(1) + "%";
    ui.meter.parentNode.classList.toggle("hit", !!sp.budget_stopped);
    var pk = row.peak;
    ui.peak.textContent = fmt(pk.drawn_kwh, 2) + " kWh" + (pk.target_kwh == null ? "" : " / " + fmt(pk.target_kwh, 2) + " kWh");
    ui.counts.textContent = sp.calls + ", " + sp.clamped + ", " + sp.fallback;
    addLog(row);
    scheduleRender();
  }
  function addLog(row) {
    var d = row.agent.decision, li = el("li", "live-entry " + d.status);
    var meta = el("div", "meta");
    meta.appendChild(el("span", "num", hourLabel(row.day, row.hour_of_day)));
    meta.appendChild(el("span", "tag " + d.status, d.status === "ok" ? "OK" : d.status === "clamped" ? "Clamped" : "Fallback"));
    meta.appendChild(el("span", "num cost", money(row.spend.usd)));
    li.appendChild(meta);
    var text = d.status === "fallback" ? "Baseline actions held. " + (d.fallback || "") : (d.reason || "No change requested.");
    li.appendChild(el("div", "text", text));
    if (d.clamps.length) {
      var ul = el("ul");
      d.clamps.slice(0, 3).forEach(function (c) {
        ul.appendChild(el("li", "", c.point.replace("_", " ") + ": " + c.reason));
      });
      if (d.clamps.length > 3) ul.appendChild(el("li", "", "+" + (d.clamps.length - 3) + " more"));
      li.appendChild(ul);
    }
    if (d.trim_ends && d.trim_ends.length) {
      var te = el("ul", "trim-ends");
      d.trim_ends.forEach(function (t) {
        te.appendChild(el("li", "", t.building.replace("_", " ") + ": trim ended early: " + t.reason));
      });
      li.appendChild(te);
    }
    ui.log.insertBefore(li, ui.log.firstChild);
    while (ui.log.childNodes.length > LOG_MAX) ui.log.removeChild(ui.log.lastChild);
  }
  function scheduleRender() {
    if (renderPending) return;
    renderPending = true;
    var wait = Math.max(0, 250 - (Date.now() - lastRender));
    setTimeout(function () {
      renderPending = false;
      lastRender = Date.now();
      if (window.HyperbolicViewer.render(data, { follow: true })) $("sample-banner").hidden = true;
    }, wait);
  }
  function onDone(ev) {
    lastFinished = ev.complete && !ev.stopped;
    var box = ui.result;
    box.textContent = "";
    box.appendChild(el("div", "live-result-title", lastFinished ? "Finished: " + ev.steps + " hours" : "Stopped after " + ev.steps + " of " + ev.hours + " hours, saved as partial"));
    var table = el("table"), thead = el("thead"), tr = el("tr");
    ["CityLearn KPI", "Baseline", "This run"].forEach(function (t) { tr.appendChild(el("th", "", t)); });
    thead.appendChild(tr); table.appendChild(thead);
    var tb = el("tbody");
    ev.kpis.forEach(function (k) {
      var r = el("tr");
      r.appendChild(el("td", "", k.name));
      r.appendChild(el("td", "num", fmt(k.baseline, 4)));
      var a = el("td", "num", fmt(k.agent, 4));
      if (k.baseline != null && k.agent != null && Math.abs(k.agent - k.baseline) > 5e-5) a.className += k.agent < k.baseline ? " better" : " worse";
      r.appendChild(a);
      tb.appendChild(r);
    });
    table.appendChild(tb);
    box.appendChild(table);
    var facts = el("p", "live-note", "API spend " + money(ev.cost_usd) + ", " + ev.calls + " calls, " + ev.clamped + " clamped hours, " +
      ev.fallback + " fallback hours" + (ev.budget_stopped ? ", budget stop hit" : "") + ". Recorded in " + ev.agent_run + "; replay it with `hyperbolic replay`.");
    box.appendChild(facts);
    var pub = button("live-publish", "Publish to docs/data", "primary");
    var note = el("p", "live-note"); note.id = "live-published";
    pub.addEventListener("click", function () {
      pub.disabled = true;
      post("/api/publish").then(function (r) {
        note.textContent = r.ok ? "Wrote " + r.body.written.join(" and ") + ". " + r.body.note : (r.body.error || "Could not publish.");
        pub.disabled = false;
      });
    });
    box.appendChild(pub);
    box.appendChild(note);
    box.hidden = false;
    fetch("/api/viewer").then(function (r) { return r.ok ? r.json() : null; }).then(function (full) {
      if (full && window.HyperbolicViewer.render(full, { follow: true })) {
        $("sample-banner").hidden = true;
        var sub = document.querySelector("#score-title + .card-sub");
        if (sub) sub.textContent = "From CityLearn's own evaluate(). Lower is better on every KPI.";
      }
    });
  }

  // A new run is starting: clear what the last one left on the panel.
  function clearRun(hours) {
    ui.log.textContent = "";
    ui.result.hidden = true; ui.result.textContent = "";
    ui.message.hidden = true;
    ui.progress.textContent = "0 of " + (hours || "n/a");
    ui.spend.textContent = money(0);
    ui.meter.style.width = "0%";
    ui.meter.parentNode.classList.remove("hit");
    ui.peak.textContent = "n/a"; ui.counts.textContent = "0, 0, 0";
  }

  // ---------- stream ----------
  function connect(since) {
    if (source) source.close();
    source = new EventSource("/api/events?since=" + since);
    source.addEventListener("start", function (e) { onStart(JSON.parse(e.data)); });
    source.addEventListener("hour", function (e) { onHour(JSON.parse(e.data)); });
    source.addEventListener("status", function (e) {
      var s = JSON.parse(e.data);
      if (s.state === "baseline") clearRun(s.hours);
      setPhase(s.state, s.detail);
    });
    source.addEventListener("done", function (e) { var d = JSON.parse(e.data); onDone(d); setPhase("finished"); });
    source.addEventListener("failed", function (e) { showMessage(JSON.parse(e.data).message); setPhase("error"); });
  }

  function boot() {
    Promise.all([fetch("/api/config").then(function (r) { return r.json(); }), fetch("/api/state").then(function (r) { return r.json(); })])
      .then(function (res) {
        cfg = res[0];
        buildPanel();
        var st = res[1];
        connect(st.first_event == null ? st.events : st.first_event);
      })
      .catch(function () {
        var p = el("p", "live-note warn", "Live mode could not reach `hyperbolic serve`. Is it still running?");
        $("main").insertBefore(p, $("main").firstChild);
      });
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", boot); else boot();
})();
