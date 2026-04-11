/**
 * Hue Bridge — UI card for Philips Hue light control.
 */
class HueBridgePanel extends LlmingClient {
  static id = 'hue-bridge';
  static name = 'HueBridge';
  static llmingTitle = 'Hue';
  static llmingIcon = 'ph ph-lamp';
  static llmingDescription = 'Philips Hue smart lights';
  static llmingWidgets = ['hue-bridge-panel'];
  static autoShow = true;

  _statusData = null;

  _feedStore(data) {
    this._statusData = data;
  }

  onConnect() {
    this.subscribe('hue_update', (data) => {
      if (data) this._statusData = data;
    });
    this.vaultRead('latest').then(data => {
      if (data && data.auth_state !== undefined) this._statusData = data;
    });
  }

  renderThumbnail(ctx, width, height) {
    const data = this._statusData;
    ctx.fillStyle = '#0f1724';
    ctx.fillRect(0, 0, width, height);

    if (!data || data.auth_state !== 'ok' || !data.lights) {
      ctx.fillStyle = '#4a5568';
      ctx.font = 'bold 36px system-ui';
      ctx.textAlign = 'center';
      ctx.fillText('\u{1F4A1}', width / 2, height / 2 - 10);
      ctx.font = '12px system-ui';
      ctx.fillStyle = data?.auth_state === 'pairing' ? '#fbbf24' : '#94a3b8';
      const msg = !data ? 'Not configured' :
        data.auth_state === 'pairing' ? 'Press link button...' :
        data.auth_state === 'error' ? 'Connection error' : 'Not connected';
      ctx.fillText(msg, width / 2, height / 2 + 20);
      return;
    }

    const lights = data.lights || [];
    const onCount = lights.filter(l => l.on).length;

    ctx.fillStyle = '#e0e0e0';
    ctx.font = 'bold 14px system-ui';
    ctx.textAlign = 'left';
    ctx.fillText(data.bridge_name || 'Hue Bridge', 12, 24);

    ctx.fillStyle = '#94a3b8';
    ctx.font = '11px system-ui';
    ctx.fillText(onCount + '/' + lights.length + ' lights on', 12, 42);

    const cols = Math.min(10, lights.length);
    const dotSize = 12;
    const gap = 4;
    lights.forEach((light, i) => {
      const x = 12 + (i % cols) * (dotSize + gap);
      const y = 56 + Math.floor(i / cols) * (dotSize + gap);
      ctx.beginPath();
      ctx.arc(x + dotSize / 2, y + dotSize / 2, dotSize / 2, 0, Math.PI * 2);
      if (light.on) {
        ctx.fillStyle = 'rgba(255, 200, 50, ' + Math.max(0.3, light.brightness / 254) + ')';
      } else {
        ctx.fillStyle = light.reachable ? '#2a3a5a' : '#1a1a2e';
      }
      ctx.fill();
    });
  }

