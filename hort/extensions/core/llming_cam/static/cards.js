/* global HortExtension, Vue */

/**
 * LlmingCam — Camera card for the llming grid.
 * Shows available cameras with live preview thumbnails.
 * Click toggle to start/stop capture, preview updates live.
 */

(function () {
  'use strict';

  class LlmingCamPanel extends HortExtension {
    static id = 'llming-cam';
    static label = 'Cameras';
    static icon = 'ph ph-video-camera';
    static autoShow = true;
    static llmingWidgets = ['llming-cam-panel'];

    setup(app, Quasar, options) {
      app.component('llming-cam-panel', {
        setup() {
          const cameras = Vue.ref([]);
          const previews = Vue.ref({});  // source_id → base64 data URL
          const loading = Vue.ref({});
          let previewTimer = null;

          async function refresh() {
            if (!window.hortWS) return;
            const msg = await window.hortWS.request({ type: 'sources.list', source_type: 'camera' });
            if (msg && msg.data) cameras.value = msg.data;
          }

          async function toggleCam(sourceId) {
            if (!window.hortWS) return;
            loading.value = { ...loading.value, [sourceId]: true };
            const cam = cameras.value.find(c => c.source_id === sourceId);
            const isActive = cam && cam.metadata && cam.metadata.active;
            const power = isActive ? 'stop_camera' : 'start_camera';
            await window.hortWS.request({
              type: 'debug.call', llming: 'llming-cam', power, args: { source_id: sourceId }
            });
            // Wait briefly for camera to start
            if (!isActive) await new Promise(r => setTimeout(r, 1500));
            await refresh();
            loading.value = { ...loading.value, [sourceId]: false };
          }

          async function refreshPreviews() {
            for (const cam of cameras.value) {
              if (!cam.metadata || !cam.metadata.active) continue;
              const msg = await window.hortWS.request({
                type: 'debug.call', llming: 'llming-cam', power: 'capture_camera',
                args: { source_id: cam.source_id }
              });
              if (msg && msg.result && msg.result.content) {
                const img = msg.result.content.find(c => c.type === 'image');
                if (img) {
                  previews.value = { ...previews.value, [cam.source_id]: 'data:' + img.mimeType + ';base64,' + img.data };
                }
              }
            }
          }

          Vue.onMounted(() => {
            refresh();
            setInterval(refresh, 3000);
            previewTimer = setInterval(refreshPreviews, 2000);
          });

          Vue.onUnmounted(() => {
            if (previewTimer) clearInterval(previewTimer);
          });

          return { cameras, previews, loading, toggleCam };
        },
        template: `
          <div style="padding: 8px">
            <div v-if="cameras.length === 0" style="color: var(--el-text-dim); text-align: center; padding: 20px">
              No cameras detected
            </div>
            <div v-for="cam in cameras" :key="cam.source_id"
                 style="margin-bottom: 8px; border-radius: 8px; overflow: hidden; background: rgba(255,255,255,0.03); border: 1px solid rgba(255,255,255,0.06)">
              <!-- Preview image (when active) -->
              <div v-if="previews[cam.source_id]" style="position: relative; background: #000">
                <img :src="previews[cam.source_id]" style="width: 100%; display: block; max-height: 200px; object-fit: contain">
              </div>
              <!-- Camera info row -->
              <div style="display: flex; align-items: center; padding: 8px 10px; gap: 8px">
                <i class="ph ph-video-camera" :style="{color: cam.metadata?.active ? 'var(--el-success)' : 'var(--el-text-dim)', fontSize: '18px'}"></i>
                <div style="flex: 1; min-width: 0">
                  <div style="font-size: 13px; font-weight: 500; white-space: nowrap; overflow: hidden; text-overflow: ellipsis">{{ cam.name }}</div>
                  <div style="font-size: 11px; color: var(--el-text-dim)">
                    <template v-if="cam.metadata?.active">
                      {{ cam.metadata.width }}×{{ cam.metadata.height }} @ {{ Math.round(cam.metadata.fps || 0) }}fps
                    </template>
                    <template v-else>Idle</template>
                  </div>
                </div>
                <button @click.stop="toggleCam(cam.source_id)"
                        :disabled="loading[cam.source_id]"
                        :style="{
                          background: cam.metadata?.active ? 'var(--el-danger, #ef4444)' : 'var(--el-success, #22c55e)',
                          color: '#fff', border: 'none', borderRadius: '6px', padding: '4px 12px',
                          fontSize: '12px', fontWeight: 600, cursor: 'pointer', opacity: loading[cam.source_id] ? 0.5 : 1
                        }">
                  {{ loading[cam.source_id] ? '...' : (cam.metadata?.active ? 'Stop' : 'Start') }}
                </button>
              </div>
            </div>
          </div>
        `,
      });
    }

    renderThumbnail(ctx, w, h) {
      ctx.fillStyle = '#0e1621';
      ctx.fillRect(0, 0, w, h);
      const data = this._feedStore ? this._feedStore() : {};
      const total = data.total_cameras || 0;
      const active = data.active_cameras || 0;

      // Camera icon
      const cx = w / 2, cy = h / 2 - 12;
      ctx.fillStyle = active > 0 ? '#22c55e' : '#1e3a5f';
      ctx.beginPath();
      ctx.roundRect(cx - 35, cy - 20, 70, 40, 6);
      ctx.fill();
      ctx.fillStyle = active > 0 ? '#fff' : '#3b82f6';
      ctx.beginPath();
      ctx.arc(cx, cy, 14, 0, Math.PI * 2);
      ctx.fill();
      ctx.fillStyle = '#0e1621';
      ctx.beginPath();
      ctx.arc(cx, cy, 8, 0, Math.PI * 2);
      ctx.fill();
      if (active > 0) {
        // Recording dot
        ctx.fillStyle = '#ef4444';
        ctx.beginPath();
        ctx.arc(cx + 25, cy - 12, 4, 0, Math.PI * 2);
        ctx.fill();
      }

      // Label
      ctx.fillStyle = '#8899aa';
      ctx.font = '12px -apple-system, sans-serif';
      ctx.textAlign = 'center';
      ctx.textBaseline = 'bottom';
      const label = active > 0
        ? active + ' active / ' + total
        : total + ' camera' + (total !== 1 ? 's' : '');
      ctx.fillText(label, w / 2, h - 8);
    }
  }

  if (typeof HortExtension !== 'undefined') {
    HortExtension.register(LlmingCamPanel);
  }
})();
