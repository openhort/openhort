/* Dice Roller — shows last roll + live updates */
/* global LlmingClient, Vue */

(function () {
  'use strict';

  class DiceRollerCard extends LlmingClient {
    static id = 'dice-roller';
    static name = 'Dice Roller';
    static llmingTitle = 'Dice Roller';
    static llmingIcon = 'ph ph-dice-five';
    static llmingDescription = 'Roll dice with history';

    _lastRoll = null;

    onConnect() {
      this.vault.get('state').then(s => {
        if (s && s.last_roll) this._lastRoll = s;
      });
      this.subscribe('dice_roll', d => {
        this._lastRoll = { last_roll: d.rolls, last_total: d.total, sides: d.sides };
      });
    }

    renderThumbnail(ctx, w, h) {
      ctx.fillStyle = '#111827';
      ctx.fillRect(0, 0, w, h);

      if (this._lastRoll && this._lastRoll.last_roll) {
        const rolls = this._lastRoll.last_roll;
        const total = this._lastRoll.last_total;

        // Draw dice
        ctx.fillStyle = '#f0f4ff';
        ctx.font = 'bold 42px system-ui';
        ctx.textAlign = 'center';
        ctx.fillText(rolls.join(' '), w / 2, h / 2);

        // Total
        ctx.fillStyle = '#3b82f6';
        ctx.font = 'bold 20px system-ui';
        ctx.fillText(`Total: ${total}`, w / 2, h / 2 + 35);

        // Type
        ctx.fillStyle = '#94a3b8';
        ctx.font = '12px system-ui';
        ctx.fillText(`d${this._lastRoll.sides}`, w / 2, h / 2 + 55);
      } else {
        ctx.fillStyle = '#94a3b8';
        ctx.font = '14px system-ui';
        ctx.textAlign = 'center';
        ctx.fillText('🎲 Roll some dice!', w / 2, h / 2);
        ctx.font = '12px system-ui';
        ctx.fillText('Use /roll or click here', w / 2, h / 2 + 20);
      }
    }

    setup(app, Quasar) {
      const card = this;

      app.component('dice-roller-panel', {
        template: `
          <div style="padding:20px;text-align:center">
            <div v-if="lastRoll" style="font-size:48px;font-weight:bold;color:var(--el-text);margin-bottom:8px">
              {{ lastRoll.join(' ') }}
            </div>
            <div v-if="lastRoll" style="font-size:24px;color:var(--el-primary);margin-bottom:16px">
              Total: {{ total }}
            </div>
            <div style="margin-bottom:16px">
              <q-btn-group>
                <q-btn label="d4" @click="roll(4)" />
                <q-btn label="d6" @click="roll(6)" color="primary" />
                <q-btn label="d8" @click="roll(8)" />
                <q-btn label="d10" @click="roll(10)" />
                <q-btn label="d12" @click="roll(12)" />
                <q-btn label="d20" @click="roll(20)" color="accent" />
              </q-btn-group>
            </div>
            <q-slider v-model="count" :min="1" :max="10" :step="1" label
              :label-value="count + ' dice'" style="max-width:200px;margin:0 auto" />
            <div v-if="history.length" style="margin-top:16px;text-align:left;max-height:200px;overflow-y:auto">
              <div style="color:var(--el-text-dim);font-size:12px" v-for="r in history" :key="r.ts">
                d{{ r.sides }}: [{{ r.rolls.join(', ') }}] = {{ r.total }}
              </div>
            </div>
          </div>
        `,
        data() {
          return { lastRoll: null, total: 0, count: 1, history: [] };
        },
        async mounted() {
          const s = await card.vault.get('state');
          if (s && s.last_roll) { this.lastRoll = s.last_roll; this.total = s.last_total; }
          const h = await card.vault.get('history');
          if (h && h.rolls) this.history = h.rolls.slice(-20).reverse();

          card.subscribe('dice_roll', d => {
            this.lastRoll = d.rolls;
            this.total = d.total;
            this.history.unshift({ rolls: d.rolls, total: d.total, sides: d.sides, ts: Date.now() });
            if (this.history.length > 20) this.history.pop();
          });
        },
        methods: {
          async roll(sides) {
            const result = await card.call('roll', { sides, count: this.count });
            if (result && result.rolls) {
              this.lastRoll = result.rolls;
              this.total = result.total;
            }
          },
        },
      });
    }
  }

  LlmingClient.register(DiceRollerCard);
})();
