/* Self-contained canvas line chart for the voltage dashboard (no dependencies).
 *
 * A `LineChart` renders one or more time series onto a canvas with a Y axis
 * (voltage), an X axis (time), a legend, and a hover tooltip. It redraws on
 * container resize and keeps device-pixel-ratio crisp.
 */
(function () {
  "use strict";

  function niceStep(range, target) {
    const rough = range / Math.max(1, target);
    const power = Math.pow(10, Math.floor(Math.log10(rough)));
    const fraction = rough / power;
    let nice;
    if (fraction <= 1) nice = 1;
    else if (fraction <= 2) nice = 2;
    else if (fraction <= 2.5) nice = 2.5;
    else if (fraction <= 5) nice = 5;
    else nice = 10;
    return nice * power;
  }

  class LineChart {
    constructor(canvas, options) {
      this.canvas = canvas;
      this.ctx = canvas.getContext("2d");
      this.series = [];
      this.options = Object.assign(
        {
          yUnit: "V",
          yTicks: 5,
          padding: { top: 26, right: 16, bottom: 28, left: 46 },
          gridColor: "rgba(255,255,255,0.07)",
          axisColor: "rgba(255,255,255,0.25)",
          textColor: "#8b949e",
          lineWidth: 2,
          fill: false,
          xLabelCount: 6,
          mono: "SFMono-Regular, Consolas, monospace",
          xFormat: (d) =>
            d.getHours().toString().padStart(2, "0") + ":" +
            d.getMinutes().toString().padStart(2, "0"),
        },
        options || {}
      );
      this.hover = null;
      this._bind();
      window.addEventListener("resize", () => this.resize());
      this.resize();
    }

    setSeries(series) {
      this.series = series || [];
      this.hover = null;
      this.resize();
      this.draw();
    }

    _bind() {
      this.canvas.addEventListener("mousemove", (e) => {
        const rect = this.canvas.getBoundingClientRect();
        this.hover = { x: e.clientX - rect.left, y: e.clientY - rect.top };
        this.draw();
      });
      this.canvas.addEventListener("mouseleave", () => {
        this.hover = null;
        this.draw();
      });
    }

    resize() {
      const parent = this.canvas.parentElement;
      if (!parent) return;
      const dpr = window.devicePixelRatio || 1;
      const width = parent.clientWidth || this.canvas.clientWidth || 600;
      const height = parent.clientHeight || this.canvas.clientHeight || 260;
      this.canvas.width = Math.round(width * dpr);
      this.canvas.height = Math.round(height * dpr);
      this.canvas.style.width = width + "px";
      this.canvas.style.height = height + "px";
      this.ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      this._w = width;
      this._h = height;
      this.draw();
    }

    _bounds() {
      let minT = Infinity, maxT = -Infinity;
      let minV = Infinity, maxV = -Infinity;
      let count = 0;
      for (const s of this.series) {
        for (const p of s.points) {
          const t = new Date(p[0]).getTime();
          const v = p[1];
          if (Number.isFinite(t)) { minT = Math.min(minT, t); maxT = Math.max(maxT, t); }
          if (Number.isFinite(v)) { minV = Math.min(minV, v); maxV = Math.max(maxV, v); count++; }
        }
      }
      return { minT, maxT, minV, maxV, count };
    }

    _yScale(minV, maxV) {
      // Pad the voltage range so the trace never touches the top/bottom edge.
      const pad = Math.max(5, (maxV - minV) * 0.15);
      let lo = minV - pad, hi = maxV + pad;
      const step = niceStep(hi - lo, this.options.yTicks);
      lo = Math.floor(lo / step) * step;
      hi = Math.ceil(hi / step) * step;
      return { lo, hi, step };
    }

    _x(v) {
      const { padding } = this.options;
      return padding.left + (v - this._minT) / (this._maxT - this._minT || 1) *
        (this._w - padding.left - padding.right);
    }

    _y(v) {
      const { padding } = this.options;
      return this._h - padding.bottom - (v - this._lo) / (this._hi - this._lo || 1) *
        (this._h - padding.top - padding.bottom);
    }

    draw() {
      const ctx = this.ctx;
      const { padding, gridColor, axisColor, textColor } = this.options;
      ctx.clearRect(0, 0, this._w, this._h);

      const b = this._bounds();
      if (b.count === 0) return; // caller shows an empty-state overlay

      this._minT = b.minT; this._maxT = b.maxT;
      const scale = this._yScale(b.minV, b.maxV);
      this._lo = scale.lo; this._hi = scale.hi;
      const plotW = this._w - padding.left - padding.right;
      const plotH = this._h - padding.top - padding.bottom;

      ctx.font = "11px " + (this.options.mono || "monospace");

      // Horizontal grid lines + Y labels.
      ctx.textAlign = "right";
      ctx.textBaseline = "middle";
      for (let v = scale.lo; v <= scale.hi + 1e-6; v += scale.step) {
        const y = this._y(v);
        ctx.strokeStyle = gridColor;
        ctx.lineWidth = 1;
        ctx.beginPath();
        ctx.moveTo(padding.left, y);
        ctx.lineTo(padding.left + plotW, y);
        ctx.stroke();
        ctx.fillStyle = textColor;
        ctx.fillText(v.toFixed(1), padding.left - 6, y);
      }

      // X axis labels.
      const span = b.maxT - b.minT || 1;
      const n = this.options.xLabelCount;
      ctx.textAlign = "center";
      ctx.textBaseline = "top";
      for (let i = 0; i <= n; i++) {
        const t = b.minT + (span * i) / n;
        const x = this._x(t);
        ctx.fillStyle = textColor;
        ctx.fillText(this.options.xFormat(new Date(t)), x, this._h - padding.bottom + 8);
      }

      // Series lines (and optional area fill for the first series).
      for (let si = 0; si < this.series.length; si++) {
        const s = this.series[si];
        if (!s.points || s.points.length === 0) continue;
        const pts = s.points
          .map((p) => ({ t: new Date(p[0]).getTime(), v: p[1] }))
          .filter((p) => Number.isFinite(p.t) && Number.isFinite(p.v));
        if (pts.length === 0) continue;
        const color = s.color || "#9ca3af";

        if (this.options.fill && si === 0 && pts.length > 1) {
          const grad = ctx.createLinearGradient(0, padding.top, 0, padding.top + plotH);
          grad.addColorStop(0, this._withAlpha(color, 0.24));
          grad.addColorStop(1, this._withAlpha(color, 0.0));
          ctx.beginPath();
          ctx.moveTo(this._x(pts[0].t), this._h - padding.bottom);
          for (const p of pts) ctx.lineTo(this._x(p.t), this._y(p.v));
          ctx.lineTo(this._x(pts[pts.length - 1].t), this._h - padding.bottom);
          ctx.closePath();
          ctx.fillStyle = grad;
          ctx.fill();
        }

        ctx.strokeStyle = color;
        ctx.lineWidth = this.options.lineWidth;
        ctx.lineJoin = "round";
        ctx.lineCap = "round";
        ctx.beginPath();
        pts.forEach((p, idx) => {
          const x = this._x(p.t), y = this._y(p.v);
          idx === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y);
        });
        ctx.stroke();
      }

      // Legend.
      let lx = padding.left + 6;
      const ly = 12;
      ctx.textBaseline = "middle";
      ctx.textAlign = "left";
      ctx.font = "12px " + (this.options.mono || "monospace");
      for (const s of this.series) {
        const w = ctx.measureText(s.label || s.phase).width;
        ctx.fillStyle = s.color || "#9ca3af";
        ctx.fillRect(lx, ly - 4, 12, 3);
        ctx.fillStyle = textColor;
        ctx.fillText(s.label || s.phase, lx + 16, ly);
        lx += 16 + w + 14;
      }

      this._drawTooltip();
    }

    _roundedRect(x, y, w, h, r) {
      const ctx = this.ctx;
      ctx.moveTo(x + r, y);
      ctx.lineTo(x + w - r, y);
      ctx.quadraticCurveTo(x + w, y, x + w, y + r);
      ctx.lineTo(x + w, y + h - r);
      ctx.quadraticCurveTo(x + w, y + h, x + w - r, y + h);
      ctx.lineTo(x + r, y + h);
      ctx.quadraticCurveTo(x, y + h, x, y + h - r);
      ctx.lineTo(x, y + r);
      ctx.quadraticCurveTo(x, y, x + r, y);
      ctx.closePath();
    }

    _withAlpha(hex, alpha) {
      const h = hex.replace("#", "");
      const r = parseInt(h.substring(0, 2), 16);
      const g = parseInt(h.substring(2, 4), 16);
      const b = parseInt(h.substring(4, 6), 16);
      return "rgba(" + r + "," + g + "," + b + "," + alpha + ")";
    }

    _drawTooltip() {
      if (!this.hover || this.series.length === 0) return;
      const ctx = this.ctx;
      const { padding, textColor } = this.options;
      const mouseTime = this._minT +
        ((this.hover.x - padding.left) /
          (this._w - padding.left - padding.right)) * (this._maxT - this._minT);

      // Find the nearest point in each series to the hovered time.
      const rows = [];
      for (const s of this.series) {
        let best = null, bestDist = Infinity;
        for (const p of s.points) {
          const t = new Date(p[0]).getTime();
          const d = Math.abs(t - mouseTime);
          if (d < bestDist) { bestDist = d; best = p; }
        }
        if (best) rows.push({ label: s.label || s.phase, color: s.color, value: best[1] });
      }
      if (rows.length === 0) return;

      const lineH = 18;
      const boxW = 130;
      const boxH = rows.length * lineH + 18;
      let bx = this.hover.x + 14;
      let by = this.hover.y - boxH / 2;
      bx = Math.min(bx, this._w - boxW - 8);
      by = Math.max(8, Math.min(by, this._h - boxH - 8));

      ctx.fillStyle = "rgba(13,17,23,0.92)";
      ctx.strokeStyle = "rgba(255,255,255,0.12)";
      ctx.beginPath();
      this._roundedRect(bx, by, boxW, boxH, 8);
      ctx.fill();
      ctx.stroke();

      ctx.textAlign = "left";
      ctx.textBaseline = "middle";
      ctx.font = "11px " + (this.options.mono || "monospace");
      ctx.fillStyle = textColor;
      ctx.fillText(this.options.xFormat(new Date(mouseTime)), bx + 10, by + 12);
      rows.forEach((row, i) => {
        const ry = by + 30 + i * lineH;
        ctx.fillStyle = row.color;
        ctx.fillRect(bx + 10, ry - 3, 8, 8);
        ctx.fillStyle = textColor;
        ctx.fillText(row.label, bx + 24, ry);
        ctx.fillText(row.value.toFixed(2) + " " + this.options.yUnit, bx + 62, ry);
      });
    }
  }

  window.LineChart = LineChart;
})();
