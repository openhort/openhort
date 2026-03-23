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
    static llmingWidgets = ['disk-usage-panel'];

    // Cached disk data for thumbnail
    _lastDisks = null;

    renderThumbnail(ctx, w, h) {
      const bg = '#111827', dim = '#94a3b8', text = '#f0f4ff';
      ctx.fillStyle = bg; ctx.fillRect(0, 0, w, h);

      const disks = this._lastDisks;
      if (!disks || !disks.length) {
        ctx.fillStyle = dim; ctx.font = '13px system-ui'; ctx.textAlign = 'center';
        ctx.fillText('Disk Usage', w / 2, h / 2);
        return;
      }

      function barColor(pct) {
        if (pct >= 90) return '#ef4444';
        if (pct >= 80) return '#f59e0b';
        return '#22c55e';
      }

      const maxBars = Math.min(disks.length, 5);
      const barH = 24, gap = 10, startY = 20;
      ctx.font = 'bold 11px system-ui';
      ctx.textAlign = 'left';
      for (let i = 0; i < maxBars; i++) {
        const p = disks[i];
        const y = startY + i * (barH + gap);
        const pct = p.percent || 0;
        // Background bar
        ctx.fillStyle = '#1e293b'; ctx.fillRect(20, y, w - 40, barH);
        // Fill bar
        ctx.fillStyle = barColor(pct);
        ctx.fillRect(20, y, (w - 40) * pct / 100, barH);
        // Mount label
        const label = p.mountpoint || p.device || '?';
        ctx.fillStyle = text;
        ctx.fillText(label.length > 16 ? label.substring(0, 16) + '..' : label, 26, y + 16);
        // Percentage
        ctx.textAlign = 'right';
        ctx.fillText(Math.round(pct) + '%', w - 26, y + 16);
        ctx.textAlign = 'left';
      }
      // Title
      ctx.fillStyle = dim; ctx.font = '10px system-ui'; ctx.textAlign = 'center';
      ctx.fillText('Disk Usage', w / 2, h - 8);
    }

    setup(app) {
      app.component('disk-usage-panel', {
        setup() {
          const bp = HortExtension.basePath;
          const partitions = Vue.ref([]);
          const timestamp = Vue.ref(null);

          async function refresh() {
            try {
              const store = await fetch(bp + '/api/plugins/disk-usage/store').catch(() => fetch(bp + '/api/plugin/store')).then(r => r.json()).catch(() => null);
              if (store && store.latest) {
                const data = store.latest;
                partitions.value = data.partitions || [];
                timestamp.value = data.timestamp ? new Date(data.timestamp * 1000).toLocaleTimeString() : null;
                // Cache for thumbnail rendering
                const inst = HortExtension.get('disk-usage');
                if (inst) inst._lastDisks = data.partitions || [];
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
