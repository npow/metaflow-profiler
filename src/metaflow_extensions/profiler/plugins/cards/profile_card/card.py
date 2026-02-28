"""ProfileCard — interactive flamegraph + resource timeline.

Layer: Card (visualization)
May only import from: standard library, metaflow.cards

The card is entirely self-contained HTML/CSS/JS — no CDN, no external deps.
The flamegraph renderer is a bespoke Canvas-based implementation that
supports click-to-zoom, search highlighting, and hover tooltips.
"""

from __future__ import annotations

import json
from typing import Any

from metaflow.cards import MetaflowCard


class ProfileCard(MetaflowCard):
    """Render an interactive profiling card from ``_profile_card_data`` artifact."""

    type = "profile_card"
    ALLOW_USER_COMPONENTS = False
    RUNTIME_UPDATABLE = False

    def __init__(self, options: dict[str, Any] | None = None, **kwargs: Any) -> None:
        if options is None:
            options = {}
        super().__init__(**kwargs)
        self._artifact_name = options.get("artifact_name", "profile_card_data")

    # ── render ────────────────────────────────────────────────────────────────

    def render(self, task: Any) -> str:
        raw = getattr(task.data, self._artifact_name, None)
        if raw is None:
            return _error_html("No profiling data found on this task.", detail=(
                f"Expected artifact <code>{self._artifact_name}</code>. "
                "Make sure <code>@profile_card</code> is applied to this step "
                "and the artifact name does not start with an underscore."
            ))

        if "error" in raw:
            err = raw["error"]
            return _error_html(
                f"Profiler error: {err.get('type', 'Error')}",
                detail=err.get("message", ""),
                traceback=err.get("traceback"),
            )

        data: dict[str, Any] = raw.get("data", {})
        step_failed: bool = raw.get("step_failed", False)
        return _render_card(data, step_failed, task)


# ── HTML helpers ──────────────────────────────────────────────────────────────

def _error_html(title: str, detail: str = "", traceback: str | None = None) -> str:
    tb_section = ""
    if traceback:
        tb_section = f"""
        <details style="margin-top:12px">
          <summary style="cursor:pointer;color:var(--accent)">Traceback</summary>
          <pre style="margin-top:8px;padding:12px;background:var(--surface1);
                      border-radius:6px;font-size:12px;overflow:auto;
                      white-space:pre-wrap">{traceback}</pre>
        </details>"""
    return f"""<!DOCTYPE html><html><head><meta charset="utf-8">
<style>
  :root{{--bg:#1e1e2e;--surface0:#181825;--surface1:#313244;
        --text:#cdd6f4;--subtext:#a6adc8;--red:#f38ba8;--accent:#89b4fa}}
  body{{background:var(--bg);color:var(--text);font-family:ui-monospace,monospace;
        display:flex;align-items:center;justify-content:center;min-height:100vh;margin:0}}
  .box{{background:var(--surface0);border:1px solid var(--red);border-radius:10px;
        padding:32px;max-width:640px;width:90%}}
  h2{{color:var(--red);margin:0 0 8px}}
  p{{color:var(--subtext);margin:4px 0;font-size:14px}}
</style></head><body>
<div class="box">
  <h2>&#9888; {title}</h2>
  <p>{detail}</p>
  {tb_section}
</div>
</body></html>"""


def _fmt_duration(s: float) -> str:
    ms = s * 1000.0
    if ms < 1:
        return f"{ms:.3f} ms"
    if ms < 1000:
        return f"{ms:.0f} ms"
    if s < 60:
        return f"{s:.2f} s"
    m, sec = divmod(s, 60)
    return f"{int(m)}m {sec:.1f}s"


def _fmt_mb(mb: float) -> str:
    if mb >= 1024:
        return f"{mb / 1024:.2f} GB"
    return f"{mb:.1f} MB"


def _stat_card(value: str, label: str, css_class: str = "") -> str:
    cls = f' class="stat-card{" " + css_class if css_class else ""}"'
    return f"""
    <div{cls}>
      <div class="stat-value">{value}</div>
      <div class="stat-label">{label}</div>
    </div>"""


