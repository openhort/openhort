/* Cloud Connector — panel UI extension with token-based QR access */
/* global HortExtension, Vue */

(function () {
  'use strict';

  class CloudConnector extends HortExtension {
    static id = 'cloud-connector';
    static name = 'Cloud';
    static connectorIcon = 'ph ph-cloud';

    setup(app) {
      app.component('cloud-connector-panel', {
        props: ['connectors'],
        emits: ['close', 'save'],
        setup(props, { emit }) {
          const { ref, reactive, computed, onMounted } = Vue;
          const bp = HortExtension.basePath;

          const config = reactive({ server: '', key: '' });
          const loading = ref(false);
          const showKey = ref(false);
          const tab = ref('temp');
          const permToken = ref('');

          onMounted(() => {
            fetch(bp + '/api/config/connector.cloud').then(r => r.json()).then(cfg => {
              config.server = cfg.server || '';
              config.key = cfg.key || '';
            }).catch(() => {});
          });

          const cloud = computed(() => props.connectors.cloud || {});
          const hostId = computed(() => cloud.value.host_id || '');
          const tokens = computed(() => cloud.value.tokens || {});
          const serverUrl = computed(() => cloud.value.server_url || config.server || '');

          function buildLoginUrl(token) {
            const srv = serverUrl.value;
            const hid = hostId.value;
            if (!token || !hid || !srv) return '';
            return srv + '/api/access/token/login?token=' + encodeURIComponent(token) + '&host=' + encodeURIComponent(hid);
          }

          const tempQrUrl = computed(() => buildLoginUrl(tokens.value.temporary));

          // Permanent QR is only available after generating a new key
          const permQrUrl = computed(() => permToken.value ? buildLoginUrl(permToken.value) : '');

          async function saveConfig(enabled) {
            loading.value = true;
            try {
              await fetch(bp + '/api/config/connector.cloud', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ enabled, server: config.server, key: config.key }),
              });
              emit('save', enabled);
            } finally { loading.value = false; }
          }

          async function refreshTempToken() {
            loading.value = true;
            try {
              const resp = await fetch(bp + '/api/connectors/cloud/token', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ permanent: false }),
              });
              if ((await resp.json()).ok) emit('save', true);
            } finally { loading.value = false; }
          }

          async function regeneratePermanent() {
            loading.value = true;
            permToken.value = '';
            try {
              const resp = await fetch(bp + '/api/connectors/cloud/token', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ permanent: true }),
              });
              const data = await resp.json();
              if (data.ok) {
                permToken.value = data.token;
                emit('save', true);
              }
            } finally { loading.value = false; }
          }

          return {
            config, loading, showKey, tab, cloud, hostId, tokens, serverUrl,
            tempQrUrl, permQrUrl, permToken,
            saveConfig, refreshTempToken, regeneratePermanent,
          };
        },
        template: `
          <div class="connector-panel">
            <div class="connector-panel-header">
              <h3><i class="ph ph-cloud"></i> Cloud Proxy</h3>
              <button class="connector-panel-close" @click="$emit('close')"><i class="ph ph-x"></i></button>
            </div>
            <div class="connector-panel-body">
              <!-- Status -->
              <div style="text-align:center;margin-bottom:12px">
                <span class="dot" :class="cloud.active ? 'on' : 'off'"
                      style="display:inline-block;width:10px;height:10px;border-radius:50%"></span>
                {{ cloud.active ? 'Connected' : 'Disconnected' }}
                <span v-if="cloud.active" style="font-size:11px;color:var(--el-text-dim);margin-left:6px">{{ serverUrl }}</span>
              </div>

              <!-- Tabs (when connected) -->
              <div v-if="cloud.active" style="display:flex;gap:0;margin-bottom:12px;border-radius:6px;overflow:hidden;border:1px solid var(--el-border)">
                <button v-for="t in [{id:'temp',label:'Session QR',icon:'ph ph-clock'},{id:'perm',label:'Permanent QR',icon:'ph ph-key'},{id:'settings',label:'Settings',icon:'ph ph-gear'}]"
                        :key="t.id" @click="tab = t.id"
                        style="flex:1;padding:8px 4px;border:none;font-size:11px;cursor:pointer;transition:background .15s"
                        :style="{ background: tab === t.id ? 'var(--el-primary)' : 'var(--el-surface)', color: tab === t.id ? '#fff' : 'var(--el-text-dim)' }">
                  <i :class="t.icon" style="margin-right:2px"></i> {{ t.label }}
                </button>
              </div>

              <!-- Tab: Temporary token (default) -->
              <div v-if="cloud.active && tab === 'temp'" style="text-align:center">
                <hort-qr :url="tempQrUrl" label="Scan to connect — expires on server restart" />
                <button @click="refreshTempToken()" :disabled="loading"
                        style="margin-top:8px;padding:8px 16px;border:none;border-radius:6px;font-size:12px;cursor:pointer;background:var(--el-surface);color:var(--el-text);border:1px solid var(--el-border)">
                  <i class="ph ph-arrows-clockwise"></i> Refresh Token
                </button>
              </div>

              <!-- Tab: Permanent token -->
              <div v-if="cloud.active && tab === 'perm'" style="text-align:center">
                <hort-qr v-if="permQrUrl" :url="permQrUrl" label="Bookmark this — never expires" />
                <div v-else-if="tokens.has_permanent && !permToken" style="color:var(--el-text-dim);font-size:12px;margin:12px 0">
                  <i class="ph ph-key"></i> Permanent key is active.<br>
                  <span style="font-size:11px">Regenerate to see the QR code (old key will be invalidated).</span>
                </div>
                <button @click="regeneratePermanent()" :disabled="loading"
                        style="margin-top:8px;padding:8px 16px;border:none;border-radius:6px;font-size:12px;cursor:pointer;background:var(--el-surface);color:var(--el-text);border:1px solid var(--el-border)">
                  <i class="ph ph-key"></i> {{ tokens.has_permanent ? 'Regenerate Key' : 'Create Permanent Key' }}
                </button>
              </div>

              <!-- Tab: Settings (or shown when disconnected) -->
              <div v-if="!cloud.active || tab === 'settings'">
                <div style="font-size:12px;color:var(--el-text-dim);margin-bottom:8px">Settings (saved to hort-config.yaml)</div>
                <label style="font-size:12px;color:var(--el-text-dim);display:block;margin-bottom:4px">Server URL</label>
                <input v-model="config.server" placeholder="https://openhort-access.azurewebsites.net"
                       style="width:100%;background:var(--el-bg);color:var(--el-text);border:1px solid var(--el-border);border-radius:6px;padding:8px;font-size:13px;margin-bottom:8px;box-sizing:border-box">
                <label style="font-size:12px;color:var(--el-text-dim);display:block;margin-bottom:4px">Connection Key</label>
                <div style="position:relative">
                  <input :type="showKey ? 'text' : 'password'" v-model="config.key" placeholder="Your connection key"
                         style="width:100%;background:var(--el-bg);color:var(--el-text);border:1px solid var(--el-border);border-radius:6px;padding:8px;padding-right:36px;font-size:13px;margin-bottom:12px;box-sizing:border-box">
                  <button @click="showKey = !showKey"
                          style="position:absolute;right:6px;top:6px;background:none;border:none;cursor:pointer;color:var(--el-text-dim);font-size:16px">
                    <i :class="showKey ? 'ph ph-eye-slash' : 'ph ph-eye'"></i>
                  </button>
                </div>
                <div style="display:flex;gap:8px">
                  <button @click="saveConfig(true)" :disabled="loading"
                          style="flex:1;padding:10px;border:none;border-radius:6px;font-size:13px;cursor:pointer;font-weight:600"
                          :style="{ background: 'var(--el-success)', color: '#fff' }">
                    <i class="ph ph-power"></i> Enable &amp; Save
                  </button>
                  <button @click="saveConfig(false)" :disabled="loading"
                          style="flex:1;padding:10px;border:none;border-radius:6px;font-size:13px;cursor:pointer;font-weight:600"
                          :style="{ background: 'var(--el-border)', color: 'var(--el-text-dim)' }">
                    <i class="ph ph-stop"></i> Disable
                  </button>
                </div>
              </div>
            </div>
          </div>
        `,
      });
    }
  }

  HortExtension.register(CloudConnector);
})();
