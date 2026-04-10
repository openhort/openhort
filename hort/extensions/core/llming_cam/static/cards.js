/* global HortExtension, Vue */

/**
 * LlmingCam — Camera card for the llming grid.
 * Shows available cameras with live preview thumbnails.
 */

(function () {
  'use strict';

  class LlmingCamPanel extends HortExtension {
    static type = 'llming-cam';
    static label = 'Cameras';
    static icon = 'ph ph-video-camera';

    setup(app, Quasar, options) {
      const ext = this;

      app.component('llming-cam-panel', {
        setup() {
          const cameras = Vue.ref([]);
          const loading = Vue.ref(false);

          async function refresh() {
            if (!window.hortWS) return;
            const msg = await window.hortWS.request({ type: 'sources.list', source_type: 'camera' });
            if (msg && msg.data) cameras.value = msg.data;
          }

          async function startCam(sourceId) {
            loading.value = true;
            if (window.hortWS) {
              // Use the llming-cam MCP tool via the llming wire
              const bp = HortExtension.basePath;
              try {
                const r = await fetch(bp + '/api/llmings/llming-cam/start?source_id=' + encodeURIComponent(sourceId), { method: 'POST' });
              } catch (e) {}
            }
            await refresh();
            loading.value = false;
          }

          Vue.onMounted(() => { refresh(); setInterval(refresh, 5000); });

          return { cameras, loading, refresh, startCam };
        },
        template: `
          <div data-plugin="llming-cam" style="max-width: 600px">
            <div style="padding: 12px">
              <div v-if="cameras.length === 0" style="color: var(--el-text-dim); text-align: center; padding: 20px">
                No cameras detected
              </div>
              <div v-for="cam in cameras" :key="cam.source_id"
                   style="display: flex; align-items: center; padding: 8px 0; border-bottom: 1px solid rgba(255,255,255,0.06)">
                <i class="ph ph-video-camera" style="font-size: 20px; color: var(--el-primary); margin-right: 10px"></i>
                <div style="flex: 1">
                  <div style="font-weight: 500">{{ cam.name }}</div>
                  <div style="font-size: 11px; color: var(--el-text-dim)">
                    {{ cam.metadata.active ? '🟢 Active' : '⚪ Idle' }}
                    <span v-if="cam.metadata.active"> — {{ cam.metadata.width }}×{{ cam.metadata.height }}@{{ Math.round(cam.metadata.fps || 0) }}fps</span>
                  </div>
                </div>
              </div>
            </div>
          </div>
        `,
      });
    }

    renderThumbnail(ctx, w, h) {
      // Dark background
      ctx.fillStyle = '#0e1621';
      ctx.fillRect(0, 0, w, h);

      // Camera icon
      ctx.fillStyle = '#3b82f6';
      ctx.font = '48px Phosphor';
      ctx.textAlign = 'center';
      ctx.textBaseline = 'middle';
      // Fallback: draw a simple camera shape
      const cx = w / 2, cy = h / 2 - 10;
      ctx.fillStyle = '#1e3a5f';
      ctx.beginPath();
      ctx.roundRect(cx - 40, cy - 25, 80, 50, 8);
      ctx.fill();
      ctx.fillStyle = '#3b82f6';
      ctx.beginPath();
      ctx.arc(cx, cy, 18, 0, Math.PI * 2);
      ctx.fill();
      ctx.fillStyle = '#0e1621';
      ctx.beginPath();
      ctx.arc(cx, cy, 10, 0, Math.PI * 2);
      ctx.fill();

      // Camera count
      const data = this._feedStore ? this._feedStore() : {};
      const total = data.total_cameras || 0;
      const active = data.active_cameras || 0;
      ctx.fillStyle = '#8899aa';
      ctx.font = '13px -apple-system, sans-serif';
      ctx.textAlign = 'center';
      ctx.textBaseline = 'bottom';
      ctx.fillText(total + ' camera' + (total !== 1 ? 's' : '') + (active ? ' (' + active + ' active)' : ''), w / 2, h - 10);
    }
  }

  if (typeof HortExtension !== 'undefined') {
    HortExtension.register(LlmingCamPanel);
  }
})();
