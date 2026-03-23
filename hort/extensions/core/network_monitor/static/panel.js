/* Network Monitor — dashboard UI */
/* global HortExtension, Vue, Plotly */

(function () {
  'use strict';

  class NetworkMonitorPanel extends HortExtension {
    static id = 'network-monitor';
    static name = 'Network Monitor';
    static llmingTitle = 'Network Monitor';
    static llmingIcon = 'ph ph-wifi-high';
    static llmingDescription = 'Network interfaces and bandwidth monitoring';

    setup(app) {
      app.component('network-monitor-panel', {
        setup() {
          const bp = HortExtension.basePath;
          const latest = Vue.ref(null);
          const history = Vue.ref([]);
          const chartRef = Vue.ref(null);

          function formatSpeed(bps) {
            if (bps == null) return '0 B/s';
            if (bps >= 1024 * 1024) return (bps / (1024 * 1024)).toFixed(1) + ' MB/s';
            if (bps >= 1024) return (bps / 1024).toFixed(1) + ' KB/s';
            return Math.round(bps) + ' B/s';
          }

          function formatSpeedValue(bps) {
            if (bps == null) return { value: '0', unit: 'B/s' };
            if (bps >= 1024 * 1024) return { value: (bps / (1024 * 1024)).toFixed(1), unit: 'MB/s' };
            if (bps >= 1024) return { value: (bps / 1024).toFixed(1), unit: 'KB/s' };
            return { value: Math.round(bps).toString(), unit: 'B/s' };
          }

          async function refresh() {
            try {
              const store = await fetch(bp + '/api/plugin/store').then(r => r.json()).catch(() => null);
              if (store && store.latest) {
                latest.value = store.latest;
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
            const uploadData = history.value.map(e => (e.total_upload_bps || 0) / 1024);
            const downloadData = history.value.map(e => (e.total_download_bps || 0) / 1024);

            const traces = [
              { x: times, y: uploadData, name: 'Upload KB/s', type: 'scatter', mode: 'lines', line: { color: '#f59e0b', width: 2 } },
              { x: times, y: downloadData, name: 'Download KB/s', type: 'scatter', mode: 'lines', line: { color: '#3b82f6', width: 2 } },
            ];
            const layout = {
              paper_bgcolor: 'transparent', plot_bgcolor: 'transparent',
              font: { color: '#94a3b8', size: 10 },
              margin: { l: 40, r: 10, t: 10, b: 30 },
              height: 180,
              yaxis: { gridcolor: 'rgba(255,255,255,0.05)', title: { text: 'KB/s', font: { size: 10 } } },
              xaxis: { gridcolor: 'rgba(255,255,255,0.05)' },
              legend: { orientation: 'h', y: 1.15, font: { size: 10 } },
              showlegend: true,
            };
            if (typeof Plotly !== 'undefined') {
              Plotly.react(chartRef.value, traces, layout, { responsive: true, displayModeBar: false });
            }
          }

          Vue.onMounted(() => { refresh(); setInterval(refresh, 5000); });

          return { latest, history, chartRef, formatSpeed, formatSpeedValue };
        },
        template: `
          <div data-plugin="network-monitor" style="max-width: 800px">
            <div v-if="!latest" style="color:var(--el-text-dim);text-align:center;padding:20px">
              <i class="ph ph-spinner" style="animation:spin 1s linear infinite"></i> Waiting for network data...
            </div>
            <template v-else>
              <!-- Stat cards -->
              <div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(160px,1fr));gap:10px;margin-bottom:16px">
                <hort-stat-card
                  label="Upload"
                  :value="formatSpeedValue(latest.total_upload_bps).value"
                  :unit="formatSpeedValue(latest.total_upload_bps).unit"
                  :trend="latest.total_upload_bps > 1024*1024 ? 'up' : 'flat'"
                  icon="ph ph-arrow-up"
                  :color="latest.total_upload_bps > 1024*1024 ? 'var(--el-warning)' : 'var(--el-success)'"
                />
                <hort-stat-card
                  label="Download"
                  :value="formatSpeedValue(latest.total_download_bps).value"
                  :unit="formatSpeedValue(latest.total_download_bps).unit"
                  :trend="latest.total_download_bps > 1024*1024 ? 'up' : 'flat'"
                  icon="ph ph-arrow-down"
                  :color="latest.total_download_bps > 1024*1024 ? 'var(--el-warning)' : 'var(--el-primary)'"
                />
              </div>
              <!-- Interface list -->
              <div style="background:var(--el-surface);border:1px solid var(--el-border);border-radius:10px;padding:12px;margin-bottom:16px">
                <div style="font-size:12px;color:var(--el-text-dim);margin-bottom:8px">Network Interfaces</div>
                <div v-for="iface in latest.interfaces" :key="iface.name"
                     style="display:flex;align-items:center;justify-content:space-between;padding:6px 0;border-bottom:1px solid var(--el-border)">
                  <div>
                    <div style="font-size:13px;font-weight:500;color:var(--el-text)">
                      <i class="ph ph-plugs-connected" style="margin-right:4px"></i>{{ iface.name }}
                    </div>
                    <div style="font-size:11px;color:var(--el-text-dim)">
                      {{ iface.ips && iface.ips.length ? iface.ips.join(', ') : 'No IP' }}
                    </div>
                  </div>
                  <div v-if="iface.upload_bps != null" style="text-align:right;font-size:11px;color:var(--el-text-dim)">
                    <span style="color:#f59e0b"><i class="ph ph-arrow-up"></i> {{ formatSpeed(iface.upload_bps) }}</span>
                    <span style="margin-left:8px;color:#3b82f6"><i class="ph ph-arrow-down"></i> {{ formatSpeed(iface.download_bps) }}</span>
                  </div>
                </div>
              </div>
              <!-- Bandwidth chart -->
              <div style="background:var(--el-surface);border:1px solid var(--el-border);border-radius:10px;padding:12px">
                <div style="font-size:12px;color:var(--el-text-dim);margin-bottom:4px">Bandwidth History (5 min)</div>
                <div ref="chartRef"></div>
              </div>
            </template>
          </div>
        `,
      });
    }
  }

  HortExtension.register(NetworkMonitorPanel);
})();
