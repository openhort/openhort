/* LAN Connector — panel UI extension */
/* global HortExtension */

(function () {
  'use strict';

  class LanConnector extends HortExtension {
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
              <hort-qr :url="lanUrl" label="Scan to connect from your phone" />
            </div>
          </div>
        `,
      });
    }
  }

  HortExtension.register(LanConnector);
})();