  setup(app) {
    app.component('hue-bridge-panel', {
      template: `
        <div style="padding:16px;max-width:600px;height:100%;display:flex;flex-direction:column;overflow:hidden;box-sizing:border-box">
          <!-- CONNECTED: light list -->
          <template v-if="authState === 'ok'">
            <h3 style="margin:0 0 12px;font-size:16px;color:var(--el-text);flex-shrink:0">{{ bridgeName }}</h3>
            <div style="color:var(--el-text-dim);font-size:12px;margin-bottom:12px;flex-shrink:0">{{ lights.length }} lights, {{ onCount }} on</div>
            <div style="flex:1;overflow-y:auto;min-height:0">
              <div v-for="light in lights" :key="light.id"
                   style="display:flex;align-items:center;gap:12px;padding:8px 12px;background:var(--el-surface);border:1px solid var(--el-border);border-radius:8px;margin-bottom:6px">
                <div style="width:10px;height:10px;border-radius:50%"
                     :style="{background: light.on ? 'rgba(255,200,50,' + Math.max(0.4, light.brightness/254) + ')' : '#2a3a5a'}"></div>
                <span style="flex:1;font-size:13px">{{ light.name }}</span>
                <button :style="{background: light.on ? 'rgba(239,68,68,0.15)' : 'rgba(34,197,94,0.15)', border: '1px solid ' + (light.on ? 'rgba(239,68,68,0.4)' : 'rgba(34,197,94,0.4)'), color: light.on ? '#ef4444' : '#22c55e', borderRadius: '6px', padding: '4px 10px', fontSize: '12px', cursor: 'pointer'}"
                        @click="toggle(light)">{{ light.on ? 'Off' : 'On' }}</button>
              </div>
            </div>
            <!-- Sensors -->
            <div v-if="sensors.length" style="flex-shrink:0;margin-top:16px;border-top:1px solid var(--el-border);padding-top:12px">
              <div style="color:var(--el-text-dim);font-size:12px;margin-bottom:8px">Motion Sensors</div>
            </div>
            <div v-if="sensors.length" style="flex:0 1 auto;overflow-y:auto;min-height:0">
              <div v-for="s in sensors" :key="s.id"
                   style="display:flex;align-items:center;gap:10px;padding:6px 12px;background:var(--el-surface);border:1px solid var(--el-border);border-radius:8px;margin-bottom:6px;font-size:12px">
                <i class="ph" :class="s.presence ? 'ph-fill ph-person-simple-walk' : 'ph ph-person-simple-walk'"
                   :style="{fontSize:'16px', color: s.presence ? '#22c55e' : 'var(--el-text-dim)'}"></i>
                <div style="flex:1;min-width:0">
                  <div style="font-size:13px">{{ s.name }}</div>
                  <div style="font-size:10px;color:var(--el-text-dim)">
                    <span :style="{color: s.presence ? '#22c55e' : sensorAgo(s) < 300 ? '#fbbf24' : 'var(--el-text-dim)'}">
                      {{ s.presence ? 'Motion now' : sensorAgoText(s) }}
                    </span>
                  </div>
                </div>
                <span v-if="s.temperature != null" style="color:var(--el-text-dim);white-space:nowrap">{{ s.temperature }}\u00b0C</span>
                <span v-if="s.battery != null" style="color:var(--el-text-dim);white-space:nowrap"><i class="ph ph-battery-medium"></i> {{ s.battery }}%</span>
              </div>
            </div>
          </template>

          <!-- NOT CONNECTED: discovery + pairing -->
          <template v-else>
            <div style="text-align:center;padding:20px 0 16px">
              <i class="ph ph-lamp" style="font-size:48px;color:var(--el-text-dim)"></i>
              <div style="font-size:16px;margin:12px 0;color:var(--el-text)">Connect to Hue Bridge</div>
              <div v-if="discovering" style="color:var(--el-text-dim);font-size:13px">
                <i class="ph ph-spinner" style="animation:spin 1s linear infinite"></i> Scanning network...
              </div>
            </div>

            <!-- Discovered bridges -->
            <div v-if="bridges.length" style="margin-bottom:16px">
              <div style="font-size:12px;color:var(--el-text-dim);margin-bottom:8px">Bridges found on your network:</div>
              <div v-for="b in bridges" :key="b.ip"
                   style="display:flex;align-items:center;gap:12px;padding:10px 14px;background:var(--el-surface);border:1px solid var(--el-border);border-radius:8px;margin-bottom:6px">
                <i class="ph ph-wifi-high" style="font-size:18px;color:#66bb6a"></i>
                <div style="flex:1">
                  <div style="font-size:13px;color:var(--el-text)">{{ b.name || 'Hue Bridge' }}</div>
                  <div style="font-size:11px;color:var(--el-text-dim)">{{ b.ip }}</div>
                </div>
                <div v-if="b.pairing" style="font-size:11px;color:#fbbf24;text-align:right">
                  <div>Press link button</div>
                  <div style="font-size:10px;opacity:0.7">then click Pair again</div>
                </div>
                <button style="padding:6px 16px;background:var(--el-primary);color:#fff;border:none;border-radius:6px;font-size:12px;cursor:pointer"
                        @click="pair(b)">{{ b.pairing ? 'Pair' : 'Pair' }}</button>
              </div>
            </div>

            <!-- No bridges found -->
            <div v-if="!discovering && !bridges.length" style="text-align:center;color:var(--el-text-dim);font-size:13px;margin-bottom:16px">
              No bridges found.
              <a href="#" @click.prevent="discover" style="color:var(--el-primary)">Retry</a>
            </div>

            <!-- Manual entry -->
            <div style="border-top:1px solid var(--el-border);padding-top:14px;margin-top:8px">
              <div style="font-size:12px;color:var(--el-text-dim);margin-bottom:8px">Or enter credentials manually:</div>
              <div style="display:flex;gap:6px;align-items:flex-end">
                <div style="flex:1">
                  <input v-model="manualIp" placeholder="Bridge IP"
                         style="width:100%;padding:7px 10px;background:var(--el-surface);color:var(--el-text);border:1px solid var(--el-border);border-radius:6px;font-size:12px;box-sizing:border-box">
                </div>
                <div style="flex:1">
                  <input v-model="manualKey" placeholder="API Key"
                         style="width:100%;padding:7px 10px;background:var(--el-surface);color:var(--el-text);border:1px solid var(--el-border);border-radius:6px;font-size:12px;box-sizing:border-box">
                </div>
                <button style="padding:7px 14px;background:var(--el-primary);color:#fff;border:none;border-radius:6px;font-size:12px;cursor:pointer;white-space:nowrap"
                        @click="saveManual" :disabled="!manualIp || !manualKey">Save</button>
              </div>
            </div>

            <div v-if="statusMsg" style="margin-top:10px;font-size:12px;text-align:center" :style="{color: statusError ? 'var(--el-danger)' : '#66bb6a'}">{{ statusMsg }}</div>
          </template>
        </div>
      `,
      setup() {
        const authState = Vue.ref('not_configured');
        const bridgeName = Vue.ref('');
        const lights = Vue.ref([]);
        const sensors = Vue.ref([]);
        const onCount = Vue.computed(() => lights.value.filter(l => l.on).length);
        const bridges = Vue.ref([]);
        const discovering = Vue.ref(false);
        const manualIp = Vue.ref('');
        const manualKey = Vue.ref('');
        const statusMsg = Vue.ref('');
        const statusError = Vue.ref(false);

        function refresh() {
          const inst = LlmingClient.get('hue-bridge');
          const data = inst?._statusData;
          if (data) {
            authState.value = data.auth_state || 'not_configured';
            bridgeName.value = data.bridge_name || 'Hue Bridge';
            lights.value = data.lights || [];
            sensors.value = data.sensors || [];
          }
        }

        async function callTool(power, args) {
          if (!window.hortWS) return null;
          return await window.hortWS.request({
            type: 'llmings.execute_power',
            name: 'hue-bridge',
            power: power,
            args: args || {},
          });
        }

        async function discover() {
          discovering.value = true;
          bridges.value = [];
          statusMsg.value = '';
          const r = await callTool('discover_bridge');
          discovering.value = false;
          const result = r?.result || {};
          if (result.bridges) {
            bridges.value = result.bridges.map(b => ({ ...b, pairing: false }));
          }
          if (result.authenticated) {
            setTimeout(refresh, 500);
            return;
          }
          if (result.is_error) {
            statusMsg.value = result.content?.[0]?.text || 'Discovery failed';
            statusError.value = true;
          }
          refresh();
        }

        async function pair(bridge) {
          bridge.pairing = true;
          statusMsg.value = '';
          const r = await callTool('pair_bridge', { bridge_ip: bridge.ip });
          const text = r?.result?.content?.[0]?.text || '';
          if (r?.result?.is_error) {
            // Still need button press — keep pairing state
            statusMsg.value = 'Press the link button on your bridge, then click Pair again.';
            statusError.value = false;
          } else {
            statusMsg.value = text;
            statusError.value = false;
            bridge.pairing = false;
          }
          setTimeout(refresh, 1000);
        }

        async function saveManual() {
          if (!manualIp.value || !manualKey.value) return;
          const r = await callTool('set_api_key', { bridge_ip: manualIp.value, api_key: manualKey.value });
          const text = r?.result?.content?.[0]?.text || '';
          statusMsg.value = text;
          statusError.value = !!r?.result?.is_error;
          setTimeout(refresh, 1000);
        }

        async function toggle(light) {
          await callTool('set_light', { light_id: light.id, on: !light.on });
          setTimeout(refresh, 500);
        }

        function sensorAgo(s) {
          if (!s.last_updated || s.last_updated === 'none') return Infinity;
          try {
            const t = new Date(s.last_updated + 'Z').getTime();
            return Math.max(0, Math.floor((Date.now() - t) / 1000));
          } catch { return Infinity; }
        }

        function sensorAgoText(s) {
          const sec = sensorAgo(s);
          if (sec === Infinity) return 'no data';
          if (sec < 60) return 'Last motion ' + sec + 's ago';
          if (sec < 3600) return 'Last motion ' + Math.floor(sec / 60) + 'm ago';
          if (sec < 86400) return 'Last motion ' + Math.floor(sec / 3600) + 'h ago';
          return 'Last motion ' + Math.floor(sec / 86400) + 'd ago';
        }

        // Auto-discover on mount
        Vue.onMounted(() => {
          refresh();
          setInterval(refresh, 5000);
          if (authState.value !== 'ok') discover();
        });

        return { authState, bridgeName, lights, sensors, onCount, sensorAgo, sensorAgoText,
                 bridges, discovering, manualIp, manualKey, statusMsg, statusError,
                 discover, pair, saveManual, toggle };
      },
    });
  }
}

LlmingClient.register(HueBridgePanel);
