/* Clipboard History — searchable clipboard panel UI */
/* global LlmingClient, Vue */

(function () {
  'use strict';

  class ClipboardHistoryPanel extends LlmingClient {
    static id = 'clipboard-history';
    static name = 'Clipboard History';
    static llmingTitle = 'Clipboard History';
    static llmingIcon = 'ph ph-clipboard-text';
    static llmingDescription = 'Searchable clipboard history';
    static llmingWidgets = ['clipboard-history-panel'];

    // Cached clipboard data for thumbnail
    _lastClips = null;

    _feedStore(store) {
      const clips = [];
      for (const [k, v] of Object.entries(store)) {
        if (k.startsWith('clip:') && v) clips.push(v);
      }
      clips.sort((a, b) => (b.timestamp || 0) - (a.timestamp || 0));
      this._lastClips = clips;
    }

    onConnect() {
      this.subscribe('clipboard_update', (data) => {
        if (!data) return;
        // Single clip update — merge into existing list
        if (data.text !== undefined) {
          const clips = [...(this._lastClips || [])];
          clips.unshift(data);
          this._lastClips = clips;
        } else if (Array.isArray(data.clips)) {
          this._lastClips = data.clips;
        }
      });
      this.vault.get('state').then(store => {
        if (!store) return;
        const clips = [];
        for (const [k, v] of Object.entries(store)) {
          if (k.startsWith('clip:') && v) clips.push(v);
        }
        if (clips.length) {
          clips.sort((a, b) => (b.timestamp || 0) - (a.timestamp || 0));
          this._lastClips = clips;
        }
      });
    }

    renderThumbnail(ctx, w, h) {
      const bg = '#111827', dim = '#94a3b8', text = '#f0f4ff';
      ctx.fillStyle = bg; ctx.fillRect(0, 0, w, h);

      const clips = this._lastClips;
      if (!clips || !clips.length) {
        ctx.fillStyle = dim; ctx.font = '13px system-ui'; ctx.textAlign = 'center';
        ctx.fillText('Clipboard History', w / 2, h / 2);
        return;
      }

      // Entry count header
      ctx.textAlign = 'center';
      ctx.fillStyle = text; ctx.font = 'bold 28px system-ui';
      ctx.fillText(String(clips.length), w / 2, 42);
      ctx.fillStyle = dim; ctx.font = '12px system-ui';
      ctx.fillText('clipboard entr' + (clips.length === 1 ? 'y' : 'ies'), w / 2, 60);

      // Preview last 3 entries
      const preview = clips.slice(0, 3);
      ctx.textAlign = 'left';
      ctx.font = '11px system-ui';
      const startY = 86;
      const lineH = 30;
      preview.forEach((clip, i) => {
        const y = startY + i * lineH;
        const t = (clip.text || '').replace(/\n/g, ' ').trim();
        const truncated = t.length > 38 ? t.substring(0, 38) + '...' : t;
        // Dim index
        ctx.fillStyle = dim;
        ctx.fillText((i + 1) + '.', 20, y);
        // Clip text
        ctx.fillStyle = text;
        ctx.fillText(truncated, 36, y);
      });

      // Title
      ctx.fillStyle = dim; ctx.font = '10px system-ui'; ctx.textAlign = 'center';
      ctx.fillText('Clipboard History', w / 2, h - 8);
    }

    setup(app) {
      app.component('clipboard-history-panel', {
        setup() {
          const bp = LlmingClient.basePath;
          const entries = Vue.ref([]);
          const searchQuery = Vue.ref('');
          const selectedEntry = Vue.ref(null);

          async function refresh() {
            try {
              const store = await fetch(bp + '/api/llmings/clipboard-history/status').catch(() => fetch(bp + '/api/llmings/clipboard-history/status')).then(r => r.json()).catch(() => null);
              if (!store) return;
              const items = [];
              for (const [k, v] of Object.entries(store)) {
                if (k.startsWith('clip:') && v) items.push(v);
              }
              items.sort((a, b) => (b.timestamp || 0) - (a.timestamp || 0));
              entries.value = items;
              // Cache for thumbnail rendering
              const inst = LlmingClient.get('clipboard-history');
              if (inst) inst._lastClips = items;
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

  LlmingClient.register(ClipboardHistoryPanel);
})();
