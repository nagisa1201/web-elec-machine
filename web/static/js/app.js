/* Dashboard controller: wires the JSON API to the DOM and the charts. */
(function () {
  "use strict";

  const PHASE_COLOR = { a: "#4f8cff", b: "#34d399", c: "#f59e0b" };
  const PHASE_NAME = { a: "A 相电压", b: "B 相电压", c: "C 相电压" };

  const state = {
    meter: null,
    day: null, // "YYYY-MM-DD"
    liveChart: null,
    historyChart: null,
    healthTimer: null,
    realtimeTimer: null,
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
    const d = new Date(iso);
    return fmtClock(d);
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

  function setStatus(stateName, text) {
    const node = el("status");
    node.setAttribute("data-state", stateName);
    node.querySelector(".status-text").textContent = text;
  }

  function tickClock() {
    el("clock").textContent = fmtClock(new Date());
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

    if (!health.db_available || health.meters.length === 0) {
      setStatus("online", "已连接 · 无数据");
    } else {
      setStatus("online", "已连接");
    }
    el("footer-info").textContent =
      health.service + " v" + health.version +
      (health.polling ? " · 采集运行中" : "") +
      " · 数据库 " + health.db;

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
      el("live-window").textContent = "最近 " + data.minutes + " 分钟";
      renderPhaseCards(data);
      const hasPoints = data.series.some((s) => s.points && s.points.length > 0);
      el("live-empty").classList.toggle("hidden", hasPoints);
      state.liveChart.setSeries(data.series);
    } catch (err) {
      el("live-empty").classList.remove("hidden");
    }
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
      card.innerHTML =
        '<span class="phase-name"><span class="swatch" style="background:' +
        (PHASE_COLOR[phase] || "#9ca3af") + '"></span>' + (PHASE_NAME[phase] || phase) +
        '</span>' +
        '<span class="phase-value">' + fmtVoltage(value) + '<span class="phase-unit">V</span></span>' +
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

    const list = el("outage-list");
    list.innerHTML = "";
    if (!stats || !stats.outages || stats.outages.length === 0) {
      list.innerHTML = '<p class="muted">当日无停电记录</p>';
      return;
    }
    stats.outages.forEach((o) => {
      const row = document.createElement("div");
      row.className = "outage-item";
      row.innerHTML =
        '<span class="outage-time">' + fmtTime(o.start) + " — " + fmtTime(o.end) + "</span>" +
        '<span class="outage-dur">' + fmtDuration(o.seconds) + "</span>";
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
  }

  document.addEventListener("DOMContentLoaded", init);
})();