def _render_card(data: dict[str, Any], step_failed: bool, task: Any) -> str:
    backend = data.get("backend", "unknown")
    duration = data.get("duration", 0.0)
    sample_count = data.get("sample_count", 0)
    call_tree = data.get("call_tree")
    memory_tree = data.get("memory_tree")
    timeline: list[dict[str, Any]] = data.get("timeline", [])
    peak_cpu = data.get("peak_cpu_pct", 0.0)
    peak_mem = data.get("peak_rss_mb", 0.0)
    avg_cpu = data.get("avg_cpu_pct", 0.0)
    avg_mem = data.get("avg_rss_mb", 0.0)
    peak_disk_read = data.get("peak_disk_read_mb_s", 0.0)
    peak_disk_write = data.get("peak_disk_write_mb_s", 0.0)
    peak_net_recv = data.get("peak_net_recv_mb_s", 0.0)
    peak_net_sent = data.get("peak_net_sent_mb_s", 0.0)
    peak_gpu_pct = data.get("peak_gpu_pct", 0.0)
    peak_gpu_mem = data.get("peak_gpu_mem_mb", 0.0)

    # Step metadata from the task
    try:
        step_name = task.id.rsplit("/", 2)[-2]
    except Exception:
        step_name = ""

    failed_banner = ""
    if step_failed:
        failed_banner = """
        <div class="failed-banner">
          &#9888; Step failed — profiling data captured up to the point of failure
        </div>"""

    # ── Stats grid ────────────────────────────────────────────────────────────
    # Base stats — always shown
    stats_html = (
        _stat_card(_fmt_duration(duration), "Duration")
        + _stat_card(f"{sample_count:,}", "Samples")
        + _stat_card(f"{peak_cpu:.1f}%", "Peak CPU", "cpu")
        + _stat_card(_fmt_mb(peak_mem), "Peak Memory", "mem")
        + _stat_card(f"{avg_cpu:.1f}%", "Avg CPU")
        + _stat_card(_fmt_mb(avg_mem), "Avg Memory")
    )
    # Extended stats — only when non-zero
    if peak_disk_read > 0:
        stats_html += _stat_card(f"{peak_disk_read:.2f} MB/s", "Peak Disk Read", "disk")
    if peak_disk_write > 0:
        stats_html += _stat_card(f"{peak_disk_write:.2f} MB/s", "Peak Disk Write", "disk")
    if peak_net_recv > 0:
        stats_html += _stat_card(f"{peak_net_recv:.2f} MB/s", "Peak Net Recv", "net")
    if peak_net_sent > 0:
        stats_html += _stat_card(f"{peak_net_sent:.2f} MB/s", "Peak Net Sent", "net")
    if peak_gpu_pct > 0:
        stats_html += _stat_card(f"{peak_gpu_pct:.1f}%", "Peak GPU", "gpu")
    if peak_gpu_mem > 0:
        stats_html += _stat_card(_fmt_mb(peak_gpu_mem), "Peak GPU Mem", "gpu")

    # ── JS data ───────────────────────────────────────────────────────────────
    js_data = json.dumps(
        {
            "call_tree": call_tree,
            "memory_tree": memory_tree,
            "timeline": timeline,
            "backend": backend,
            "duration": duration,
            "sample_count": sample_count,
            "peak_cpu_pct": peak_cpu,
            "peak_rss_mb": peak_mem,
            "peak_disk_read_mb_s": peak_disk_read,
            "peak_disk_write_mb_s": peak_disk_write,
            "peak_net_recv_mb_s": peak_net_recv,
            "peak_net_sent_mb_s": peak_net_sent,
            "peak_gpu_pct": peak_gpu_pct,
            "peak_gpu_mem_mb": peak_gpu_mem,
        },
        separators=(",", ":"),
    )

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Profile — {step_name}</title>
<style>
{_CSS}
</style>
</head>
<body>
<div class="card">
  <div class="card-header">
    <div>
      <h1 class="title">Step Profile
        {f'<span class="step-name">{step_name}</span>' if step_name else ''}
      </h1>
      <div class="subtitle">
        Backend: <span class="badge">{backend}</span>
        &nbsp;·&nbsp; Duration: <strong>{_fmt_duration(duration)}</strong>
        &nbsp;·&nbsp; {sample_count:,} samples
      </div>
    </div>
  </div>

  {failed_banner}

  <div class="stats-grid">
    {stats_html}
  </div>

  <div class="section" id="flamegraph-section">
    <div class="section-header">
      <h2 class="section-title">CPU Flamegraph</h2>
      <div class="fg-controls">
        <input type="search" id="fg-search" class="search-input"
               placeholder="Search functions…" autocomplete="off">
        <button id="fg-reset" class="btn btn-secondary">Reset zoom</button>
      </div>
    </div>
    <div id="fg-breadcrumb" class="breadcrumb" style="display:none"></div>
    <div id="fg-container" class="fg-container">
      <canvas id="fg-canvas"></canvas>
    </div>
    <div id="fg-tooltip" class="tooltip" style="display:none"></div>
    <div id="fg-no-data" class="no-data" style="display:none">
      No call-tree data available for this backend.
    </div>
  </div>

  <div class="section" id="mem-flame-section" style="display:none">
    <div class="section-header">
      <h2 class="section-title">Memory Flamegraph <span class="section-subtitle">(MB)</span></h2>
      <div class="fg-controls">
        <input type="search" id="mem-search" class="search-input"
               placeholder="Search functions…" autocomplete="off">
        <button id="mem-reset" class="btn btn-secondary">Reset zoom</button>
      </div>
    </div>
    <div id="mem-breadcrumb" class="breadcrumb" style="display:none"></div>
    <div id="mem-container" class="fg-container">
      <canvas id="mem-canvas"></canvas>
    </div>
    <div id="mem-tooltip" class="tooltip" style="display:none"></div>
  </div>

  <div class="section" id="timeline-section">
    <div class="section-header">
      <h2 class="section-title">Resource Timeline</h2>
    </div>
    <div id="timeline-container" class="timeline-container">
      <canvas id="timeline-canvas"></canvas>
    </div>
    <div id="timeline-legend" class="timeline-legend">
      <span class="legend-cpu">&#9632; CPU %</span>
      <span class="legend-mem">&#9632; Memory (MB)</span>
    </div>
    <div id="timeline-no-data" class="no-data" style="display:none">
      No timeline data available (psutil not installed or step too fast).
    </div>
  </div>

  <div class="section" id="io-section" style="display:none">
    <div class="section-header">
      <h2 class="section-title">I/O Timeline</h2>
    </div>
    <div class="timeline-container">
      <canvas id="io-canvas"></canvas>
    </div>
    <div id="io-legend" class="timeline-legend">
      <span style="color:#f0a060">&#9632; Disk Read MB/s</span>
      <span style="color:#e06060">&#9632; Disk Write MB/s</span>
      <span style="color:#60c0e0">&#9632; Net Recv MB/s</span>
      <span style="color:#8060e0">&#9632; Net Sent MB/s</span>
    </div>
  </div>

  <div class="section" id="gpu-section" style="display:none">
    <div class="section-header">
      <h2 class="section-title">GPU Timeline</h2>
    </div>
    <div class="timeline-container">
      <canvas id="gpu-canvas"></canvas>
    </div>
    <div id="gpu-legend" class="timeline-legend">
      <span style="color:#b060e0">&#9632; GPU %</span>
      <span style="color:#60e080">&#9632; GPU Memory (MB)</span>
    </div>
  </div>
