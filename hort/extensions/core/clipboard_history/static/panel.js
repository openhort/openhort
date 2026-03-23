/* Clipboard History — searchable clipboard panel UI */
/* global HortExtension, Vue */

(function () {
  'use strict';

  class ClipboardHistoryPanel extends HortExtension {
    static id = 'clipboard-history';
    static name = 'Clipboard History';
    static llmingTitle = 'Clipboard History';
    static llmingIcon = 'ph ph-clipboard-text';
    static llmingDescription = 'Searchable clipboard history';

    setup(app) {
      app.component('clipboard-history-panel', {
        setup() {
          const bp = HortExtension.basePath;
          const entries = Vue.ref([]);
          const searchQuery = Vue.ref('');
          const selectedEntry = Vue.ref(null);

          async function refresh() {
            try {
              const store = await fetch(bp + '/api/plugin/store').then(r => r.json()).catch(() => null);
              if (!store) return;
              const items = [];
              for (const [k, v] of Object.entries(store)) {
                if (k.startsWith('clip:') && v) items.push(v);
              }
              items.sort((a, b) => (b.timestamp || 0) - (a.timestamp || 0));
              entries.value = items;
            } catch {}
          }

          const filteredEntries = Vue.computed(() => {
            const q = searchQuery.value.toLowerCase().trim();
            if (!q) return entries.value;
            return entries.value.filter(e => (e.text || '').toLowerCase().includes(q));
          });

          function formatTime(ts) {
            if (!ts) return '';
            const d = new Date(ts);
            return d.toLocaleTimeString();
          }

          function truncate(text, max) {
            if (!text) return '';
            return text.length > max ? text.substring(0, max) + '...' : text;
          }

          function selectEntry(entry) {
            selectedEntry.value = selectedEntry.value === entry ? null : entry;
          }

          Vue.onMounted(() => { refresh(); setInterval(refresh, 3000); });

          return { entries, searchQuery, filteredEntries, selectedEntry, formatTime, truncate, selectEntry };
        },
        template: `
          <div data-plugin="clipboard-history" style="max-width: 800px">
            <!-- Search box -->
            <div style="margin-bottom:12px">
              <div style="position:relative">
                <i class="ph ph-magnifying-glass" style="position:absolute;left:10px;top:50%;transform:translateY(-50%);color:var(--el-text-dim);font-size:14px"></i>
                <input
                  v-model="searchQuery"
                  placeholder="Search clipboard history..."
                  style="width:100%;padding:8px 12px 8px 32px;background:var(--el-surface);border:1px solid var(--el-border);border-radius:8px;color:var(--el-text);font-size:13px;outline:none;box-sizing:border-box"
                />
              </div>
            </div>

            <!-- Empty state -->
            <div v-if="!entries.length" style="color:var(--el-text-dim);text-align:center;padding:20px">
              <i class="ph ph-clipboard-text" style="font-size:32px;display:block;margin-bottom:8px"></i>
              Waiting for clipboard activity...
            </div>

            <!-- No results -->
            <div v-else-if="!filteredEntries.length" style="color:var(--el-text-dim);text-align:center;padding:20px">
              No entries matching "{{ searchQuery }}"
            </div>

            <!-- Entry list -->
            <div v-else style="display:flex;flex-direction:column;gap:6px">
              <div
                v-for="(entry, idx) in filteredEntries"
                :key="entry.timestamp"
                @click="selectEntry(entry)"
                style="background:var(--el-surface);border:1px solid var(--el-border);border-radius:8px;padding:10px 12px;cursor:pointer;transition:border-color 0.15s"
                :style="selectedEntry === entry ? 'border-color:var(--el-primary)' : ''"
              >
                <!-- Header row -->
                <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:4px">
                  <span style="font-size:11px;color:var(--el-text-dim)">
                    <i class="ph ph-clock"></i> {{ formatTime(entry.timestamp) }}
                  </span>
                  <span style="font-size:11px;color:var(--el-text-dim)">
                    {{ entry.length || 0 }} chars
                  </span>
                </div>
                <!-- Preview / full text -->
                <div style="font-size:13px;color:var(--el-text);white-space:pre-wrap;word-break:break-word;font-family:monospace;line-height:1.4">{{ selectedEntry === entry ? entry.text : truncate(entry.text, 100) }}</div>
              </div>
            </div>

            <!-- Entry count -->
            <div v-if="entries.length" style="text-align:center;margin-top:12px;font-size:11px;color:var(--el-text-dim)">
              {{ filteredEntries.length }} of {{ entries.length }} entries
            </div>
          </div>
        `,
      });
    }
  }

  HortExtension.register(ClipboardHistoryPanel);
})();
