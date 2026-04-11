/* LAN Connector — panel UI extension */
/* global LlmingClient */

(function () {
  'use strict';

  class LanConnector extends LlmingClient {
    static id = 'lan-connector';
    static name = 'LAN';
    static connectorIcon = 'ph ph-wifi-high';

    setup(app) {
      app.component('lan-connector-panel', {
        props: ['connectors'],
        emits: ['close'],
        setup(props) {
          const { computed } = Vue;
          const lanUrl = computed(() => props.connectors.lan.https_url || props.connectors.lan.http_url || '');
          return { lanUrl };
        },
        template: `
          <div class="connector-panel">
            <div class="connector-panel-header">
              <h3><i class="ph ph-wifi-high"></i> LAN Connection</h3>
              <button class="connector-panel-close" @click="$emit('close')"><i class="ph ph-x"></i></button>
            </div>
            <div class="connector-panel-body" style="text-align: center">
              <div><span class="dot on" style="display:inline-block;width:10px;height:10px;border-radius:50%"></span> Active</div>
              <div v-if="lanUrl" style="display:flex;align-items:center;gap:8px;margin:12px 0;justify-content:center">
                <input :value="lanUrl" readonly style="flex:1;max-width:280px;background:#16213e;border:1px solid #333;color:#e0e0e0;padding:6px 10px;border-radius:6px;font-size:12px;font-family:monospace" @click="$event.target.select()">
                <button style="background:#7B1FA2;color:#fff;border:none;border-radius:6px;padding:6px 10px;cursor:pointer" @click="navigator.clipboard.writeText(lanUrl)">
                  <i class="ph ph-copy"></i>
                </button>
              </div>
              <hort-qr :url="lanUrl" label="Scan to connect from your phone" />
            </div>
          </div>
        `,
      });
    }
  }

  LlmingClient.register(LanConnector);
})();
