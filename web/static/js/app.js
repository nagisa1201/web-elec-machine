/* Dashboard controller: wires the JSON API to the DOM and the charts. */
(function () {
  "use strict";

  const PHASE_COLOR = { a: "#4f8cff", b: "#34d399", c: "#f59e0b" };
  const PHASE_NAME = { a: "A 相电压", b: "B 相电压", c: "C 相电压" };

  const state = {
    meter: null,
    day: null, // "YYYY-MM-DD"
    nominalVolts: 220, // nominal grid voltage, refreshed from /api/health
    outageLow: 30, // outage threshold, refreshed from /api/health
    lastUpdate: null, // epoch ms of the last successful realtime fetch
    liveChart: null,
    historyChart: null,
    healthTimer: null,
    realtimeTimer: null,
    statsTimer: null,
  };

  const el = (id) => document.getElementById(id);

  function toLocalDate(d) {
    const y = d.getFullYear();
    const m = String(d.getMonth() + 1).padStart(2, "0");
    const day = String(d.getDate()).padStart(2, "0");
    return y + "-" + m + "-" + day;
  }

  function fmtClock(d) {
    const p = (n) => String(n).padStart(2, "0");
    return p(d.getHours()) + ":" + p(d.getMinutes()) + ":" + p(d.getSeconds());
  }

  function fmtTime(iso) {
    if (!iso) return "—";
    return fmtClock(new Date(iso));
  }

  function fmtVoltage(v) {
    return (v === null || v === undefined) ? "—" : v.toFixed(1);
  }

  function fmtDuration(seconds) {
    if (seconds === null || seconds === undefined || seconds === 0) return "0";
    const s = Math.round(seconds);
    if (s < 60) return s + " 秒";
    if (s < 3600) return Math.round(s / 60) + " 分钟";
    return (s / 3600).toFixed(1) + " 小时";
  }

  function fmtAgo(ts) {
    if (!ts) return "—";
    const s = Math.max(0, Math.round((Date.now() - ts) / 1000));
    if (s < 5) return "刚刚";
    if (s < 60) return s + " 秒前";
    return Math.round(s / 60) + " 分钟前";
  }

  // Classify a voltage reading against the configured thresholds.
  function classifyVoltage(v) {
    if (v === null || v === undefined || !Number.isFinite(v)) {
      return { label: "暂无数据", tone: "idle" };
    }
    if (v < state.outageLow) return { label: "电压异常", tone: "bad" };
    if (v < state.nominalVolts * 0.9) return { label: "电压偏低", tone: "warn" };
    if (v > state.nominalVolts * 1.1) return { label: "电压偏高", tone: "warn" };
    return { label: "正常", tone: "ok" };
  }

  function setStatus(stateName, text) {
    const node = el("status");
    node.setAttribute("data-state", stateName);
    node.querySelector(".status-text").textContent = text;
  }

  function tickClock() {
    el("clock").textContent = fmtClock(new Date());
    if (state.lastUpdate) {
      el("hero-updated").textContent = "最后更新 " + fmtAgo(state.lastUpdate);
    }
  }

  // ----------------------------------------------------------------- health

  async function loadHealth() {
    let health;
    try {
      health = await window.api.health();
    } catch (err) {
      setStatus("offline", "未连接");
      el("footer-info").textContent = "无法连接服务器";
      return;
    }

    if (Number.isFinite(health.nominal_volts)) state.nominalVolts = health.nominal_volts;
    if (Number.isFinite(health.outage_low_volts)) state.outageLow = health.outage_low_volts;

    if (!health.db_available || health.meters.length === 0) {
      setStatus("online", "已连接 · 无数据");
    } else {
      setStatus("online", "已连接");
    }
    el("footer-info").textContent =
      health.service + " v" + health.version +
      (health.polling ? " · 采集运行中" : "") +
      " · 数据库 " + health.db;

    // Keep the live chart's nominal reference line in sync with the server.
    state.liveChart.options.referenceLines = [{
      value: state.nominalVolts,
      label: state.nominalVolts + "V 额定",
      color: "rgba(245, 158, 11, 0.55)",
      dash: [4, 4],
    }];

    populateMeters(health.meters);
  }

  function populateMeters(meters) {
    const select = el("meter-select");
    const current = state.meter;
    select.innerHTML = "";
    if (meters.length === 0) {
      select.disabled = true;
      select.add(new Option("暂无电表", ""));
      return;
    }
    select.disabled = false;
    meters.forEach((m) => select.add(new Option(m, m)));
    if (current && meters.indexOf(current) >= 0) {
      select.value = current;
    } else {
      select.value = meters[0];
      state.meter = meters[0];
      onMeterChanged();
    }
  }

  async function onMeterChanged() {
    state.day = null;
    try {
      const days = await window.api.days(state.meter);
      if (days.days && days.days.length > 0) {
        state.day = days.days[0];
        el("day-picker").value = state.day;
      }
    } catch (err) {
      /* a fresh meter may have no data yet */
    }
    await refreshAll();
  }

  // ------------------------------------------------------------------ refresh

  async function refreshAll() {
    await Promise.all([loadRealtime(), loadHistory(), loadStats()]);
  }

  async function loadRealtime() {
    if (!state.meter) return;
    try {
      const data = await window.api.realtime(state.meter);
      state.lastUpdate = Date.now();
      el("live-window").textContent = "最近 " + data.minutes + " 分钟";
      renderHero(data);
      renderPhaseCards(data);
      const hasPoints = data.series.some((s) => s.points && s.points.length > 0);
      el("live-empty").classList.toggle("hidden", hasPoints);
      state.liveChart.setSeries(data.series);
    } catch (err) {
      el("live-empty").classList.remove("hidden");
    }
  }

  function renderHero(data) {
    const phase = (data.phases && data.phases[0]) || null;
    const series =
      (data.series || []).find((s) => !phase || s.phase === phase) ||
      (data.series || [])[0];
    const pts = series && series.points;
    const latest = pts && pts.length ? pts[pts.length - 1] : null;
    const value = latest ? latest[1] : null;
    const cls = classifyVoltage(value);

    const valueEl = el("hero-value");
    valueEl.textContent = fmtVoltage(value);
    valueEl.setAttribute("data-tone", cls.tone);
    el("hero-phase").textContent = phase ? (PHASE_NAME[phase] || phase) : "电压";
    const statusEl = el("hero-status");
    statusEl.textContent = cls.label;
    statusEl.setAttribute("data-tone", cls.tone);
    el("hero-updated").textContent = "最后更新 " + fmtAgo(state.lastUpdate);
  }

  function renderPhaseCards(data) {
    const container = el("phase-cards");
    container.innerHTML = "";
    const latest = {};
    data.series.forEach((s) => {
      const pts = s.points;
      if (pts && pts.length > 0) latest[s.phase] = pts[pts.length - 1];
    });

    const phases = data.phases && data.phases.length ? data.phases : [];
    if (phases.length === 0) {
      container.innerHTML = '<div class="phase-card"><span class="phase-name">等待数据…</span></div>';
      return;
    }
    phases.forEach((phase) => {
      const point = latest[phase];
      const card = document.createElement("div");
      card.className = "phase-card";
      const value = point ? point[1] : null;
      const cls = classifyVoltage(value);
      card.innerHTML =
        '<span class="phase-name"><span class="swatch" style="background:' +
        (PHASE_COLOR[phase] || "#9ca3af") + '"></span>' + (PHASE_NAME[phase] || phase) +
        '</span>' +
        '<span class="phase-value" data-tone="' + cls.tone + '">' + fmtVoltage(value) +
        '<span class="phase-unit">V</span></span>' +
        '<span class="phase-status" data-tone="' + cls.tone + '">' + cls.label + '</span>' +
        '<span class="phase-time">' + (point ? fmtTime(point[0]) : "—") + "</span>";
      container.appendChild(card);
    });
  }

  async function loadHistory() {
    if (!state.meter || !state.day) {
      el("history-empty").classList.remove("hidden");
      return;
    }
    try {
      const data = await window.api.series(state.meter, state.day);
      const hasPoints = data.series.some((s) => s.points && s.points.length > 0);
      el("history-empty").classList.toggle("hidden", hasPoints);
      state.historyChart.setSeries(data.series);
    } catch (err) {
      el("history-empty").classList.remove("hidden");
    }
  }

  async function loadStats() {
    if (!state.meter || !state.day) return;
    el("stats-date").textContent = state.day;
    try {
      const stats = await window.api.stats(state.meter, state.day);
      renderStats(stats);
    } catch (err) {
      renderStats(null);
    }
  }

  function renderStats(stats) {
    el("stat-max").textContent = stats && stats.max ? fmtVoltage(stats.max.value) + " V" : "—";
    el("stat-max-time").textContent = stats && stats.max ? fmtTime(stats.max.time) : "—";
    el("stat-min").textContent = stats && stats.min ? fmtVoltage(stats.min.value) + " V" : "—";
    el("stat-min-time").textContent = stats && stats.min ? fmtTime(stats.min.time) : "—";
    el("stat-outage-count").textContent = stats ? String(stats.outage_count) : "—";
    el("stat-outage-duration").textContent = stats ? fmtDuration(stats.outage_seconds) : "—";

    // Highlight the day's extrema on the history curve.
    const markers = [];
    if (stats && stats.max) {
      markers.push({ time: stats.max.time, value: stats.max.value, color: "#f59e0b", radius: 4 });
    }
    if (stats && stats.min) {
      markers.push({ time: stats.min.time, value: stats.min.value, color: "#34d399", radius: 4 });
    }
    state.historyChart.setMarkers(markers);

    const list = el("outage-list");
    list.innerHTML = "";
    if (!stats || !stats.outages || stats.outages.length === 0) {
      list.innerHTML = '<p class="muted">当日无停电记录</p>';
      return;
    }
    stats.outages.forEach((o) => {
      const ongoing = Date.now() - new Date(o.end).getTime() < 60000;
      const row = document.createElement("div");
      row.className = "outage-item";
      if (ongoing) row.classList.add("outage-ongoing");
      row.innerHTML =
        '<span class="outage-time">' + fmtTime(o.start) + " — " + fmtTime(o.end) + "</span>" +
        '<span class="outage-dur">' + fmtDuration(o.seconds) +
        (ongoing ? ' <span class="outage-badge">进行中</span>' : "") + "</span>";
      list.appendChild(row);
    });
  }

  // -------------------------------------------------------------- day nav

  function shiftDay(delta) {
    if (!state.day) return;
    const d = new Date(state.day + "T12:00:00");
    d.setDate(d.getDate() + delta);
    state.day = toLocalDate(d);
    el("day-picker").value = state.day;
    loadHistory();
    loadStats();
  }

  function onDayPicked() {
    state.day = el("day-picker").value;
    loadHistory();
    loadStats();
  }

  // ------------------------------------------------------------------- init

  function init() {
    state.liveChart = new window.LineChart(el("live-chart"), {
      yUnit: "V",
      fill: true,
      xFormat: (d) => fmtClock(d),
      referenceLines: [{
        value: state.nominalVolts,
        label: state.nominalVolts + "V 额定",
        color: "rgba(245, 158, 11, 0.55)",
        dash: [4, 4],
      }],
    });
    state.historyChart = new window.LineChart(el("history-chart"), {
      yUnit: "V",
      xLabelCount: 8,
      xFormat: (d) =>
        String(d.getHours()).padStart(2, "0") + ":" + String(d.getMinutes()).padStart(2, "0"),
    });

    el("meter-select").addEventListener("change", () => {
      state.meter = el("meter-select").value;
      onMeterChanged();
    });
    el("prev-day").addEventListener("click", () => shiftDay(-1));
    el("next-day").addEventListener("click", () => shiftDay(1));
    el("day-picker").addEventListener("change", onDayPicked);

    tickClock();
    setInterval(tickClock, 1000);

    loadHealth();
    state.healthTimer = setInterval(loadHealth, 5000);
    state.realtimeTimer = setInterval(loadRealtime, 5000);
    // Stats (outage count/duration) must refresh too, so an outage that is
    // still in progress keeps counting up without a manual page reload.
    state.statsTimer = setInterval(loadStats, 15000);
  }

  document.addEventListener("DOMContentLoaded", init);
})();
