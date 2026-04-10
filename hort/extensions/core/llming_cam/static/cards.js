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
      // Reusable triple-toggle component (Off / Auto / On)
      if (!app._context.components['hort-tri-toggle']) {
        app.component('hort-tri-toggle', {
          props: {
            value: { type: String, default: 'off' },
            options: { type: Array, default: () => [
              { key: 'off', label: 'Off', color: '#ef4444' },
              { key: 'auto', label: 'Auto', color: '#f59e0b' },
              { key: 'on', label: 'On', color: '#22c55e' },
            ]},
            disabled: { type: Boolean, default: false },
          },
          emits: ['change'],
          template: `
            <div style="display:inline-flex; border-radius:6px; overflow:hidden; border:1px solid rgba(255,255,255,0.12); background:rgba(0,0,0,0.2)">
              <button v-for="o in options" :key="o.key"
                @click.stop="!disabled && $emit('change', o.key)"
                :style="{
                  background: value === o.key ? o.color : 'transparent',
                  color: value === o.key ? '#fff' : '#667',
                  border: 'none', padding: '4px 10px', fontSize: '11px', fontWeight: 600,
                  cursor: disabled ? 'default' : 'pointer',
                  opacity: disabled ? 0.4 : 1,
                  transition: 'all 0.15s',
                }">{{ o.label }}</button>
            </div>
          `,
        });
      }

      app.component('llming-cam-panel', {
        setup() {
          const cameras = Vue.ref([]);
          const previews = Vue.ref({});  // source_id → base64 data URL
          const loading = Vue.ref({});
          let previewTimer = null;

          async function refresh() {
            if (!window.hortWS) return;
            // Query llming-cam directly — it owns the CameraProvider with correct state
            const msg = await window.hortWS.request({
              type: 'debug.call', llming: 'llming-cam', power: 'list_cameras_detailed'
            });
            if (msg?.result?.cameras) cameras.value = msg.result.cameras;
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

          // Load stored thumbnails for inactive cameras on refresh
          function loadStoredThumbs() {
            for (const cam of cameras.value) {
              if (cam.thumb && !previews.value[cam.source_id]) {
                previews.value = { ...previews.value, [cam.source_id]: 'data:image/webp;base64,' + cam.thumb };
              }
            }
          }

          // Live preview: client-driven pull, one frame at a time
          let _previewRunning = false;
          async function previewLoop() {
            _previewRunning = true;
            while (_previewRunning) {
              const activeCams = cameras.value.filter(c => c.metadata?.active);
              if (!activeCams.length) {
                await new Promise(r => setTimeout(r, 500));
                continue;
              }
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
                } catch (e) {}
              }
              await new Promise(r => requestAnimationFrame(r));
            }
          }

          const browserCamActive = Vue.ref(false);
          const browserDevices = Vue.ref([]);

          async function shareBrowserCam(deviceId) {
            if (!window.hortCamera) return;
            if (browserCamActive.value) {
              window.hortCamera.stop();
              browserCamActive.value = false;
            } else {
              const sid = await window.hortCamera.start(deviceId);
              browserCamActive.value = !!sid;
            }
            await refresh();
          }

          async function loadBrowserDevices() {
            if (window.hortCamera) {
              browserDevices.value = await window.hortCamera.listDevices();
            }
          }

          Vue.onMounted(async () => {
            await refresh();
            loadStoredThumbs();
            loadBrowserDevices();
            setInterval(async () => { await refresh(); loadStoredThumbs(); }, 3000);
            previewLoop();
          });

          Vue.onUnmounted(() => {
            _previewRunning = false;
          });

          return { cameras, previews, loading, setPolicy, browserCamActive, browserDevices, shareBrowserCam };
        },
        template: `
          <div style="padding: 8px">
            <!-- Share browser camera -->
            <div v-if="browserDevices.length" style="margin-bottom: 8px; padding: 8px; border-radius: 8px; background: rgba(59,130,246,0.08); border: 1px solid rgba(59,130,246,0.2)">
              <div style="display:flex; align-items:center; gap:8px">
                <i class="ph ph-broadcast" style="font-size:18px; color:var(--el-primary)"></i>
                <span style="flex:1; font-size:12px; font-weight:500">Share Browser Camera</span>
                <button @click="shareBrowserCam()" :style="{
                  background: browserCamActive ? 'var(--el-danger, #ef4444)' : 'var(--el-primary, #3b82f6)',
                  color: '#fff', border: 'none', borderRadius: '6px', padding: '4px 12px',
                  fontSize: '11px', fontWeight: 600, cursor: 'pointer',
                }">{{ browserCamActive ? 'Stop Sharing' : 'Share' }}</button>
              </div>
            </div>
            <div v-if="cameras.length === 0 && !browserDevices.length" style="color: var(--el-text-dim); text-align: center; padding: 20px">
              No cameras detected
            </div>
            <div v-for="cam in cameras" :key="cam.source_id"
                 style="margin-bottom: 8px; border-radius: 8px; overflow: hidden; background: rgba(255,255,255,0.03); border: 1px solid rgba(255,255,255,0.06)">
              <!-- Preview image (live when active, last-known when off/auto) -->
              <div v-if="previews[cam.source_id]" style="position: relative; background: #000">
                <img :src="previews[cam.source_id]" :style="{
                  width: '100%', display: 'block', maxHeight: '200px', objectFit: 'contain',
                  opacity: cam.metadata?.active ? 1 : 0.5, filter: cam.metadata?.active ? 'none' : 'grayscale(0.5)',
                }">
                <span v-if="!cam.metadata?.active && (cam.metadata?.policy === 'auto')"
                  style="position:absolute; top:6px; right:6px; background:rgba(245,158,11,0.85); color:#fff; padding:2px 6px; border-radius:4px; font-size:10px; font-weight:600">
                  auto
                </span>
                <span v-if="cam.metadata?.active"
                  style="position:absolute; top:6px; left:6px; display:flex; align-items:center; gap:4px">
                  <span style="width:8px;height:8px;border-radius:50%;background:#ef4444;animation:pulse 1.5s infinite"></span>
                  <span style="font-size:10px;color:#fff;text-shadow:0 1px 3px rgba(0,0,0,0.8)">LIVE</span>
                </span>
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
                <hort-tri-toggle
                  :value="cam.metadata?.policy || 'off'"
                  :disabled="!!loading[cam.source_id]"
                  @change="setPolicy(cam.source_id, $event)"
                />
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
      const cams = data.cameras || [];

      // Try to show camera icon
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
