/* global LlmingClient, Vue */

/**
 * LlmingCam — Camera card for the llming grid.
 * Unified UI for native cameras AND browser cameras.
 * All cameras shown in same list with same controls.
 *
 * Uses cam.* WS commands (not debug.call).
 */

(function () {
  'use strict';

  class LlmingCamPanel extends LlmingClient {
    static id = 'llming-cam';
    static label = 'Cameras';
    static icon = 'ph ph-video-camera';
    static autoShow = true;
    static llmingWidgets = ['llming-cam-panel'];

    setup(app, Quasar, options) {
      // Reusable triple-toggle component
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
                  opacity: disabled ? 0.4 : 1, transition: 'all 0.15s',
                }">{{ o.label }}</button>
            </div>
          `,
        });
      }

      app.component('llming-cam-panel', {
        setup() {
          const cameras = Vue.ref([]);
          const previews = Vue.ref({});
          const loading = Vue.ref({});
          const hasBrowserCams = Vue.computed(() => cameras.value.some(c => c.metadata?.browser));

          async function refresh() {
            if (!window.hortWS) return;
            const msg = await window.hortWS.request({ type: 'cam.list' });
            if (msg?.cameras) cameras.value = msg.cameras;
          }

          function loadStoredThumbs() {
            for (const cam of cameras.value) {
              if (cam.thumb && !previews.value[cam.source_id]) {
                previews.value = { ...previews.value, [cam.source_id]: 'data:image/webp;base64,' + cam.thumb };
              }
            }
          }

          async function setPolicy(sourceId, policy) {
            if (!window.hortWS) return;
            loading.value = { ...loading.value, [sourceId]: true };
            await window.hortWS.request({ type: 'cam.policy', source_id: sourceId, policy });
            if (policy === 'off' || policy === 'auto') {
              const p = { ...previews.value }; delete p[sourceId]; previews.value = p;
            } else if (policy === 'on') {
              await new Promise(r => setTimeout(r, 1500));
            }
            await refresh();
            loading.value = { ...loading.value, [sourceId]: false };
          }

          // Grant browser camera permission and register devices
          async function grantBrowserAccess() {
            try {
              const devices = await navigator.mediaDevices.enumerateDevices();
              const hasLabels = devices.some(d => d.kind === 'videoinput' && d.label);
              if (!hasLabels) {
                const stream = await navigator.mediaDevices.getUserMedia({ video: true });
                stream.getTracks().forEach(t => t.stop());
              }
              await registerBrowserDevices();
              await refresh();
            } catch (e) {}
          }

          async function registerBrowserDevices() {
            const devices = await navigator.mediaDevices.enumerateDevices();
            const videoDevices = devices.filter(d => d.kind === 'videoinput' && d.label);
            if (!videoDevices.length) return;
            await window.hortWS.request({
              type: 'cam.register_browser',
              devices: videoDevices.map(d => ({ deviceId: d.deviceId, label: d.label }))
            });
            await refresh();
          }

          // Live preview loop — only captures from "on" + active cameras
          // Throttled: ~5fps max per camera, backs off on failure
          let _previewRunning = false;
          async function previewLoop() {
            _previewRunning = true;
            while (_previewRunning) {
              const onCams = cameras.value.filter(c => c.metadata?.active && c.metadata?.policy === 'on');
              for (const cam of cameras.value) {
                if (!cam.metadata?.active && !cam.thumb && previews.value[cam.source_id]) {
                  const p = { ...previews.value }; delete p[cam.source_id]; previews.value = p;
                }
              }
              if (!onCams.length) { await new Promise(r => setTimeout(r, 1000)); continue; }
              for (const cam of onCams) {
                if (!_previewRunning) break;
                try {
                  const msg = await window.hortWS.request({ type: 'cam.capture', source_id: cam.source_id });
                  if (msg?.content) {
                    const img = msg.content.find(c => c.type === 'image');
                    if (img) previews.value = { ...previews.value, [cam.source_id]: 'data:' + img.mimeType + ';base64,' + img.data };
                  }
                } catch (e) {}
              }
              // ~5fps: 200ms between capture rounds
              await new Promise(r => setTimeout(r, 200));
            }
          }

          Vue.onMounted(async () => {
            await refresh(); loadStoredThumbs();
            setInterval(async () => { await refresh(); loadStoredThumbs(); }, 3000);
            previewLoop();
          });
          Vue.onUnmounted(() => { _previewRunning = false; });

          return { cameras, previews, loading, setPolicy, hasBrowserCams, grantBrowserAccess };
        },
        template: `
          <div style="padding: 8px; overflow-y: auto; max-height: 100%">
            <div v-for="cam in cameras" :key="cam.source_id"
                 style="margin-bottom: 8px; border-radius: 8px; overflow: hidden; background: rgba(255,255,255,0.03); border: 1px solid rgba(255,255,255,0.06)">
              <div v-if="previews[cam.source_id]" style="position: relative; background: #000; max-height: 180px; overflow: hidden">
                <img :src="previews[cam.source_id]" @error="delete previews[cam.source_id]" :style="{
                  width: '100%', display: 'block', maxHeight: '180px', objectFit: 'contain',
                  opacity: cam.metadata?.active ? 1 : 0.5,
                  filter: cam.metadata?.active ? 'none' : 'grayscale(0.4) brightness(0.8)',
                }">
                <span v-if="cam.metadata?.active"
                  style="position:absolute; top:6px; left:6px; display:flex; align-items:center; gap:4px">
                  <span style="width:8px;height:8px;border-radius:50%;background:#ef4444"></span>
                  <span style="font-size:10px;color:#fff;text-shadow:0 1px 3px rgba(0,0,0,0.8)">LIVE</span>
                </span>
              </div>
              <div style="display: flex; align-items: center; padding: 8px 10px; gap: 8px">
                <i :class="cam.metadata?.browser ? 'ph ph-broadcast' : 'ph ph-video-camera'"
                   :style="{color: cam.metadata?.active ? 'var(--el-success)' : 'var(--el-text-dim)', fontSize: '18px'}"></i>
                <div style="flex: 1; min-width: 0">
                  <div style="font-size: 13px; font-weight: 500; white-space: nowrap; overflow: hidden; text-overflow: ellipsis">
                    {{ cam.name }}
                    <span v-if="cam.metadata?.browser" style="font-size:10px; color:var(--el-text-dim); margin-left:4px">(browser)</span>
                  </div>
                  <div style="font-size: 11px; color: var(--el-text-dim)">
                    <template v-if="cam.metadata?.active">{{ cam.metadata.width }}×{{ cam.metadata.height }} @ {{ Math.round(cam.metadata.fps || 0) }}fps</template>
                    <template v-else>Idle</template>
                  </div>
                </div>
                <hort-tri-toggle
                  :value="cam.metadata?.policy || 'off'"
                  :disabled="!!loading[cam.source_id]"
                  @change="setPolicy(cam.source_id, $event)" />
              </div>
            </div>

            <div v-if="!hasBrowserCams"
                 @click="grantBrowserAccess"
                 style="display:flex; align-items:center; justify-content:center; gap:6px; padding:10px; border-radius:8px; border:1px dashed rgba(255,255,255,0.15); cursor:pointer; color:var(--el-text-dim); font-size:12px; transition: border-color 0.15s; margin-top: 8px"
                 onmouseover="this.style.borderColor='var(--el-primary)'" onmouseout="this.style.borderColor='rgba(255,255,255,0.15)'">
              <i class="ph ph-broadcast" style="font-size:16px"></i> Enable Browser Cameras
            </div>

            <div v-if="!cameras.length" style="color: var(--el-text-dim); text-align: center; padding: 20px">
              No cameras detected
            </div>
          </div>
        `,
      });
    }

    async onConnect() {
      // Register browser camera devices and auto-start "on" cameras
      if (!window.hortWS || !window.hortCamera) return;
      try {
        const devices = await navigator.mediaDevices.enumerateDevices();
        const videoDevices = devices.filter(d => d.kind === 'videoinput' && d.label);
        if (videoDevices.length) {
          await window.hortWS.request({
            type: 'cam.register_browser',
            devices: videoDevices.map(d => ({ deviceId: d.deviceId, label: d.label }))
          });
        }
        const list = await window.hortWS.request({ type: 'cam.list' });
        if (list?.cameras) {
          for (const cam of list.cameras) {
            if (cam.metadata?.browser && cam.metadata?.policy === 'on' && !cam.metadata?.active) {
              window.hortCamera.startDevice(cam.source_id).catch(() => {});
            }
          }
        }
      } catch (e) {}
    }

    renderThumbnail(ctx, w, h) {
      ctx.fillStyle = '#0e1621';
      ctx.fillRect(0, 0, w, h);
      const data = this._feedStore ? this._feedStore() : {};
      const total = data.total_cameras || 0;
      const active = data.active_cameras || 0;
      const cx = w / 2, cy = h / 2 - 12;
      ctx.fillStyle = active > 0 ? '#22c55e' : '#1e3a5f';
      ctx.beginPath(); ctx.roundRect(cx - 35, cy - 20, 70, 40, 6); ctx.fill();
      ctx.fillStyle = active > 0 ? '#fff' : '#3b82f6';
      ctx.beginPath(); ctx.arc(cx, cy, 14, 0, Math.PI * 2); ctx.fill();
      ctx.fillStyle = '#0e1621';
      ctx.beginPath(); ctx.arc(cx, cy, 8, 0, Math.PI * 2); ctx.fill();
      if (active > 0) { ctx.fillStyle = '#ef4444'; ctx.beginPath(); ctx.arc(cx + 25, cy - 12, 4, 0, Math.PI * 2); ctx.fill(); }
      ctx.fillStyle = '#8899aa'; ctx.font = '12px -apple-system, sans-serif';
      ctx.textAlign = 'center'; ctx.textBaseline = 'bottom';
      ctx.fillText(active > 0 ? active + ' active / ' + total : total + ' camera' + (total !== 1 ? 's' : ''), w / 2, h - 8);
    }
  }

  if (typeof LlmingClient !== 'undefined') LlmingClient.register(LlmingCamPanel);
})();
