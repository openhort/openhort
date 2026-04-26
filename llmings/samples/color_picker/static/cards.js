/* Color Picker — client-side with vault persistence */
/* global LlmingClient, Vue, Quasar */

(function () {
  'use strict';

  class ColorPickerCard extends LlmingClient {
    static id = 'color-picker';
    static name = 'Color Picker';
    static llmingTitle = 'Color Picker';
    static llmingIcon = 'ph ph-palette';
    static llmingDescription = 'Pick and save favorite colors';

    _color = '#3b82f6';
    _saved = [];

    onConnect() {
      this.vault.get('state').then(s => {
        if (s && s.color) this._color = s.color;
        if (s && s.saved) this._saved = s.saved;
      });
    }

    renderThumbnail(ctx, w, h) {
      // Draw current color as full background
      ctx.fillStyle = this._color;
      ctx.fillRect(0, 0, w, h);

      // Saved colors as dots at the bottom
      const dots = this._saved.slice(-8);
      const dotR = 8;
      const startX = (w - dots.length * (dotR * 2 + 4)) / 2 + dotR;
      dots.forEach((c, i) => {
        ctx.fillStyle = c;
        ctx.beginPath();
        ctx.arc(startX + i * (dotR * 2 + 4), h - 20, dotR, 0, Math.PI * 2);
        ctx.fill();
        ctx.strokeStyle = '#fff';
        ctx.lineWidth = 1;
        ctx.stroke();
      });

      // Hex label
      ctx.fillStyle = '#fff';
      ctx.font = 'bold 18px monospace';
      ctx.textAlign = 'center';
      ctx.shadowColor = '#000';
      ctx.shadowBlur = 4;
      ctx.fillText(this._color, w / 2, h / 2 + 6);
      ctx.shadowBlur = 0;
    }

    setup(app, Quasar) {
      const card = this;

      app.component('color-picker-panel', {
        template: `
          <div style="padding:20px">
            <div :style="{background: color, height: '120px', borderRadius: '8px', marginBottom: '16px',
              display: 'flex', alignItems: 'center', justifyContent: 'center'}">
              <span style="color:#fff;font-size:24px;font-weight:bold;text-shadow:0 1px 4px #0008">{{ color }}</span>
            </div>
            <div style="display:flex;gap:8px;align-items:center;margin-bottom:16px">
              <input type="color" :value="color" @input="setColor($event.target.value)"
                style="width:48px;height:48px;border:none;cursor:pointer" />
              <input type="text" v-model="color" @change="setColor(color)"
                style="flex:1;padding:8px 10px;background:var(--el-surface);color:var(--el-text);border:1px solid var(--border);border-radius:6px;font-family:monospace" />
              <button @click="saveColor"
                style="padding:8px 12px;background:transparent;color:#ec4899;border:none;cursor:pointer;font-size:18px">♥</button>
            </div>
            <div v-if="saved.length" style="display:flex;flex-wrap:wrap;gap:6px">
              <div v-for="(c, i) in saved" :key="i" @click="setColor(c)"
                :style="{width:'36px',height:'36px',borderRadius:'6px',background:c,cursor:'pointer',
                  border:'2px solid '+(c===color?'#fff':'transparent')}" />
            </div>
          </div>
        `,
        data() {
          return { color: card._color, saved: [...card._saved] };
        },
        methods: {
          setColor(c) {
            this.color = c;
            card._color = c;
            card.vault.set('state', { color: c, saved: this.saved });
          },
          saveColor() {
            if (!this.saved.includes(this.color)) {
              this.saved.push(this.color);
              if (this.saved.length > 20) this.saved.shift();
              card._saved = [...this.saved];
              card.vault.set('state', { color: this.color, saved: this.saved });
            }
          },
        },
      });
    }
  }

  LlmingClient.register(ColorPickerCard);
})();
