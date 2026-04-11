/* Disk Usage — partition usage panel */
/* global LlmingClient, Vue */

(function () {
  'use strict';

  class DiskUsagePanel extends LlmingClient {
    static id = 'disk-usage';
    static name = 'Disk Usage';
    static llmingTitle = 'Disk Usage';
    static llmingIcon = 'ph ph-hard-drive';
    static llmingDescription = 'Disk partition usage monitoring';
    static llmingWidgets = ['disk-usage-panel'];

    // Cached disk data for thumbnail
    _lastDisks = null;

    // Legacy polling (kept for backward compat with renderPluginThumbs)
    _feedStore(store) { if (store.latest) this._lastDisks = store.latest.partitions || []; }

    // New: subscribe to push-based pulse + load initial data from vault
    onConnect() {
      // Subscribe to disk_usage pulse channel
      this.subscribe('disk_usage', (data) => {
        this._lastDisks = data.partitions || [];
      });
      // Load initial data from vault
      this.vaultRead('latest').then(data => {
        if (data && data.partitions) {
          this._lastDisks = data.partitions;
        }
      });
    }

    renderThumbnail(ctx, w, h) {
      const bg = '#111827', dim = '#94a3b8', text = '#f0f4ff';
      ctx.fillStyle = bg; ctx.fillRect(0, 0, w, h);

      const disks = this._lastDisks;
      if (!disks || !disks.length) {
        ctx.fillStyle = dim; ctx.font = '13px system-ui'; ctx.textAlign = 'center';
        ctx.fillText('Disk Usage', w / 2, h / 2);
        return;
      }

      // Show main disks: prefer /System/Volumes/Data (macOS real data) or / on Linux
      let main = disks.filter(d => d.total_gb > 1 && !d.mountpoint.includes('/Preboot') && !d.mountpoint.includes('/Update') && !d.mountpoint.includes('/VM') && !d.mountpoint.includes('/xarts') && !d.mountpoint.includes('/iSCPreboot') && !d.mountpoint.includes('/Hardware'));
      // On macOS, /System/Volumes/Data is the real disk; skip bare / if Data exists
      const dataVol = main.find(d => d.mountpoint === '/System/Volumes/Data');
      if (dataVol) main = main.filter(d => d.mountpoint !== '/');
      // Deduplicate same-size disks (macOS mirrors)
      const seen = new Set();
      main = main.filter(d => {
        const key = Math.round(d.total_gb);
        if (seen.has(key) && d.mountpoint !== '/System/Volumes/Data' && d.mountpoint !== '/') return false;
        seen.add(key);
        return true;
      });
      main = main.slice(0, 3);
      if (!main.length) main.push(disks[0]);
      const pieR = Math.min(38, (h - 40) / 2);
      const spacing = w / (main.length + 1);

      main.forEach((d, i) => {
        const cx = spacing * (i + 1);
        const cy = h / 2 - 8;
        const pct = (d.percent || 0) / 100;
        const usedColor = pct > 0.9 ? '#ef4444' : pct > 0.8 ? '#f59e0b' : '#3b82f6';

        // Free space arc (dark)
        ctx.beginPath();
        ctx.arc(cx, cy, pieR, 0, Math.PI * 2);
        ctx.fillStyle = '#1e293b';
        ctx.fill();

        // Used space arc
        ctx.beginPath();
        ctx.moveTo(cx, cy);
        ctx.arc(cx, cy, pieR, -Math.PI / 2, -Math.PI / 2 + Math.PI * 2 * pct);
        ctx.closePath();
        ctx.fillStyle = usedColor;
        ctx.fill();

        // Center hole (donut)
        ctx.beginPath();
        ctx.arc(cx, cy, pieR * 0.55, 0, Math.PI * 2);
        ctx.fillStyle = bg;
        ctx.fill();

        // Percentage in center
        ctx.fillStyle = text; ctx.font = 'bold 14px system-ui'; ctx.textAlign = 'center';
        ctx.fillText(Math.round(d.percent) + '%', cx, cy + 5);

        // Label below
        ctx.fillStyle = dim; ctx.font = '9px system-ui';
        const label = d.mountpoint === '/' ? 'Main' : (d.mountpoint || '').split('/').pop() || '?';
        ctx.fillText(label, cx, cy + pieR + 14);
      });
    }

    setup(app) {
      app.component('disk-usage-panel', {
        setup() {
          const bp = LlmingClient.basePath;
          const partitions = Vue.ref([]);
          const timestamp = Vue.ref(null);

          async function refresh() {
            try {
              const store = await fetch(bp + '/api/llmings/disk-usage/status').catch(() => fetch(bp + '/api/llmings/disk-usage/status')).then(r => r.json()).catch(() => null);
              if (store && store.latest) {
                const data = store.latest;
                partitions.value = data.partitions || [];
                timestamp.value = data.timestamp ? new Date(data.timestamp * 1000).toLocaleTimeString() : null;
                // Cache for thumbnail rendering
                const inst = LlmingClient.get('disk-usage');
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

  LlmingClient.register(DiskUsagePanel);
})();
