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

          async function setPolicy(sourceId, policy) {
            if (!window.hortWS) return;
            loading.value = { ...loading.value, [sourceId]: true };
            await window.hortWS.request({
              type: 'debug.call', llming: 'llming-cam', power: 'set_camera_policy',
              args: { source_id: sourceId, policy }
            });
            // Clear preview on off/auto
            if (policy !== 'on') {
              const p = { ...previews.value };
              delete p[sourceId];
              previews.value = p;
            } else {
              await new Promise(r => setTimeout(r, 1500));
            }
            await refresh();
            loading.value = { ...loading.value, [sourceId]: false };
          }

          // Preview uses a lightweight pull: one frame at a time, client-driven.
          // Same principle as the stream ACK flow — never push, never pile up.
          let _previewRunning = false;
          async function previewLoop() {
            _previewRunning = true;
            while (_previewRunning) {
              const activeCams = cameras.value.filter(c => c.metadata?.active);
              // Clear previews for stopped cameras
              for (const cam of cameras.value) {
                if (!cam.metadata?.active && previews.value[cam.source_id]) {
                  const p = { ...previews.value };
                  delete p[cam.source_id];
                  previews.value = p;
                }
              }
              if (!activeCams.length) {
                await new Promise(r => setTimeout(r, 500));
                continue;
              }
              // Fetch ONE frame per camera, sequentially. Client drives the pace —
              // next request only after current frame is received and rendered.
              for (const cam of activeCams) {
                if (!_previewRunning) break;
                try {
                  const msg = await window.hortWS.request({
                    type: 'debug.call', llming: 'llming-cam', power: 'capture_camera',
                    args: { source_id: cam.source_id }
                  });
                  if (msg?.result?.content) {
                    const img = msg.result.content.find(c => c.type === 'image');
                    if (img) {
                      previews.value = { ...previews.value, [cam.source_id]: 'data:' + img.mimeType + ';base64,' + img.data };
                    }
                  }
                } catch (e) { /* timeout or error — skip, retry next loop */ }
              }
              // Tiny yield to let the browser render before requesting next frame
              await new Promise(r => requestAnimationFrame(r));
            }
          }

          Vue.onMounted(() => {
            refresh();
            setInterval(refresh, 3000);
            previewLoop();
          });

          Vue.onUnmounted(() => {
            _previewRunning = false;
          });

          return { cameras, previews, loading, setPolicy };
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
                <div style="display:flex; border-radius:6px; overflow:hidden; border:1px solid rgba(255,255,255,0.1)">
                  <button v-for="p in ['off','auto','on']" :key="p"
                    @click.stop="setPolicy(cam.source_id, p)"
                    :disabled="loading[cam.source_id]"
                    :style="{
                      background: (cam.metadata?.policy || 'off') === p
                        ? (p === 'off' ? '#6b7280' : p === 'auto' ? '#3b82f6' : '#22c55e')
                        : 'transparent',
                      color: (cam.metadata?.policy || 'off') === p ? '#fff' : '#8899aa',
                      border: 'none', padding: '3px 8px', fontSize: '11px', fontWeight: 600,
                      cursor: 'pointer', textTransform: 'capitalize',
                      opacity: loading[cam.source_id] ? 0.5 : 1,
                    }">{{ p }}</button>
                </div>
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