</div>

<script>
const PROFILE_DATA = {js_data};
{_JS}
</script>
</body>
</html>"""


# ── CSS ───────────────────────────────────────────────────────────────────────

_CSS = """
/* ── Design tokens ──────────────────────────────────────────────────────── */
:root {
  --bg:       #0f0f17;
  --surface0: #1a1a2e;
  --surface1: #252538;
  --surface2: #2e2e48;
  --border:   #3a3a5c;
  --text:     #e2e2f0;
  --subtext:  #9090b0;
  --accent:   #7b8ef8;
  --hot:      #ff6b6b;
  --warm:     #ffa94d;
  --cool:     #63e6be;
  --cpu-col:  #7b8ef8;
  --mem-col:  #63e6be;
  --radius:   8px;
}
@media (prefers-color-scheme: light) {
  :root {
    --bg:       #f5f5fa;
    --surface0: #ffffff;
    --surface1: #ebebf5;
    --surface2: #e0e0f0;
    --border:   #c8c8e0;
    --text:     #1a1a2e;
    --subtext:  #6060a0;
  }
}

/* ── Reset ──────────────────────────────────────────────────────────────── */
*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
html { font-size: 14px; }
body {
  background: var(--bg);
  color: var(--text);
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto,
               "Inter", ui-sans-serif, sans-serif;
  line-height: 1.5;
}

/* ── Card layout ────────────────────────────────────────────────────────── */
.card {
  max-width: 1200px;
  margin: 0 auto;
  padding: 24px 20px;
}
.card-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  margin-bottom: 20px;
  gap: 12px;
}
.title {
  font-size: 1.5rem;
  font-weight: 700;
  color: var(--text);
  line-height: 1.2;
}
.step-name {
  font-size: 1.1rem;
  font-weight: 400;
  color: var(--accent);
  margin-left: 8px;
}
.subtitle {
  font-size: 0.85rem;
  color: var(--subtext);
  margin-top: 4px;
}
.badge {
  background: var(--surface2);
  border: 1px solid var(--border);
  border-radius: 4px;
  padding: 1px 6px;
  font-family: ui-monospace, "Fira Code", monospace;
  font-size: 0.8rem;
}

/* ── Failed banner ──────────────────────────────────────────────────────── */
.failed-banner {
  background: rgba(255, 107, 107, 0.15);
  border: 1px solid var(--hot);
  border-radius: var(--radius);
  padding: 10px 16px;
  margin-bottom: 20px;
  font-size: 0.875rem;
  color: var(--hot);
}

