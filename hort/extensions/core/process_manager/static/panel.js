/* Process Manager — task manager UI */
/* global HortExtension, Vue */

(function () {
  'use strict';

  class ProcessManagerPanel extends HortExtension {
    static id = 'process-manager';
    static name = 'Process Manager';
    static llmingTitle = 'Task Manager';
    static llmingIcon = 'ph ph-list-checks';
    static llmingDescription = 'View and manage running processes';

    setup(app) {
      app.component('process-manager-panel', {
        setup() {
          const bp = HortExtension.basePath;
          const processes = Vue.ref([]);
          const totalCount = Vue.ref(0);
          const sortBy = Vue.ref('cpu');
          const search = Vue.ref('');

          async function refresh() {
            try {
              const store = await fetch(bp + '/api/plugin/store').then(r => r.json()).catch(() => ({}));
              const data = store.processes || {};
              processes.value = data.list || [];
              totalCount.value = data.total || 0;
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

  HortExtension.register(ProcessManagerPanel);
})();
