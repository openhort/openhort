/**
 * Camera Scan — phone camera capture + server-side analysis.
 *
 * Demonstrates CLIENT→SERVER image flow:
 * 1. User taps "Open Camera" — browser requests camera access via getUserMedia()
 * 2. Live viewfinder shown in a <video> element
 * 3. User taps "Capture" — frame grabbed as JPEG, converted to base64
 * 4. Base64 sent to server: POST /scan {image: "<base64>", mime_type: "image/jpeg"}
 * 5. Server analyzes (dimensions, color, QR codes) and returns result
 * 6. Result displayed below the viewfinder
 *
 * Also supports file input as fallback (for desktop browsers or when camera unavailable).
 */
/* global HortExtension, Vue */

(function () {
  'use strict';

  class CameraScanPanel extends HortExtension {
    static id = 'camera-scan';
    static name = 'Camera Scan';
    static llmingTitle = 'Camera Scanner';
    static llmingIcon = 'ph ph-qr-code';
    static llmingDescription = 'Scan QR codes and analyze photos';

    setup(app) {
      app.component('camera-scan-panel', {
        setup() {
          const bp = HortExtension.basePath;
          const videoRef = Vue.ref(null);
          const canvasRef = Vue.ref(null);
          const cameraActive = Vue.ref(false);
          const analyzing = Vue.ref(false);
          const result = Vue.ref(null);
          const recentScans = Vue.ref([]);
          const error = Vue.ref('');
          let stream = null;

          function routerBase() {
            return bp + '/api/plugins/camera-scan';
          }

          async function startCamera() {
            error.value = '';
            try {
              stream = await navigator.mediaDevices.getUserMedia({
                video: { facingMode: 'environment', width: { ideal: 1280 }, height: { ideal: 720 } }
              });
              cameraActive.value = true;
              Vue.nextTick(() => {
                if (videoRef.value) {
                  videoRef.value.srcObject = stream;
                  videoRef.value.play();
                }
              });
            } catch (e) {
              error.value = 'Camera access denied or not available. Use file upload instead.';
            }
          }

          function stopCamera() {
            if (stream) {
              stream.getTracks().forEach(t => t.stop());
              stream = null;
            }
            cameraActive.value = false;
          }

          async function captureAndScan() {
            if (!videoRef.value || !canvasRef.value) return;
            analyzing.value = true;
            error.value = '';

            try {
              const video = videoRef.value;
              const canvas = canvasRef.value;
              canvas.width = video.videoWidth;
              canvas.height = video.videoHeight;
              canvas.getContext('2d').drawImage(video, 0, 0);

              // Convert to JPEG base64
              const dataUrl = canvas.toDataURL('image/jpeg', 0.85);
              const b64 = dataUrl.split(',')[1];

              await sendToServer(b64, 'image/jpeg');
            } catch (e) {
              error.value = 'Capture failed: ' + e.message;
            } finally {
              analyzing.value = false;
            }
          }

          async function handleFileUpload(event) {
            const file = event.target.files[0];
            if (!file) return;
            analyzing.value = true;
            error.value = '';

            try {
              const buffer = await file.arrayBuffer();
              const b64 = btoa(String.fromCharCode(...new Uint8Array(buffer)));
              await sendToServer(b64, file.type || 'image/jpeg');
            } catch (e) {
              error.value = 'Upload failed: ' + e.message;
            } finally {
              analyzing.value = false;
            }
          }

          async function sendToServer(imageB64, mimeType) {
            let resp = await fetch(routerBase() + '/scan', {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({ image: imageB64, mime_type: mimeType }),
            });
            if (!resp.ok) {
              // Debugger fallback
              resp = await fetch(bp + '/scan', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ image: imageB64, mime_type: mimeType }),
              });
            }
            if (resp.ok) {
              result.value = await resp.json();
              await loadRecentScans();
            } else {
              error.value = 'Server error: ' + resp.status;
            }
          }

          async function loadRecentScans() {
            try {
              let resp = await fetch(routerBase() + '/scans');
              if (!resp.ok) resp = await fetch(bp + '/scans');
              if (resp.ok) recentScans.value = await resp.json();
            } catch {}
          }

          Vue.onMounted(loadRecentScans);
          Vue.onUnmounted(stopCamera);

          return {
            videoRef, canvasRef, cameraActive, analyzing, result, recentScans, error,
            startCamera, stopCamera, captureAndScan, handleFileUpload,
          };
        },
        template: `
          <div data-plugin="camera-scan" style="max-width: 600px">
            <!-- Controls -->
            <div style="display:flex;gap:8px;margin-bottom:16px;flex-wrap:wrap">
              <button v-if="!cameraActive" @click="startCamera"
                style="padding:10px 16px;background:var(--el-primary);color:#fff;border:none;border-radius:8px;font-size:13px;cursor:pointer;display:flex;align-items:center;gap:6px">
                <i class="ph ph-camera"></i> Open Camera
              </button>
              <button v-if="cameraActive" @click="captureAndScan" :disabled="analyzing"
                style="padding:10px 16px;background:var(--el-success);color:#fff;border:none;border-radius:8px;font-size:13px;cursor:pointer;display:flex;align-items:center;gap:6px">
                <i :class="analyzing ? 'ph ph-spinner' : 'ph ph-scan'" :style="analyzing ? 'animation:spin 1s linear infinite' : ''"></i>
                {{ analyzing ? 'Analyzing...' : 'Capture & Scan' }}
              </button>
              <button v-if="cameraActive" @click="stopCamera"
                style="padding:10px 16px;background:var(--el-border);color:var(--el-text-dim);border:none;border-radius:8px;font-size:13px;cursor:pointer">
                <i class="ph ph-stop"></i> Stop Camera
              </button>
              <label style="padding:10px 16px;background:var(--el-surface-elevated);color:var(--el-text);border:1px solid var(--el-border);border-radius:8px;font-size:13px;cursor:pointer;display:flex;align-items:center;gap:6px">
                <i class="ph ph-upload-simple"></i> Upload Image
                <input type="file" accept="image/*" capture="environment" @change="handleFileUpload" style="display:none">
              </label>
            </div>

            <!-- Error -->
            <div v-if="error" style="color:var(--el-danger);font-size:12px;margin-bottom:12px;padding:8px;background:rgba(239,68,68,0.1);border-radius:6px">
              <i class="ph ph-warning"></i> {{ error }}
            </div>

            <!-- Camera viewfinder -->
            <div v-if="cameraActive" style="margin-bottom:16px;border-radius:8px;overflow:hidden;border:2px solid var(--el-primary);position:relative">
              <video ref="videoRef" autoplay playsinline muted style="width:100%;display:block"></video>
              <div style="position:absolute;inset:0;border:2px dashed rgba(59,130,246,0.3);pointer-events:none;margin:20%"></div>
            </div>
            <canvas ref="canvasRef" style="display:none"></canvas>

            <!-- Analysis result -->
            <div v-if="result" style="background:var(--el-surface);border:1px solid var(--el-border);border-radius:8px;padding:12px;margin-bottom:16px">
              <div style="font-size:13px;font-weight:600;margin-bottom:8px;display:flex;align-items:center;gap:6px">
                <i class="ph ph-check-circle" style="color:var(--el-success)"></i> Analysis Result
              </div>
              <div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(140px,1fr));gap:8px">
                <div v-if="result.width">
                  <div style="font-size:10px;color:var(--el-text-dim)">Dimensions</div>
                  <div style="font-size:14px;font-weight:600">{{ result.width }} × {{ result.height }}</div>
                </div>
                <div v-if="result.format">
                  <div style="font-size:10px;color:var(--el-text-dim)">Format</div>
                  <div style="font-size:14px;font-weight:600">{{ result.format }}</div>
                </div>
                <div v-if="result.size_bytes">
                  <div style="font-size:10px;color:var(--el-text-dim)">Size</div>
                  <div style="font-size:14px;font-weight:600">{{ (result.size_bytes / 1024).toFixed(0) }} KB</div>
                </div>
                <div v-if="result.avg_color">
                  <div style="font-size:10px;color:var(--el-text-dim)">Avg Color</div>
                  <div style="display:flex;align-items:center;gap:6px">
                    <span style="width:20px;height:20px;border-radius:4px;display:inline-block;border:1px solid var(--el-border)"
                          :style="{background: result.avg_color}"></span>
                    <span style="font-size:12px;font-family:monospace">{{ result.avg_color }}</span>
                  </div>
                </div>
                <div v-if="result.brightness !== undefined">
                  <div style="font-size:10px;color:var(--el-text-dim)">Brightness</div>
                  <div style="font-size:14px;font-weight:600">{{ result.brightness }} <span style="font-size:11px;color:var(--el-text-dim)">{{ result.is_dark ? '(dark)' : '(light)' }}</span></div>
                </div>
              </div>
              <!-- QR codes -->
              <div v-if="result.qr_codes && result.qr_codes.length" style="margin-top:12px;padding-top:12px;border-top:1px solid var(--el-border)">
                <div style="font-size:12px;font-weight:600;color:var(--el-success);margin-bottom:6px"><i class="ph ph-qr-code"></i> QR/Barcode Detected!</div>
                <div v-for="qr in result.qr_codes" :key="qr.data" style="font-size:13px;padding:6px;background:var(--el-bg);border-radius:4px;margin:4px 0;font-family:monospace;word-break:break-all">
                  [{{ qr.type }}] {{ qr.data }}
                </div>
              </div>
              <div v-if="result.qr_detection" style="margin-top:8px;font-size:11px;color:var(--el-text-dim)">
                <i class="ph ph-info"></i> {{ result.qr_detection }}
              </div>
            </div>

            <!-- Recent scans -->
            <div v-if="recentScans.length" style="margin-top:16px">
              <div style="font-size:12px;color:var(--el-text-dim);margin-bottom:6px">Recent Scans</div>
              <div v-for="s in recentScans" :key="s.key"
                style="font-size:12px;padding:6px 8px;border-bottom:1px solid rgba(255,255,255,0.03);display:flex;gap:12px">
                <span>{{ s.width }}×{{ s.height }}</span>
                <span>{{ s.format }}</span>
                <span style="color:var(--el-text-dim)">{{ (s.size_bytes / 1024).toFixed(0) }} KB</span>
                <span v-if="s.avg_color" style="display:inline-flex;align-items:center;gap:4px">
                  <span style="width:10px;height:10px;border-radius:2px;display:inline-block" :style="{background: s.avg_color}"></span>
                  {{ s.avg_color }}
                </span>
              </div>
            </div>
          </div>
        `,
      });
    }
  }

  HortExtension.register(CameraScanPanel);
})();