/* ── Stats grid ─────────────────────────────────────────────────────────── */
.stats-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
  gap: 12px;
  margin-bottom: 24px;
}
.stat-card {
  background: var(--surface0);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 14px 18px;
  text-align: center;
}
.stat-card.cpu  { border-top: 3px solid var(--cpu-col); }
.stat-card.mem  { border-top: 3px solid var(--mem-col); }
.stat-card.disk { border-top: 3px solid #f0a060; }
.stat-card.net  { border-top: 3px solid #60c0e0; }
.stat-card.gpu  { border-top: 3px solid #b060e0; }
.stat-value {
  font-size: 1.4rem;
  font-weight: 700;
  font-family: ui-monospace, "Fira Code", monospace;
  color: var(--text);
  letter-spacing: -0.02em;
}
.stat-label {
  font-size: 0.75rem;
  color: var(--subtext);
  text-transform: uppercase;
  letter-spacing: 0.06em;
  margin-top: 2px;
}

/* ── Section ────────────────────────────────────────────────────────────── */
.section {
  background: var(--surface0);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  margin-bottom: 20px;
  overflow: hidden;
}
.section-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 14px 16px;
  border-bottom: 1px solid var(--border);
  gap: 12px;
  flex-wrap: wrap;
}
.section-title {
  font-size: 1rem;
  font-weight: 600;
}
.section-subtitle {
  font-size: 0.8rem;
  font-weight: 400;
  color: var(--subtext);
  margin-left: 4px;
}

/* ── Flamegraph controls ─────────────────────────────────────────────────── */
.fg-controls {
  display: flex;
  gap: 8px;
  align-items: center;
  flex-wrap: wrap;
}
.search-input {
  background: var(--surface1);
  border: 1px solid var(--border);
  border-radius: 6px;
  color: var(--text);
  padding: 5px 10px;
  font-size: 0.85rem;
  width: 220px;
  outline: none;
  transition: border-color 0.15s;
}
.search-input:focus { border-color: var(--accent); }
.btn {
  padding: 5px 12px;
  border-radius: 6px;
  font-size: 0.85rem;
  cursor: pointer;
  border: 1px solid var(--border);
  transition: background 0.15s, border-color 0.15s;
  white-space: nowrap;
}
.btn-secondary {
  background: var(--surface1);
  color: var(--subtext);
}
.btn-secondary:hover { background: var(--surface2); color: var(--text); }

/* ── Breadcrumb ─────────────────────────────────────────────────────────── */
.breadcrumb {
  padding: 6px 16px;
  font-size: 0.8rem;
  color: var(--subtext);
  border-bottom: 1px solid var(--border);
  background: var(--surface1);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.breadcrumb .crumb { color: var(--accent); cursor: pointer; }
.breadcrumb .crumb:hover { text-decoration: underline; }
.breadcrumb .sep { margin: 0 4px; opacity: 0.5; }

/* ── Canvas containers ──────────────────────────────────────────────────── */
.fg-container {
  position: relative;
  padding: 0;
  overflow: hidden;
}
#fg-canvas, #mem-canvas {
  display: block;
  width: 100%;
  cursor: crosshair;
}

/* ── Tooltip ────────────────────────────────────────────────────────────── */
.tooltip {
  position: fixed;
  background: var(--surface0);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 10px 14px;
  font-size: 0.82rem;
  pointer-events: none;
  z-index: 9999;
  max-width: 380px;
  box-shadow: 0 8px 24px rgba(0,0,0,0.4);
  line-height: 1.6;
}
.tooltip-name {
  font-weight: 600;
  color: var(--text);
  font-family: ui-monospace, "Fira Code", monospace;
  word-break: break-all;
  margin-bottom: 4px;
}
.tooltip-row { color: var(--subtext); }
.tooltip-row strong { color: var(--text); }

/* ── Timeline ───────────────────────────────────────────────────────────── */
.timeline-container { padding: 0; }
#timeline-canvas, #io-canvas, #gpu-canvas { display: block; width: 100%; }
.timeline-legend {
  display: flex;
  gap: 20px;
  padding: 8px 16px 12px;
  font-size: 0.8rem;
  color: var(--subtext);
  flex-wrap: wrap;
}
.legend-cpu  { color: var(--cpu-col); }
.legend-mem  { color: var(--mem-col); }

/* ── No-data state ──────────────────────────────────────────────────────── */
.no-data {
  padding: 40px;
  text-align: center;
  color: var(--subtext);
  font-size: 0.9rem;
}
"""


# ── JavaScript ────────────────────────────────────────────────────────────────

_JS = r"""
(function () {
"use strict";

// ── Utility ──────────────────────────────────────────────────────────────────

function fmt(ms) {
  if (ms >= 1000) return (ms / 1000).toFixed(2) + " s";
  if (ms >= 1)    return ms.toFixed(1) + " ms";
  return ms.toFixed(3) + " ms";
}

function fmtMb(mb) {
  if (mb >= 1024) return (mb / 1024).toFixed(2) + " GB";
  return mb.toFixed(2) + " MB";
}

// Deterministic colour from a string
function strColor(s) {
  const lc = s.toLowerCase();
  if (lc.includes("<module>") || lc.includes("<built-in>") || lc.includes("cpython"))
    return "#6c6c8a";
  if (lc.includes("metaflow"))       return "#7b8ef8";
  if (lc.includes("numpy") || lc.includes("torch") || lc.includes("tensorflow") ||
      lc.includes("sklearn") || lc.includes("scipy") || lc.includes("pandas"))
    return "#63e6be";
  if (lc.includes("<ipython>") || lc.includes("flow.py") || lc.includes("run.py"))
    return "#ffa94d";
  if (lc.startsWith("<"))
    return "#555577";
  const mod = s.split("(")[0].trim().split(".")[0];
  let h = 0;
  for (let i = 0; i < mod.length; i++) h = mod.charCodeAt(i) + ((h << 5) - h) | 0;
  const hue = Math.abs(h) % 360;
  return `hsl(${hue},55%,58%)`;
}

function _esc(s) {
  return String(s).replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;").replace(/"/g,"&quot;");  # noqa: E501
}

// ── Flamegraph renderer ───────────────────────────────────────────────────────
//
// opts: { valueLabel: string, valueFmt: function }
//   valueLabel  — shown in tooltip (default "Time")
//   valueFmt    — formats the node value for tooltip (default fmt)

class FlameGraph {
  constructor(canvasEl, tooltipEl, breadcrumbEl, resetBtn, searchInput, opts) {
    this.canvas = canvasEl;
    this.ctx = canvasEl.getContext("2d");
    this.tooltip = tooltipEl;
    this.breadcrumb = breadcrumbEl;
    this.resetBtn = resetBtn;
    this.searchInput = searchInput;
    this._opts = Object.assign({ valueLabel: "Time", valueFmt: fmt }, opts || {});

    this.root = null;
    this.zoomStack = [];
    this.currentRoot = null;
    this.searchQuery = "";
    this.ROW_H = 20;
    this.rects = [];

    this._dpr = window.devicePixelRatio || 1;
    this._bindEvents();
  }

  load(root) {
    this.root = root;
    this.currentRoot = root;
    this.zoomStack = [];
    this._resize();
    this._render();
  }

  _resize() {
    const w = this.canvas.parentElement.clientWidth || 900;
    const depth = this._maxDepth(this.currentRoot, 0);
    const h = Math.max(200, (depth + 1) * this.ROW_H + 4);
    this.canvas.style.height = h + "px";
    this.canvas.width  = Math.round(w * this._dpr);
    this.canvas.height = Math.round(h * this._dpr);
    this.ctx.setTransform(this._dpr, 0, 0, this._dpr, 0, 0);
    this._logicalW = w;
    this._logicalH = h;
  }

  _maxDepth(node, d) {
    if (!node || !node.children || node.children.length === 0) return d;
    return Math.max(...node.children.map(c => this._maxDepth(c, d + 1)));
  }

  _render() {
    const ctx = this.ctx;
    ctx.clearRect(0, 0, this._logicalW, this._logicalH);
    this.rects = [];
    const totalVal = this.currentRoot.value;
    this._drawNode(this.currentRoot, 0, 0, this._logicalW, totalVal, ctx);
    this._updateBreadcrumb();
  }

  _drawNode(node, x, y, w, totalVal, ctx) {
    if (w < 1.5) return;

    const h = this.ROW_H - 1;
    const q = this.searchQuery;
    const isMatch = q && node.name.toLowerCase().includes(q.toLowerCase());
    const isNoMatch = q && !isMatch;

    const color = strColor(node.name);
    ctx.globalAlpha = isNoMatch ? 0.25 : 1.0;
    ctx.fillStyle = color;
    ctx.fillRect(x, y, w - 0.5, h);

    if (isMatch) {
      ctx.strokeStyle = "#fff";
      ctx.lineWidth = 1.5;
      ctx.strokeRect(x + 0.75, y + 0.75, w - 1.5, h - 1.5);
      ctx.lineWidth = 1;
    }

    if (w > 24) {
      ctx.globalAlpha = isNoMatch ? 0.3 : 1.0;
      ctx.fillStyle = "#fff";
      ctx.font = `${Math.min(11, this.ROW_H - 6)}px ui-monospace,"Fira Code",monospace`;
      ctx.textBaseline = "middle";
      const label = this._clip(node.name, w - 8, ctx);
      if (label) ctx.fillText(label, x + 4, y + h / 2);
    }

    ctx.globalAlpha = 1.0;
    this.rects.push({ x, y, w, h, node });

    if (node.children && node.children.length > 0) {
      let childX = x;
      for (const child of node.children) {
        const childW = (child.value / node.value) * w;
        this._drawNode(child, childX, y + this.ROW_H, childW, totalVal, ctx);
        childX += childW;
      }
    }
  }

  _clip(text, maxPx, ctx) {
    if (ctx.measureText(text).width <= maxPx) return text;
    let lo = 0, hi = text.length;
    while (lo < hi - 1) {
      const mid = (lo + hi) >> 1;
      if (ctx.measureText(text.slice(0, mid) + "…").width <= maxPx) lo = mid;
      else hi = mid;
    }
    return lo > 0 ? text.slice(0, lo) + "…" : null;
  }

  _hitTest(mx, my) {
    for (let i = this.rects.length - 1; i >= 0; i--) {
      const r = this.rects[i];
      if (mx >= r.x && mx <= r.x + r.w && my >= r.y && my <= r.y + r.h) {
        return r;
      }
    }
    return null;
  }

  _bindEvents() {
    const canvas = this.canvas;
    const tooltip = this.tooltip;
    const opts = this._opts;

    canvas.addEventListener("mousemove", (e) => {
      const rect = canvas.getBoundingClientRect();
      const scaleX = this._logicalW / rect.width;
      const scaleY = this._logicalH / rect.height;
      const mx = (e.clientX - rect.left) * scaleX;
      const my = (e.clientY - rect.top) * scaleY;
      const hit = this._hitTest(mx, my);
      if (hit) {
        canvas.style.cursor = "pointer";
        const node = hit.node;
        const pct = this.currentRoot.value > 0
          ? ((node.value / this.currentRoot.value) * 100).toFixed(1)
          : "0";
        tooltip.style.display = "block";
        tooltip.style.left  = (e.clientX + 14) + "px";
        tooltip.style.top   = (e.clientY - 10) + "px";
        tooltip.innerHTML =
          `<div class="tooltip-name">${_esc(node.name)}</div>` +
          `<div class="tooltip-row">${_esc(opts.valueLabel)}: <strong>${opts.valueFmt(node.value)}</strong> (${pct}% of view)</div>` +  # noqa: E501
          (node.file ? `<div class="tooltip-row">File: <strong>${_esc(node.file)}</strong>${node.line ? ':' + node.line : ''}</div>` : "");  # noqa: E501
      } else {
        canvas.style.cursor = "crosshair";
        tooltip.style.display = "none";
      }
    });

    canvas.addEventListener("mouseleave", () => {
      tooltip.style.display = "none";
    });

    canvas.addEventListener("click", (e) => {
      const rect = canvas.getBoundingClientRect();
      const scaleX = this._logicalW / rect.width;
      const scaleY = this._logicalH / rect.height;
      const mx = (e.clientX - rect.left) * scaleX;
      const my = (e.clientY - rect.top) * scaleY;
      const hit = this._hitTest(mx, my);
      if (hit && hit.node !== this.currentRoot) {
        this.zoomStack.push(this.currentRoot);
        this.currentRoot = hit.node;
        this._resize();
        this._render();
      }
    });

    this.resetBtn.addEventListener("click", () => {
      this.currentRoot = this.root;
      this.zoomStack = [];
      this._resize();
      this._render();
    });

    this.searchInput.addEventListener("input", (e) => {
      this.searchQuery = e.target.value.trim();
      this._render();
    });

    window.addEventListener("resize", () => {
      this._resize();
      this._render();
    });
  }

  _updateBreadcrumb() {
    const bc = this.breadcrumb;
    if (this.zoomStack.length === 0) {
      bc.style.display = "none";
      return;
    }
    bc.style.display = "block";
    const parts = this.zoomStack.map((n, i) => {
      const label = n.name.length > 30 ? n.name.slice(0, 30) + "…" : n.name;
      return `<span class="crumb" data-idx="${i}">${_esc(label)}</span>`;
    });
    parts.push(`<span>${_esc(this.currentRoot.name.length > 30 ? this.currentRoot.name.slice(0,30)+"…" : this.currentRoot.name)}</span>`);  # noqa: E501
    bc.innerHTML = parts.join('<span class="sep">›</span>');  # noqa: RUF001
    bc.querySelectorAll(".crumb").forEach(el => {
      el.addEventListener("click", () => {
        const idx = parseInt(el.dataset.idx, 10);
        this.currentRoot = this.zoomStack[idx];
        this.zoomStack = this.zoomStack.slice(0, idx);
        this._resize();
        this._render();
      });
    });
  }
}

// ── Timeline renderer ─────────────────────────────────────────────────────────
//
// seriesLeft  — array of {key, color, fmt?, minMax?}  drawn on left y-axis
// seriesRight — array of {key, color, fmt?}            drawn on right y-axis
//
// Each series' fmt(v) formats axis tick labels. Defaults to v.toFixed(2).
// minMax ensures the left axis max is at least this value (e.g. 100 for CPU %).
// Returns true if rendering succeeded (enough data), false otherwise.

class TimelineChart {
  constructor(canvasEl, seriesLeft, seriesRight) {
    this.canvas = canvasEl;
    this.ctx = canvasEl.getContext("2d");
    this.seriesLeft  = seriesLeft;
    this.seriesRight = seriesRight;
    this._dpr = window.devicePixelRatio || 1;
  }

  render(timeline) {
    if (!timeline || timeline.length < 2) return false;

    // Filter to points that have at least one series key
    const allKeys = [...this.seriesLeft, ...this.seriesRight].map(s => s.key);
    const pts = timeline.filter(p => allKeys.some(k => p[k] !== undefined));
    if (pts.length < 2) return false;

    const w = this.canvas.parentElement.clientWidth || 900;
    const h = 160;
    this.canvas.style.height = h + "px";
    this.canvas.width  = Math.round(w * this._dpr);
    this.canvas.height = Math.round(h * this._dpr);
    const ctx = this.ctx;
    ctx.setTransform(this._dpr, 0, 0, this._dpr, 0, 0);

    const PAD = { top: 16, right: 60, bottom: 28, left: 50 };
    const cw = w - PAD.left - PAD.right;
    const ch = h - PAD.top  - PAD.bottom;

    const isDark = window.matchMedia("(prefers-color-scheme: dark)").matches ||
                   document.documentElement.style.colorScheme === "dark";
    const gridColor  = isDark ? "rgba(255,255,255,0.07)" : "rgba(0,0,0,0.07)";
    const labelColor = isDark ? "#9090b0" : "#6060a0";
    const bgFill     = isDark ? "#1a1a2e" : "#ffffff";

    ctx.fillStyle = bgFill;
    ctx.fillRect(0, 0, w, h);

    const maxTs = Math.max(...pts.map(p => p.ts), 1);

    // Compute left/right axis maxima
    let maxLeft = 0;
    for (const s of this.seriesLeft) {
      const vals = pts.map(p => p[s.key] || 0);
      maxLeft = Math.max(maxLeft, ...vals);
    }
    if (this.seriesLeft[0] && this.seriesLeft[0].minMax) {
      maxLeft = Math.max(maxLeft, this.seriesLeft[0].minMax);
    }
    if (maxLeft === 0) maxLeft = 1;

    let maxRight = 0;
    for (const s of this.seriesRight) {
      const vals = pts.map(p => p[s.key] || 0);
      maxRight = Math.max(maxRight, ...vals);
    }
    if (maxRight === 0) maxRight = 1;

    function xOf(ts)   { return PAD.left + (ts / maxTs) * cw; }
    function yOfL(v)   { return PAD.top  + ch - (v / maxLeft)  * ch; }
    function yOfR(v)   { return PAD.top  + ch - (v / maxRight) * ch; }

    // Grid lines
    ctx.strokeStyle = gridColor;
    ctx.lineWidth = 1;
    for (let i = 0; i <= 4; i++) {
      const y = PAD.top + (i / 4) * ch;
      ctx.beginPath(); ctx.moveTo(PAD.left, y); ctx.lineTo(PAD.left + cw, y); ctx.stroke();
    }

    // Draw right series first (behind left series)
    for (const s of this.seriesRight) {
      const sp = pts.filter(p => p[s.key] !== undefined);
      if (sp.length < 2) continue;
      ctx.beginPath();
      ctx.moveTo(xOf(sp[0].ts), PAD.top + ch);
      sp.forEach(p => ctx.lineTo(xOf(p.ts), yOfR(p[s.key])));
      ctx.lineTo(xOf(sp[sp.length-1].ts), PAD.top + ch);
      ctx.closePath();
      ctx.fillStyle = s.color + "25";
      ctx.fill();

      ctx.beginPath();
      sp.forEach((p, i) =>
        i === 0 ? ctx.moveTo(xOf(p.ts), yOfR(p[s.key]))
                : ctx.lineTo(xOf(p.ts), yOfR(p[s.key])));
      ctx.strokeStyle = s.color;
      ctx.lineWidth = 1.5;
      ctx.stroke();
    }

    // Draw left series on top
    for (const s of this.seriesLeft) {
      const sp = pts.filter(p => p[s.key] !== undefined);
      if (sp.length < 2) continue;
      ctx.beginPath();
      ctx.moveTo(xOf(sp[0].ts), PAD.top + ch);
      sp.forEach(p => ctx.lineTo(xOf(p.ts), yOfL(p[s.key])));
      ctx.lineTo(xOf(sp[sp.length-1].ts), PAD.top + ch);
      ctx.closePath();
      ctx.fillStyle = s.color + "25";
      ctx.fill();

      ctx.beginPath();
      sp.forEach((p, i) =>
        i === 0 ? ctx.moveTo(xOf(p.ts), yOfL(p[s.key]))
                : ctx.lineTo(xOf(p.ts), yOfL(p[s.key])));
      ctx.strokeStyle = s.color;
      ctx.lineWidth = 1.5;
      ctx.stroke();
    }

    // Left y-axis ticks (use first left series colour + fmt)
    const fmtL = (this.seriesLeft[0] && this.seriesLeft[0].fmt) || (v => v.toFixed(1));
    const colL = (this.seriesLeft[0] && this.seriesLeft[0].color) || "#888";
    ctx.font = "10px ui-monospace,monospace";
    ctx.textBaseline = "middle";
    for (let i = 0; i <= 4; i++) {
      const v = maxLeft * (1 - i / 4);
      const y = PAD.top + (i / 4) * ch;
      ctx.textAlign = "right";
      ctx.fillStyle = colL + "cc";
      ctx.fillText(fmtL(v), PAD.left - 4, y);
    }

    // Right y-axis ticks
    const fmtR = (this.seriesRight[0] && this.seriesRight[0].fmt) || (v => v.toFixed(1));
    const colR = (this.seriesRight[0] && this.seriesRight[0].color) || "#888";
    for (let i = 0; i <= 4; i++) {
      const v = maxRight * (1 - i / 4);
      const y = PAD.top + (i / 4) * ch;
      ctx.textAlign = "left";
      ctx.fillStyle = colR + "cc";
      ctx.fillText(fmtR(v), PAD.left + cw + 4, y);
    }

    // X-axis time labels
    ctx.textAlign = "center";
    ctx.fillStyle = labelColor;
    ctx.textBaseline = "top";
    const ticks = 6;
    for (let i = 0; i <= ticks; i++) {
      const ts = (i / ticks) * maxTs;
      ctx.fillText(ts.toFixed(1) + "s", xOf(ts), PAD.top + ch + 6);
    }

    return true;
  }
}

// ── Boot ─────────────────────────────────────────────────────────────────────

(function init() {
  const data = PROFILE_DATA;

  // ── CPU Flamegraph ──────────────────────────────────────────────────────────
  const fgCanvas  = document.getElementById("fg-canvas");
  const fgTooltip = document.getElementById("fg-tooltip");
  const fgBc      = document.getElementById("fg-breadcrumb");
  const fgReset   = document.getElementById("fg-reset");
  const fgSearch  = document.getElementById("fg-search");
  const fgNoData  = document.getElementById("fg-no-data");

  if (data.call_tree) {
    const fg = new FlameGraph(fgCanvas, fgTooltip, fgBc, fgReset, fgSearch,
                               {valueLabel: "Time", valueFmt: fmt});
    fg.load(data.call_tree);
  } else {
    fgCanvas.style.display = "none";
    fgNoData.style.display = "block";
    fgReset.disabled = true;
    fgSearch.disabled = true;
  }

  // ── Memory Flamegraph ───────────────────────────────────────────────────────
  if (data.memory_tree) {
    const memSection = document.getElementById("mem-flame-section");
    memSection.style.display = "";
    const memCanvas  = document.getElementById("mem-canvas");
    const memTooltip = document.getElementById("mem-tooltip");
    const memBc      = document.getElementById("mem-breadcrumb");
    const memReset   = document.getElementById("mem-reset");
    const memSearch  = document.getElementById("mem-search");
    const memFg = new FlameGraph(memCanvas, memTooltip, memBc, memReset, memSearch,
                                  {valueLabel: "Memory", valueFmt: fmtMb});
    memFg.load(data.memory_tree);
  }

  // ── Resource Timeline (CPU + Memory) ───────────────────────────────────────
  const tlCanvas = document.getElementById("timeline-canvas");
  const tlNoData = document.getElementById("timeline-no-data");

  const tlChart = new TimelineChart(
    tlCanvas,
    [{key: "cpu_pct",  color: "#7b8ef8", fmt: v => v.toFixed(0) + "%", minMax: 100}],
    [{key: "rss_mb",   color: "#63e6be", fmt: fmtMb}]
  );
  if (!tlChart.render(data.timeline)) {
    tlCanvas.style.display = "none";
    tlNoData.style.display = "block";
    document.getElementById("timeline-legend").style.display = "none";
  }

  // ── I/O Timeline ───────────────────────────────────────────────────────────
  const hasIO = data.timeline && data.timeline.some(
    p => p.disk_read_mb_s !== undefined || p.net_recv_mb_s !== undefined
  );
  if (hasIO) {
    const ioSection = document.getElementById("io-section");
    ioSection.style.display = "";
    const ioChart = new TimelineChart(
      document.getElementById("io-canvas"),
      [
        {key: "disk_read_mb_s",  color: "#f0a060", fmt: v => v.toFixed(2) + " MB/s"},
        {key: "disk_write_mb_s", color: "#e06060", fmt: v => v.toFixed(2) + " MB/s"},
      ],
      [
        {key: "net_recv_mb_s",   color: "#60c0e0", fmt: v => v.toFixed(2) + " MB/s"},
        {key: "net_sent_mb_s",   color: "#8060e0", fmt: v => v.toFixed(2) + " MB/s"},
      ]
    );
    ioChart.render(data.timeline);
  }

  // ── GPU Timeline ───────────────────────────────────────────────────────────
  const hasGPU = data.timeline && data.timeline.some(p => p.gpu_pct !== undefined);
  if (hasGPU) {
    const gpuSection = document.getElementById("gpu-section");
    gpuSection.style.display = "";
    const gpuChart = new TimelineChart(
      document.getElementById("gpu-canvas"),
      [{key: "gpu_pct",    color: "#b060e0", fmt: v => v.toFixed(0) + "%", minMax: 100}],
      [{key: "gpu_mem_mb", color: "#60e080", fmt: fmtMb}]
    );
    gpuChart.render(data.timeline);
  }

})();

})();  // end IIFE
"""
