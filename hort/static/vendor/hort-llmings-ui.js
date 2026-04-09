/**
 * hort-llmings-ui.js — Llming integration into the main openhort UI.
 *
 * Responsibilities:
 * 1. Discovers llmings via WS (llmings.list) and loads their UI scripts
 * 2. Generates thumbnail previews for llming cards (every 5s)
 * 3. Manages active llming panels (auto-show, sort by last access)
 * 4. Provides <hort-llming-manager> config panel
 *
 * Loaded after hort-widgets.js.
 */

/* global Vue, HortExtension */

(function (root) {
  'use strict';

  let _pluginsData = [];
  let _loadedScripts = new Set();

  // Thumbnail canvases keyed by plugin id
  const _thumbCanvases = {};
  const _thumbDataUrls = {};
  const THUMB_W = 320, THUMB_H = 200;

  // ---- Plugin discovery + script loading ----

  async function discoverAndLoadPlugins() {
    try {
      if (!window.hortWS) { console.warn('[plugins] WS not ready'); return; }
      const msg = await window.hortWS.request({ type: 'llmings.list' });
      _pluginsData = msg ? msg.data : [];
      const bp = HortExtension.basePath;
      const promises = [];
      for (const p of _pluginsData) {
        if (p.loaded && p.ui_script_url && !_loadedScripts.has(p.ui_script_url)) {
          const url = bp + p.ui_script_url;  // prefix with basePath for proxy support
          promises.push(_loadScript(url));
          _loadedScripts.add(p.ui_script_url);
        }
      }
      await Promise.allSettled(promises);
    } catch (e) {
      console.warn('[plugins] Discovery failed:', e);
    }
  }

  function _loadScript(url) {
    return new Promise((resolve) => {
      const s = document.createElement('script');
      s.src = url;
      s.onload = resolve;
      s.onerror = () => { console.warn('[plugins] Failed:', url); resolve(); };
      document.body.appendChild(s);
    });
  }

  function getPlugins() { return _pluginsData; }

  // ---- Thumbnail rendering ----

  function renderAllThumbnails() {
    for (const [id, inst] of HortExtension.getRegistry()) {
      if (!inst || !HortExtension.get(id)) continue;
      const active = HortExtension.get(id);
      if (typeof active.renderThumbnail !== 'function') continue;
      if (!_thumbCanvases[id]) {
        const c = document.createElement('canvas');
        c.width = THUMB_W; c.height = THUMB_H;
        _thumbCanvases[id] = c;
      }
      try {
        const ctx = _thumbCanvases[id].getContext('2d');
        active.renderThumbnail(ctx, THUMB_W, THUMB_H);
        _thumbDataUrls[id] = _thumbCanvases[id].toDataURL('image/jpeg', 0.8);
      } catch (e) {
        // Plugin thumbnail error — ignore
      }
    }
  }

  function getThumbnailUrl(pluginId) {
    return _thumbDataUrls[pluginId] || '';
  }

  // Thumbnail loop — fast when visible (2s), slow when hidden (10s)
  let _thumbTimer = null;
  function startThumbnailLoop() {
    renderAllThumbnails();
    function schedule() {
      const visible = document.visibilityState === 'visible';
      const interval = visible ? 2000 : 10000;
      _thumbTimer = setTimeout(() => { renderAllThumbnails(); schedule(); }, interval);
    }
    schedule();
    document.addEventListener('visibilitychange', () => {
      if (_thumbTimer) { clearTimeout(_thumbTimer); _thumbTimer = null; }
      schedule();
    });
  }

  // ---- Auto-show plugins ----

  function getAutoShowPlugins() {
    const result = [];
    for (const [id, ExtClass] of HortExtension.getRegistry()) {
      if (ExtClass.autoShow && ExtClass.llmingWidgets && ExtClass.llmingWidgets.length) {
        result.push({
          id,
          widgets: ExtClass.llmingWidgets,
          icon: ExtClass.llmingIcon,
          title: ExtClass.llmingTitle || ExtClass.name || id,
        });
      }
    }
    return result;
  }

  // ---- Plugin Manager Component ----

  function registerPluginManager(app) {
    app.component('hort-plugin-manager', {
      setup() {
        const plugins = Vue.ref([]);
        const search = Vue.ref('');
        const tab = Vue.ref('active'); // 'active' | 'background' | 'config'

        async function refresh() {
          try {
            if (!window.hortWS) return;
            const msg = await window.hortWS.request({ type: 'llmings.list' });
            if (msg && msg.data) plugins.value = msg.data;
          } catch {}
        }

        const activePlugins = Vue.computed(() => plugins.value.filter(p => p.loaded && p.ui_script_url));
        const backgroundPlugins = Vue.computed(() => plugins.value.filter(p => p.loaded && !p.ui_script_url));
        const filtered = Vue.computed(() => {
          const q = search.value.toLowerCase();
          const list = tab.value === 'active' ? activePlugins.value
            : tab.value === 'background' ? backgroundPlugins.value
            : plugins.value;
          return list.filter(p => !q || p.name.includes(q) || (p.description || '').toLowerCase().includes(q));
        });

        async function toggleFeature(pluginId, feature, enabled) {
          if (window.hortWS) {
            await window.hortWS.request({ type: 'llmings.feature', name: pluginId, feature, enabled });
          }
          await refresh();
        }

        Vue.onMounted(() => { refresh(); setInterval(refresh, 10000); });

        return { plugins, search, tab, filtered, activePlugins, backgroundPlugins, toggleFeature };
      },
      template: `
        <div data-plugin="plugin-manager" style="max-width: 800px">
          <!-- Tabs -->
          <div style="display:flex;gap:0;margin-bottom:12px;border-radius:6px;overflow:hidden;border:1px solid var(--el-border)">
            <button v-for="t in [{id:'active',label:'UI Plugins',icon:'ph ph-monitor'},{id:'background',label:'Background',icon:'ph ph-gear'},{id:'config',label:'All Plugins',icon:'ph ph-sliders'}]"
              :key="t.id" @click="tab = t.id"
              style="flex:1;padding:8px;border:none;font-size:12px;cursor:pointer;display:flex;align-items:center;justify-content:center;gap:4px"
              :style="{background: tab === t.id ? 'var(--el-primary)' : 'var(--el-surface)', color: tab === t.id ? '#fff' : 'var(--el-text-dim)'}">
              <i :class="t.icon"></i> {{ t.label }}
              <span v-if="t.id === 'active'" style="font-size:10px;opacity:0.7">({{ activePlugins.length }})</span>
              <span v-if="t.id === 'background'" style="font-size:10px;opacity:0.7">({{ backgroundPlugins.length }})</span>
            </button>
          </div>
          <!-- Search -->
          <input v-model="search" placeholder="Search plugins..."
            style="width:100%;padding:8px 12px;background:var(--el-surface);color:var(--el-text);border:1px solid var(--el-border);border-radius:6px;font-size:13px;margin-bottom:12px;box-sizing:border-box">
          <!-- Plugin cards -->
          <div v-for="p in filtered" :key="p.name"
            style="background:var(--el-surface);border:1px solid var(--el-border);border-radius:10px;padding:12px;margin-bottom:8px">
            <div style="display:flex;align-items:center;gap:10px">
              <i :class="p.icon || 'ph ph-puzzle-piece'" style="font-size:22px;color:var(--el-primary)"></i>
              <div style="flex:1">
                <span style="font-weight:600;font-size:13px">{{ p.name }}</span>
                <span style="font-size:11px;color:var(--el-text-dim);margin-left:6px">{{ p.description }}</span>
              </div>
              <span style="font-size:10px;padding:2px 8px;border-radius:4px"
                :style="{background: p.loaded ? 'rgba(34,197,94,0.15)' : 'rgba(148,163,184,0.15)', color: p.loaded ? 'var(--el-success)' : 'var(--el-text-dim)'}">
                {{ p.loaded ? 'Active' : 'Inactive' }}
              </span>
            </div>
            <!-- Features -->
            <div v-if="Object.keys(p.features).length" style="margin-top:8px;display:flex;gap:8px;flex-wrap:wrap">
              <label v-for="(ft, fname) in p.features" :key="fname"
                style="display:flex;align-items:center;gap:4px;font-size:11px;cursor:pointer">
                <input type="checkbox" :checked="ft.enabled" @change="toggleFeature(p.name, fname, $event.target.checked)" :disabled="!p.loaded">
                {{ fname }}
              </label>
            </div>
            <!-- Running jobs -->
            <div v-if="p.running_jobs && p.running_jobs.length" style="margin-top:6px;display:flex;gap:4px">
              <span v-for="j in p.running_jobs" :key="j"
                style="font-size:10px;padding:1px 6px;background:rgba(34,197,94,0.1);border-radius:3px;color:var(--el-success)">
                <i class="ph ph-play-circle"></i> {{ j }}
              </span>
            </div>
          </div>
          <div v-if="!filtered.length" style="color:var(--el-text-dim);text-align:center;padding:20px;font-size:13px">
            No plugins match your search.
          </div>
        </div>
      `,
    });
  }

  // Expose
  root.HortPlugins = {
    discoverAndLoadPlugins,
    getPlugins,
    registerPluginManager,
    renderAllThumbnails,
    getThumbnailUrl,
    startThumbnailLoop,
    getAutoShowPlugins,
  };

})(typeof globalThis !== 'undefined' ? globalThis : window);
