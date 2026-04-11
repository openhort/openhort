/* System Monitor — dashboard UI */
/* global LlmingClient, Vue, Plotly */

(function () {
  'use strict';

  class SystemMonitorPanel extends LlmingClient {
    static id = 'system-monitor';
    static name = 'System Monitor';
    static llmingTitle = 'System Monitor';
    static llmingIcon = 'ph ph-cpu';
    static llmingDescription = 'CPU, memory, and disk monitoring';
    static llmingWidgets = ['system-monitor-dashboard'];
    static autoShow = true;

    // Cached data for thumbnail
    _lastMetrics = null;
    _history = [];

    _feedStore(store) {
      if (store.latest) this._lastMetrics = store.latest;
      const h = [];
      for (const [k, v] of Object.entries(store)) {
        if (k.startsWith('history:') && v) h.push(v);
      }
      h.sort((a, b) => (a.timestamp || 0) - (b.timestamp || 0));
      this._history = h.slice(-60);
    }

    onConnect() {
      this.subscribe('system_metrics', (data) => {
        this._lastMetrics = {...this._lastMetrics, ...data};
      });
      this.vaultRead('latest').then(data => {
        if (data && data.cpu_percent !== undefined) this._lastMetrics = data;
      });
    }

    renderThumbnail(ctx, w, h) {
      const bg = '#111827', dim = '#64748b', text = '#f0f4ff', muted = '#94a3b8';
      ctx.fillStyle = bg; ctx.fillRect(0, 0, w, h);

      const m = this._lastMetrics;
      if (!m) {
        ctx.fillStyle = dim; ctx.font = '13px system-ui'; ctx.textAlign = 'center';
        ctx.fillText('Waiting for data...', w / 2, h / 2);
        return;
      }

      // Top row: big numbers for CPU, MEM, DISK
      const stats = [
        { label: 'CPU', val: Math.round(m.cpu_percent || 0), color: '#f59e0b' },
        { label: 'MEM', val: Math.round(m.mem_percent || 0), color: '#3b82f6' },
        { label: 'DISK', val: Math.round(m.disk_percent || 0), color: '#6366f1' },
      ];
      const colW = (w - 20) / 3;
      stats.forEach((s, i) => {
        const x = 10 + i * colW;
        ctx.fillStyle = s.color; ctx.globalAlpha = 0.12;
        ctx.fillRect(x, 8, colW - 4, 52);
        ctx.globalAlpha = 1;
        ctx.fillStyle = muted; ctx.font = '9px system-ui'; ctx.textAlign = 'left';
        ctx.fillText(s.label, x + 6, 22);
        ctx.fillStyle = text; ctx.font = 'bold 22px system-ui';
        ctx.fillText(s.val + '%', x + 6, 50);
      });

      // Sparkline: CPU + MEM history
      const hist = this._history;
      if (hist.length > 2) {
        const chartY = 68, chartH = h - chartY - 18;
        const chartW = w - 20;
        // Grid lines
        ctx.strokeStyle = '#1e293b'; ctx.lineWidth = 0.5;
        for (let p = 0; p <= 100; p += 25) {
          const y = chartY + chartH - (p / 100) * chartH;
          ctx.beginPath(); ctx.moveTo(10, y); ctx.lineTo(w - 10, y); ctx.stroke();
        }
        // Draw lines
        const lines = [
          { key: 'cpu_percent', color: '#f59e0b' },
          { key: 'mem_percent', color: '#3b82f6' },
        ];
        lines.forEach(line => {
          ctx.strokeStyle = line.color; ctx.lineWidth = 1.5; ctx.beginPath();
          hist.forEach((e, i) => {
            const x = 10 + (i / (hist.length - 1)) * chartW;
            const y = chartY + chartH - ((e[line.key] || 0) / 100) * chartH;
            i === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y);
          });
          ctx.stroke();
        });
        // Legend
        ctx.font = '8px system-ui'; ctx.textAlign = 'left';
        ctx.fillStyle = '#f59e0b'; ctx.fillText('CPU', 12, h - 6);
        ctx.fillStyle = '#3b82f6'; ctx.fillText('MEM', 40, h - 6);
        ctx.fillStyle = dim; ctx.fillText(hist.length + ' samples', w - 70, h - 6);
      } else {
        ctx.fillStyle = dim; ctx.font = '10px system-ui'; ctx.textAlign = 'center';
        ctx.fillText('Collecting data...', w / 2, h - 20);
      }
    }

    setup(app) {
      app.component('system-monitor-dashboard', {
        setup() {
          const bp = LlmingClient.basePath;
          const latest = Vue.ref(null);
          const history = Vue.ref([]);
          const chartRef = Vue.ref(null);

          async function fetchStatus() {
            try {
              const r = await fetch(bp + '/api/llmings/system-monitor/status');
              if (r.ok) return await r.json();
            } catch {}
            return null;
          }

          async function refresh() {
            try {
              const store = await fetchStatus();
              if (store && store.latest) {
                latest.value = store.latest;
                history.value = store.history || [];
                // Cache for thumbnail rendering
                const inst = LlmingClient.get('system-monitor');
                if (inst) {
                  inst._lastMetrics = store.latest;
                  inst._history = store.history || [];
                }
                updateChart();
              }
            } catch {}
          }

          function updateChart() {
            if (!chartRef.value || !history.value.length) return;
            const times = history.value.map(e => new Date((e.timestamp || 0) * 1000).toLocaleTimeString());
            const cpuData = history.value.map(e => e.cpu_percent || 0);
            const memData = history.value.map(e => e.mem_percent || 0);

            const traces = [
              { x: times, y: cpuData, name: 'CPU %', type: 'scatter', mode: 'lines', line: { color: '#f59e0b', width: 2 } },
              { x: times, y: memData, name: 'Memory %', type: 'scatter', mode: 'lines', line: { color: '#3b82f6', width: 2 } },
            ];
            const layout = {
              paper_bgcolor: 'transparent', plot_bgcolor: 'transparent',
              font: { color: '#94a3b8', size: 10 },
              margin: { l: 35, r: 10, t: 10, b: 30 },
              height: 180,
              yaxis: { range: [0, 100], gridcolor: 'rgba(255,255,255,0.05)' },
              xaxis: { gridcolor: 'rgba(255,255,255,0.05)' },
              legend: { orientation: 'h', y: 1.15, font: { size: 10 } },
              showlegend: true,
            };
            if (typeof Plotly !== 'undefined') {
              Plotly.react(chartRef.value, traces, layout, { responsive: true, displayModeBar: false });
            }
          }

          Vue.onMounted(() => { refresh(); setInterval(refresh, 5000); });

          return { latest, history, chartRef };
        },
        template: `
          <div data-plugin="system-monitor" style="max-width: 800px">
            <div v-if="!latest" style="color:var(--el-text-dim);text-align:center;padding:20px">
              <i class="ph ph-spinner" style="animation:spin 1s linear infinite"></i> Waiting for metrics...
            </div>
            <template v-else>
              <!-- Stat cards -->
              <div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(160px,1fr));gap:10px;margin-bottom:16px">
                <hort-stat-card
                  label="CPU Usage"
                  :value="String(latest.cpu_percent || 0)"
                  unit="%"
                  :trend="latest.cpu_percent > 80 ? 'up' : latest.cpu_percent > 50 ? 'flat' : 'down'"
                  icon="ph ph-cpu"
                  :color="latest.cpu_percent > 80 ? 'var(--el-danger)' : latest.cpu_percent > 50 ? 'var(--el-warning)' : 'var(--el-success)'"
                />
                <hort-stat-card
                  v-if="latest.cpu_temp_c"
                  label="CPU Temp"
                  :value="String(latest.cpu_temp_c)"
                  unit="°C"
                  :trend="latest.cpu_temp_c > 80 ? 'up' : 'flat'"
                  icon="ph ph-thermometer"
                  :color="latest.cpu_temp_c > 80 ? 'var(--el-danger)' : 'var(--el-warning)'"
                />
                <hort-stat-card
                  label="Memory"
                  :value="String(latest.mem_percent || 0)"
                  unit="%"
                  :trend="latest.mem_percent > 80 ? 'up' : 'flat'"
                  icon="ph ph-hard-drives"
                  :color="latest.mem_percent > 80 ? 'var(--el-danger)' : 'var(--el-primary)'"
                />
                <hort-stat-card
                  label="Disk"
                  :value="String(latest.disk_percent || 0)"
                  unit="%"
                  icon="ph ph-hard-drive"
                  :color="latest.disk_percent > 90 ? 'var(--el-danger)' : 'var(--el-text-dim)'"
                />
              </div>
              <!-- Detail row -->
              <div style="display:flex;gap:12px;flex-wrap:wrap;margin-bottom:16px;font-size:12px;color:var(--el-text-dim)">
                <span><i class="ph ph-cpu"></i> {{ latest.cpu_count }} cores @ {{ latest.cpu_freq_mhz }} MHz</span>
                <span><i class="ph ph-hard-drives"></i> {{ latest.mem_used_gb }}/{{ latest.mem_total_gb }} GB</span>
                <span><i class="ph ph-hard-drive"></i> {{ latest.disk_used_gb }}/{{ latest.disk_total_gb }} GB</span>
              </div>
              <!-- Chart -->
              <div style="background:var(--el-surface);border:1px solid var(--el-border);border-radius:10px;padding:12px">
                <div style="font-size:12px;color:var(--el-text-dim);margin-bottom:4px">Usage History (5 min)</div>
                <div ref="chartRef"></div>
              </div>
            </template>
          </div>
        `,
      });
    }
  }

  LlmingClient.register(SystemMonitorPanel);
})();
