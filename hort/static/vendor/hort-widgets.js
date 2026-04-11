/**
 * hort-widgets.js — Shared UI components for openhort plugins.
 *
 * Provides responsive, theme-aware widget components that any plugin
 * can use in its templates. All components use CSS custom properties
 * (--el-*) and work in both dark and light modes.
 *
 * Components:
 *   <hort-stat-card>    — Single number with label, trend, icon
 *   <hort-chart>        — Plotly.js wrapper with reactive data
 *   <hort-status-badge> — Colored status indicator
 *   <hort-data-table>   — Responsive data table
 *   <hort-widget-grid>  — Responsive 12-column grid layout
 *   <hort-file-upload>  — File upload to plugin store
 *
 * Usage in plugin templates:
 *   <hort-stat-card label="CPU" value="42" unit="°C" icon="ph ph-thermometer" />
 *
 * Loaded after hort-ext.js. Registers components via
 * LlmingClient._registerWidgetComponents(app).
 */

/* global Vue, LlmingClient */

(function (root) {
  'use strict';

  // ---- hort-stat-card ----

  const StatCard = {
    props: {
      label: { type: String, default: '' },
      value: { type: [String, Number], default: '--' },
      unit: { type: String, default: '' },
      trend: { type: String, default: '' }, // 'up', 'down', 'flat', ''
      icon: { type: String, default: '' },
      color: { type: String, default: 'var(--el-primary)' },
    },
    template: `
      <div class="hort-stat-card" :style="{'--card-color': color}">
        <div class="hort-stat-card__header">
          <i v-if="icon" :class="icon" class="hort-stat-card__icon"></i>
          <span class="hort-stat-card__label">{{ label }}</span>
          <span v-if="trend" class="hort-stat-card__trend" :class="'trend-' + trend">
            <i :class="trend === 'up' ? 'ph ph-trend-up' : trend === 'down' ? 'ph ph-trend-down' : 'ph ph-minus'"></i>
          </span>
        </div>
        <div class="hort-stat-card__value">
          <span class="hort-stat-card__number">{{ value }}</span>
          <span v-if="unit" class="hort-stat-card__unit">{{ unit }}</span>
        </div>
      </div>
    `,
  };

  // ---- hort-chart ----

  const Chart = {
    props: {
      type: { type: String, default: 'line' },
      data: { type: Array, default: () => [] },
      layout: { type: Object, default: () => ({}) },
      config: { type: Object, default: () => ({ responsive: true, displayModeBar: false }) },
    },
    setup(props) {
      const chartRef = Vue.ref(null);
      const plotted = Vue.ref(false);

      function render() {
        if (!chartRef.value || typeof Plotly === 'undefined') return;
        const defaultLayout = {
          paper_bgcolor: 'transparent',
          plot_bgcolor: 'transparent',
          font: { color: 'var(--el-text-dim)', size: 11 },
          margin: { l: 40, r: 10, t: 30, b: 30 },
          height: 200,
        };
        const merged = { ...defaultLayout, ...props.layout };
        if (plotted.value) {
          Plotly.react(chartRef.value, props.data, merged, props.config);
        } else {
          Plotly.newPlot(chartRef.value, props.data, merged, props.config);
          plotted.value = true;
        }
      }

      Vue.watch(() => [props.data, props.layout], render, { deep: true });
      Vue.onMounted(() => { setTimeout(render, 100); });

      return { chartRef };
    },
    template: `<div ref="chartRef" class="hort-chart"></div>`,
  };

  // ---- hort-status-badge ----

  const StatusBadge = {
    props: {
      status: { type: String, default: 'ok' }, // 'ok', 'warn', 'error', 'offline'
      label: { type: String, default: '' },
    },
    computed: {
      statusColor() {
        const colors = {
          ok: 'var(--el-success)',
          warn: 'var(--el-warning)',
          error: 'var(--el-danger)',
          offline: 'var(--el-text-dim)',
        };
        return colors[this.status] || colors.offline;
      },
    },
    template: `
      <span class="hort-status-badge">
        <span class="hort-status-badge__dot" :style="{background: statusColor}"></span>
        <span v-if="label" class="hort-status-badge__label">{{ label }}</span>
      </span>
    `,
  };

  // ---- hort-data-table ----

  const DataTable = {
    props: {
      columns: { type: Array, default: () => [] }, // [{name, label, field?}]
      rows: { type: Array, default: () => [] },
      dense: { type: Boolean, default: false },
    },
    template: `
      <div class="hort-data-table" :class="{'hort-data-table--dense': dense}">
        <table>
          <thead>
            <tr><th v-for="col in columns" :key="col.name">{{ col.label || col.name }}</th></tr>
          </thead>
          <tbody>
            <tr v-for="(row, i) in rows" :key="i">
              <td v-for="col in columns" :key="col.name">{{ row[col.field || col.name] }}</td>
            </tr>
          </tbody>
        </table>
      </div>
    `,
  };

  // ---- hort-widget-grid ----

  const WidgetGrid = {
    props: {
      widgets: { type: Array, default: () => [] },
      // Each widget: {component: 'name', props: {...}, sizes: {phone: 12, tablet: 6, pc: 4}}
    },
    setup(props) {
      const screenWidth = Vue.ref(window.innerWidth);
      const onResize = () => { screenWidth.value = window.innerWidth; };
      Vue.onMounted(() => window.addEventListener('resize', onResize));
      Vue.onUnmounted(() => window.removeEventListener('resize', onResize));

      function getCols(widget) {
        const s = widget.sizes || {};
        const w = screenWidth.value;
        if (w < 480) return s.phone || 12;
        if (w < 1024) return s.tablet || 6;
        return s.pc || 4;
      }

      return { getCols };
    },
    template: `
      <div class="hort-widget-grid">
        <div v-for="(w, i) in widgets" :key="i"
             class="hort-widget-grid__cell"
             :style="{gridColumn: 'span ' + getCols(w)}">
          <component :is="w.component" v-bind="w.props || {}" />
        </div>
      </div>
    `,
  };

  // ---- hort-file-upload ----

  const FileUpload = {
    props: {
      accept: { type: String, default: '*/*' },
      maxSize: { type: Number, default: 10 * 1024 * 1024 }, // 10MB
      label: { type: String, default: 'Upload File' },
    },
    emits: ['upload'],
    setup(props, { emit }) {
      const inputRef = Vue.ref(null);
      const dragging = Vue.ref(false);

      function handleFile(file) {
        if (file.size > props.maxSize) {
          Quasar.Dialog.create({
            title: 'File Too Large',
            message: `File exceeds the maximum size of ${Math.round(props.maxSize / 1024 / 1024)} MB.`,
            dark: true,
            ok: { label: 'OK' },
          });
          return;
        }
        const reader = new FileReader();
        reader.onload = () => {
          emit('upload', {
            name: file.name,
            mime_type: file.type,
            data: new Uint8Array(reader.result),
            size: file.size,
          });
        };
        reader.readAsArrayBuffer(file);
      }

      function onChange(e) { if (e.target.files[0]) handleFile(e.target.files[0]); }
      function onDrop(e) {
        dragging.value = false;
        if (e.dataTransfer.files[0]) handleFile(e.dataTransfer.files[0]);
      }

      return { inputRef, dragging, onChange, onDrop };
    },
    template: `
      <div class="hort-file-upload"
           :class="{'hort-file-upload--drag': dragging}"
           @dragover.prevent="dragging = true"
           @dragleave="dragging = false"
           @drop.prevent="onDrop">
        <i class="ph ph-upload-simple"></i>
        <span>{{ label }}</span>
        <input ref="inputRef" type="file" :accept="accept" @change="onChange"
               style="position:absolute;inset:0;opacity:0;cursor:pointer">
      </div>
    `,
  };

  // ---- CSS ----

  const WIDGET_CSS = `
    .hort-stat-card {
      background: var(--el-surface);
      border: 1px solid var(--el-border);
      border-radius: var(--el-widget-radius, 10px);
      padding: var(--el-widget-padding, 16px);
    }
    .hort-stat-card__header {
      display: flex;
      align-items: center;
      gap: 6px;
      margin-bottom: 8px;
    }
    .hort-stat-card__icon {
      font-size: 18px;
      color: var(--card-color);
    }
    .hort-stat-card__label {
      font-size: 12px;
      color: var(--el-text-dim);
      flex: 1;
    }
    .hort-stat-card__trend { font-size: 14px; }
    .hort-stat-card__trend.trend-up { color: var(--el-success); }
    .hort-stat-card__trend.trend-down { color: var(--el-danger); }
    .hort-stat-card__trend.trend-flat { color: var(--el-text-dim); }
    .hort-stat-card__value {
      display: flex;
      align-items: baseline;
      gap: 4px;
    }
    .hort-stat-card__number {
      font-size: 28px;
      font-weight: 700;
      color: var(--el-text);
      line-height: 1;
    }
    .hort-stat-card__unit {
      font-size: 14px;
      color: var(--el-text-dim);
    }

    .hort-status-badge {
      display: inline-flex;
      align-items: center;
      gap: 6px;
    }
    .hort-status-badge__dot {
      width: 8px;
      height: 8px;
      border-radius: 50%;
      display: inline-block;
    }
    .hort-status-badge__label {
      font-size: 12px;
      color: var(--el-text-dim);
    }

    .hort-data-table {
      overflow-x: auto;
    }
    .hort-data-table table {
      width: 100%;
      border-collapse: collapse;
      font-size: 13px;
    }
    .hort-data-table th {
      text-align: left;
      padding: 8px 12px;
      color: var(--el-text-dim);
      font-weight: 600;
      font-size: 11px;
      text-transform: uppercase;
      letter-spacing: 0.5px;
      border-bottom: 1px solid var(--el-border);
    }
    .hort-data-table td {
      padding: 8px 12px;
      color: var(--el-text);
      border-bottom: 1px solid var(--el-border);
    }
    .hort-data-table--dense th,
    .hort-data-table--dense td { padding: 4px 8px; }

    .hort-widget-grid {
      display: grid;
      grid-template-columns: repeat(12, 1fr);
      gap: 12px;
    }
    .hort-widget-grid__cell {
      min-width: 0;
    }

    .hort-chart {
      width: 100%;
      min-height: 150px;
    }

    .hort-file-upload {
      position: relative;
      display: flex;
      align-items: center;
      justify-content: center;
      gap: 8px;
      padding: 16px;
      border: 2px dashed var(--el-border);
      border-radius: var(--el-widget-radius, 10px);
      color: var(--el-text-dim);
      font-size: 13px;
      cursor: pointer;
      transition: border-color 0.15s, background 0.15s;
    }
    .hort-file-upload:hover,
    .hort-file-upload--drag {
      border-color: var(--el-primary);
      background: rgba(59, 130, 246, 0.05);
    }
  `;

  // ---- Registration ----

  LlmingClient._registerWidgetComponents = function (app) {
    app.component('hort-stat-card', StatCard);
    app.component('hort-chart', Chart);
    app.component('hort-status-badge', StatusBadge);
    app.component('hort-data-table', DataTable);
    app.component('hort-widget-grid', WidgetGrid);
    app.component('hort-file-upload', FileUpload);

    // Inject widget CSS
    if (!document.getElementById('hort-widget-css')) {
      const style = document.createElement('style');
      style.id = 'hort-widget-css';
      style.textContent = WIDGET_CSS;
      document.head.appendChild(style);
    }
  };

  // Patch activateAll to also register widget components
  const _origActivateAll = LlmingClient.activateAll;
  LlmingClient.activateAll = function (app, Quasar, configs) {
    // Shared components (hort-qr) registered by hort-ext.js
    // Widget components registered here
    LlmingClient._registerWidgetComponents(app);
    _origActivateAll.call(this, app, Quasar, configs);
  };

})(typeof globalThis !== 'undefined' ? globalThis : window);
