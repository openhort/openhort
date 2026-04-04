/* Telegram Connector — panel UI extension */
/* global HortExtension, Vue */

(function () {
  'use strict';

  class TelegramConnectorExt extends HortExtension {
    static id = 'telegram-connector';
    static name = 'Telegram';
    static connectorIcon = 'ph ph-telegram-logo';

    setup(app) {
      app.component('telegram-connector-panel', {
        props: ['connectors'],
        emits: ['close'],
        setup(props) {
          const { computed, ref, onMounted } = Vue;
          const bp = HortExtension.basePath;
          const tg = computed(() => (props.connectors.messaging || {}).telegram || {});
          const config = Vue.reactive({ allowed_users: '' });

          onMounted(() => {
            fetch(bp + '/api/config/connector.telegram').then(r => r.json()).then(cfg => {
              config.allowed_users = (cfg.allowed_users || []).join(', ');
            }).catch(() => {});
          });

          return { tg, config };
        },
        template: `
          <div class="connector-panel">
            <div class="connector-panel-header">
              <h3><i class="ph ph-telegram-logo"></i> Telegram Bot</h3>
              <button class="connector-panel-close" @click="$emit('close')"><i class="ph ph-x"></i></button>
            </div>
            <div class="connector-panel-body">
              <!-- Status -->
              <div style="text-align:center;margin-bottom:16px">
                <span class="dot" :class="tg.polling ? 'on' : 'off'"
                      style="display:inline-block;width:10px;height:10px;border-radius:50%"></span>
                {{ tg.polling ? 'Polling' : 'Stopped' }}
              </div>

              <!-- Info rows -->
              <div style="display:flex;flex-direction:column;gap:10px">
                <div style="display:flex;justify-content:space-between;align-items:center">
                  <span style="font-size:12px;color:var(--el-text-dim)">Bot Token</span>
                  <span style="font-size:13px" :style="{color: tg.token_set ? 'var(--el-success)' : 'var(--el-danger)'}">
                    {{ tg.token_set ? 'Configured' : 'Not set' }}
                  </span>
                </div>
                <div style="display:flex;justify-content:space-between;align-items:center">
                  <span style="font-size:12px;color:var(--el-text-dim)">Allowed Users</span>
                  <span style="font-size:13px">{{ (tg.allowed_users || []).join(', ') || 'Anyone' }}</span>
                </div>
              </div>

              <!-- Setup hint -->
              <div v-if="!tg.token_set" style="margin-top:16px;padding:12px;border-radius:8px;background:var(--el-bg);font-size:12px;color:var(--el-text-dim);line-height:1.5">
                <i class="ph ph-info" style="margin-right:4px"></i>
                Set <code style="background:var(--el-surface);padding:2px 5px;border-radius:4px">TELEGRAM_BOT_TOKEN</code> env var and restart the server.
              </div>

              <!-- Commands: use /help in Telegram -->
            </div>
          </div>
        `,
      });
    }
  }

  HortExtension.register(TelegramConnectorExt);
})();
