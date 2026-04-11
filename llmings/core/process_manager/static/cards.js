/* Process Manager — task manager UI */
/* global LlmingClient, Vue */

(function () {
  'use strict';

  class ProcessManagerPanel extends LlmingClient {
    static id = 'process-manager';
    static name = 'Process Manager';
    static llmingTitle = 'Task Manager';
    static llmingIcon = 'ph ph-list-checks';
    static llmingDescription = 'View and manage running processes';
    static llmingWidgets = ['process-manager-panel'];

    // Cached process data for thumbnail
    _lastProcesses = null;

    _feedStore(store) { if (store.processes) this._lastProcesses = store.processes.list || store.processes; }

    onConnect() {
      this.subscribe('process_update', (data) => {
        if (data) this._lastProcesses = data.list || data;
      });
      this.vaultRead('latest').then(data => {
        if (data && data.processes) {
          this._lastProcesses = data.processes.list || data.processes;
        }
      });
    }

    renderThumbnail(ctx, w, h) {
      const bg = '#111827', dim = '#94a3b8', text = '#f0f4ff', bar = '#3b82f6';
      ctx.fillStyle = bg; ctx.fillRect(0, 0, w, h);

      const procs = this._lastProcesses;
      if (!procs || !procs.length) {
        ctx.fillStyle = dim; ctx.font = '13px system-ui'; ctx.textAlign = 'center';
        ctx.fillText('Process Manager', w / 2, h / 2);
        return;
      }

      // Top 5 by CPU
      const top5 = [...procs].sort((a, b) => b.cpu - a.cpu).slice(0, 5);
      const maxCpu = Math.max(top5[0].cpu, 1);
      const barH = 22, gap = 8, startY = 18;
      ctx.font = 'bold 11px system-ui';
      ctx.textAlign = 'left';
      top5.forEach((p, i) => {
        const y = startY + i * (barH + gap);
        // Background bar
        ctx.fillStyle = '#1e293b'; ctx.fillRect(20, y, w - 40, barH);
        // Fill bar
        ctx.fillStyle = bar;
        ctx.fillRect(20, y, (w - 40) * p.cpu / maxCpu, barH);
        // Process name
        ctx.fillStyle = text;
        ctx.fillText(p.name.length > 18 ? p.name.substring(0, 18) + '..' : p.name, 26, y + 15);
        // CPU percentage
        ctx.textAlign = 'right';
        ctx.fillText(p.cpu.toFixed(1) + '%', w - 26, y + 15);
        ctx.textAlign = 'left';
      });
      // Title
      ctx.fillStyle = dim; ctx.font = '10px system-ui'; ctx.textAlign = 'center';
      ctx.fillText('Process Manager', w / 2, h - 8);
    }

    setup(app) {
      app.component('process-manager-panel', {
        setup() {
          const bp = LlmingClient.basePath;
          const processes = Vue.ref([]);
          const totalCount = Vue.ref(0);
          const sortBy = Vue.ref('cpu');
          const search = Vue.ref('');

          async function refresh() {
            try {
              const store = await fetch(bp + '/api/llmings/process-manager/status').catch(() => fetch(bp + '/api/llmings/process-manager/status')).then(r => r.json()).catch(() => ({}));
              const data = store.processes || {};
              processes.value = data.list || [];
              totalCount.value = data.total || 0;
              // Cache for thumbnail rendering
              const inst = LlmingClient.get('process-manager');
              if (inst) inst._lastProcesses = data.list || [];
            } catch {}
          }

          const filtered = Vue.computed(() => {
            let list = [...processes.value];
            if (search.value) {
              const q = search.value.toLowerCase();
              list = list.filter(p => p.name.toLowerCase().includes(q) || String(p.pid).includes(q));
            }
            if (sortBy.value === 'mem') list.sort((a, b) => b.mem - a.mem);
            else if (sortBy.value === 'name') list.sort((a, b) => a.name.localeCompare(b.name));
            else list.sort((a, b) => b.cpu - a.cpu);
            return list;
          });

          Vue.onMounted(() => { refresh(); setInterval(refresh, 10000); });

          return { processes, totalCount, sortBy, search, filtered };
        },
        template: `
          <div data-plugin="process-manager" style="max-width: 700px">
            <div style="display:flex;gap:8px;margin-bottom:12px;align-items:center">
              <input v-model="search" placeholder="Search processes..."
                style="flex:1;padding:8px 12px;background:var(--el-surface);color:var(--el-text);border:1px solid var(--el-border);border-radius:6px;font-size:13px">
              <select v-model="sortBy"
                style="padding:8px;background:var(--el-surface);color:var(--el-text);border:1px solid var(--el-border);border-radius:6px;font-size:12px">
                <option value="cpu">Sort: CPU</option>
                <option value="mem">Sort: Memory</option>
                <option value="name">Sort: Name</option>
              </select>
              <span style="font-size:11px;color:var(--el-text-dim)">{{ totalCount }} processes</span>
            </div>
            <div style="overflow-x:auto">
              <table style="width:100%;border-collapse:collapse;font-size:12px">
                <thead>
                  <tr style="border-bottom:1px solid var(--el-border)">
                    <th style="text-align:right;padding:6px 8px;color:var(--el-text-dim);font-size:11px">PID</th>
                    <th style="text-align:left;padding:6px 8px;color:var(--el-text-dim);font-size:11px">NAME</th>
                    <th style="text-align:right;padding:6px 8px;color:var(--el-text-dim);font-size:11px">CPU %</th>
                    <th style="text-align:right;padding:6px 8px;color:var(--el-text-dim);font-size:11px">MEM %</th>
                    <th style="text-align:left;padding:6px 8px;color:var(--el-text-dim);font-size:11px">STATUS</th>
                  </tr>
                </thead>
                <tbody>
                  <tr v-for="p in filtered" :key="p.pid"
                      style="border-bottom:1px solid rgba(255,255,255,0.03)"
                      :style="{background: p.cpu > 50 ? 'rgba(239,68,68,0.08)' : 'transparent'}">
                    <td style="text-align:right;padding:4px 8px;color:var(--el-text-dim);font-family:monospace">{{ p.pid }}</td>
                    <td style="padding:4px 8px;font-weight:500">{{ p.name }}</td>
                    <td style="text-align:right;padding:4px 8px;font-family:monospace"
                        :style="{color: p.cpu > 50 ? 'var(--el-danger)' : p.cpu > 10 ? 'var(--el-warning)' : 'var(--el-text)'}">
                      {{ p.cpu.toFixed(1) }}
                    </td>
                    <td style="text-align:right;padding:4px 8px;font-family:monospace"
                        :style="{color: p.mem > 10 ? 'var(--el-primary)' : 'var(--el-text)'}">
                      {{ p.mem.toFixed(1) }}
                    </td>
                    <td style="padding:4px 8px;color:var(--el-text-dim);font-size:11px">{{ p.status }}</td>
                  </tr>
                </tbody>
              </table>
            </div>
          </div>
        `,
      });
    }
  }

  LlmingClient.register(ProcessManagerPanel);
})();
