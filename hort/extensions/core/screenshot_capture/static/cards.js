/**
 * Screenshot Capture — gallery UI + capture button.
 *
 * Demonstrates SERVER→CLIENT image flow:
 * 1. User clicks "Capture" button
 * 2. Plugin backend captures screenshot, stores in file store
 * 3. JS fetches the image via the plugin's custom router endpoint
 * 4. Displays in an image gallery with thumbnails
 */
/* global LlmingClient, Vue */

(function () {
  'use strict';

  class ScreenshotCapturePanel extends LlmingClient {
    static id = 'screenshot-capture';
    static name = 'Screenshot Capture';
    static llmingTitle = 'Screenshots';
    static llmingIcon = 'ph ph-camera';
    static llmingDescription = 'Capture and browse remote screenshots';
    static llmingWidgets = ['screenshot-capture-panel'];

    setup(app) {
      app.component('screenshot-capture-panel', {
        setup() {
          const bp = LlmingClient.basePath;
          const screenshots = Vue.ref([]);
          const capturing = Vue.ref(false);
          const selected = Vue.ref(null);

          // The router is mounted at /api/llmings/screenshot-capture/ in production
          // In the debugger, routes are directly on the app
          function routerBase() {
            // Try debugger path first, then production
            return bp + '/api/llmings/screenshot-capture';
          }

          async function refresh() {
            try {
              let resp = await fetch(routerBase() + '/screenshots');
              if (!resp.ok) {
                // Debugger fallback: router mounted without prefix
                resp = await fetch(bp + '/screenshots');
              }
              if (resp.ok) screenshots.value = await resp.json();
            } catch {}
          }

          async function capture() {
            capturing.value = true;
            try {
              let resp = await fetch(routerBase() + '/capture', { method: 'POST' });
              if (!resp.ok) resp = await fetch(bp + '/capture', { method: 'POST' });
              await refresh();
            } finally {
              capturing.value = false;
            }
          }

          function imageUrl(filename) {
            return routerBase() + '/screenshots/' + filename;
          }

          function formatTime(ts) {
            return new Date(ts * 1000).toLocaleTimeString();
          }

          function formatSize(bytes) {
            if (bytes > 1024 * 1024) return (bytes / 1024 / 1024).toFixed(1) + ' MB';
            return (bytes / 1024).toFixed(0) + ' KB';
          }

          Vue.onMounted(() => { refresh(); setInterval(refresh, 10000); });

          return { screenshots, capturing, selected, capture, imageUrl, formatTime, formatSize };
        },
        template: `
          <div data-plugin="screenshot-capture" style="max-width: 800px">
            <!-- Controls -->
            <div style="display:flex;gap:8px;align-items:center;margin-bottom:16px">
              <button @click="capture" :disabled="capturing"
                style="padding:10px 20px;background:var(--el-primary);color:#fff;border:none;border-radius:8px;font-size:14px;cursor:pointer;display:flex;align-items:center;gap:6px">
                <i :class="capturing ? 'ph ph-spinner' : 'ph ph-camera'" :style="capturing ? 'animation:spin 1s linear infinite' : ''"></i>
                {{ capturing ? 'Capturing...' : 'Capture Screenshot' }}
              </button>
              <span style="font-size:12px;color:var(--el-text-dim)">{{ screenshots.length }} screenshots</span>
            </div>

            <!-- Selected image (full view) -->
            <div v-if="selected" style="margin-bottom:16px;position:relative">
              <img :src="imageUrl(selected.name)" style="width:100%;border-radius:8px;border:1px solid var(--el-border)">
              <button @click="selected = null"
                style="position:absolute;top:8px;right:8px;background:rgba(0,0,0,0.7);color:#fff;border:none;border-radius:50%;width:32px;height:32px;cursor:pointer;font-size:16px">
                <i class="ph ph-x"></i>
              </button>
              <div style="font-size:11px;color:var(--el-text-dim);margin-top:4px">
                {{ selected.name }} · {{ formatSize(selected.size) }} · {{ formatTime(selected.created) }}
              </div>
            </div>

            <!-- Thumbnail grid -->
            <div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(150px,1fr));gap:8px">
              <div v-for="s in screenshots" :key="s.name" @click="selected = s"
                style="cursor:pointer;border-radius:6px;border:1px solid var(--el-border);overflow:hidden;transition:border-color 0.15s"
                :style="{borderColor: selected?.name === s.name ? 'var(--el-primary)' : ''}">
                <img :src="imageUrl(s.name)" style="width:100%;height:100px;object-fit:cover;display:block">
                <div style="padding:4px 6px;font-size:10px;color:var(--el-text-dim);background:var(--el-surface)">
                  {{ formatTime(s.created) }} · {{ formatSize(s.size) }}
                </div>
              </div>
            </div>

            <div v-if="!screenshots.length" style="color:var(--el-text-dim);text-align:center;padding:30px">
              No screenshots yet. Click "Capture Screenshot" to take one.
            </div>
          </div>
        `,
      });
    }
  }

  LlmingClient.register(ScreenshotCapturePanel);
})();
