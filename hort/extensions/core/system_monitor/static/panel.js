/* System Monitor — dashboard UI */
/* global HortExtension, Vue, Plotly */

(function () {
  'use strict';

  class SystemMonitorPanel extends HortExtension {
    static id = 'system-monitor';
    static name = 'System Monitor';
    static llmingTitle = 'System Monitor';
    static llmingIcon = 'ph ph-cpu';
    static llmingDescription = 'CPU, memory, and disk monitoring';

    setup(app) {
      app.component('system-monitor-dashboard', {
        setup() {
          const bp = HortExtension.basePath;
          const latest = Vue.ref(null);
          const history = Vue.ref([]);
          const chartRef = Vue.ref(null);

          async function refresh() {
            try {
              const store = await fetch(bp + '/api/plugin/store').then(r => r.json()).catch(() => null);
              // Try plugin debugger endpoint first, fall back to main app
              if (store && store.latest) {
                latest.value = store.latest;
              } else {
                const resp = await fetch(bp + '/api/config/plugin.system-monitor').then(r => r.json()).catch(() => null);
                if (resp) latest.value = resp;
              }

              // Build history from store keys
              if (store) {
                const entries = [];
                for (const [k, v] of Object.entries(store)) {
                  if (k.startsWith('history:') && v) entries.push(v);
                }
                entries.sort((a, b) => (a.timestamp || 0) - (b.timestamp || 0));
                history.value = entries.slice(-60);
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

  HortExtension.register(SystemMonitorPanel);
})();
