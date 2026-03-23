/* Disk Usage — partition usage panel */
/* global HortExtension, Vue */

(function () {
  'use strict';

  class DiskUsagePanel extends HortExtension {
    static id = 'disk-usage';
    static name = 'Disk Usage';
    static llmingTitle = 'Disk Usage';
    static llmingIcon = 'ph ph-hard-drive';
    static llmingDescription = 'Disk partition usage monitoring';

    setup(app) {
      app.component('disk-usage-panel', {
        setup() {
          const bp = HortExtension.basePath;
          const partitions = Vue.ref([]);
          const timestamp = Vue.ref(null);

          async function refresh() {
            try {
              const store = await fetch(bp + '/api/plugin/store').then(r => r.json()).catch(() => null);
              if (store && store.latest) {
                const data = store.latest;
                partitions.value = data.partitions || [];
                timestamp.value = data.timestamp ? new Date(data.timestamp * 1000).toLocaleTimeString() : null;
              }
            } catch {}
          }

          Vue.onMounted(() => { refresh(); setInterval(refresh, 30000); });

          function barColor(percent) {
            if (percent >= 90) return 'var(--el-danger, #ef4444)';
            if (percent >= 80) return 'var(--el-warning, #f59e0b)';
            return 'var(--el-success, #22c55e)';
          }

          return { partitions, timestamp, barColor };
        },
        template: `
          <div data-plugin="disk-usage" style="max-width: 800px">
            <div v-if="!partitions.length" style="color:var(--el-text-dim);text-align:center;padding:20px">
              <i class="ph ph-spinner" style="animation:spin 1s linear infinite"></i> Waiting for disk data...
            </div>
            <template v-else>
              <div style="font-size:11px;color:var(--el-text-dim);margin-bottom:10px" v-if="timestamp">
                Last updated: {{ timestamp }}
              </div>
              <div style="background:var(--el-surface);border:1px solid var(--el-border);border-radius:10px;overflow:hidden">
                <table style="width:100%;border-collapse:collapse;font-size:13px">
                  <thead>
                    <tr style="border-bottom:1px solid var(--el-border);color:var(--el-text-dim);font-size:11px;text-transform:uppercase;letter-spacing:0.5px">
                      <th style="padding:10px 12px;text-align:left">Device</th>
                      <th style="padding:10px 12px;text-align:left">Mount</th>
                      <th style="padding:10px 12px;text-align:right">Used / Total</th>
                      <th style="padding:10px 12px;text-align:left;min-width:140px">Usage</th>
                    </tr>
                  </thead>
                  <tbody>
                    <tr v-for="p in partitions" :key="p.mountpoint" style="border-bottom:1px solid var(--el-border)">
                      <td style="padding:8px 12px;font-family:monospace;font-size:12px;color:var(--el-text-dim)">{{ p.device }}</td>
                      <td style="padding:8px 12px;font-family:monospace;font-size:12px">{{ p.mountpoint }}</td>
                      <td style="padding:8px 12px;text-align:right;white-space:nowrap">
                        {{ p.used_gb }} / {{ p.total_gb }} GB
                      </td>
                      <td style="padding:8px 12px">
                        <div style="display:flex;align-items:center;gap:8px">
                          <div style="flex:1;height:8px;background:var(--el-border);border-radius:4px;overflow:hidden">
                            <div :style="{
                              width: p.percent + '%',
                              height: '100%',
                              background: barColor(p.percent),
                              borderRadius: '4px',
                              transition: 'width 0.5s ease'
                            }"></div>
                          </div>
                          <span :style="{ color: barColor(p.percent), fontWeight: 600, fontSize: '12px', minWidth: '36px', textAlign: 'right' }">
                            {{ p.percent }}%
                          </span>
                        </div>
                      </td>
                    </tr>
                  </tbody>
                </table>
              </div>
            </template>
          </div>
        `,
      });
    }
  }

  HortExtension.register(DiskUsagePanel);
})();
