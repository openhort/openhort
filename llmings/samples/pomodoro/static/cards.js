/* Pomodoro Timer — pure client-side card */
/* global LlmingClient, Vue */

(function () {
  'use strict';

  class PomodoroCard extends LlmingClient {
    static id = 'pomodoro';
    static name = 'Pomodoro';
    static llmingTitle = 'Pomodoro Timer';
    static llmingIcon = 'ph ph-timer';
    static llmingDescription = 'Focus timer — works offline';

    _remaining = 25 * 60;
    _running = false;
    _interval = null;

    onConnect() {
      this.vault.get('state').then(s => {
        if (s && s.remaining !== undefined) this._remaining = s.remaining;
      });
    }

    renderThumbnail(ctx, w, h) {
      const bg = '#111827';
      ctx.fillStyle = bg;
      ctx.fillRect(0, 0, w, h);

      const mins = String(Math.floor(this._remaining / 60)).padStart(2, '0');
      const secs = String(this._remaining % 60).padStart(2, '0');

      // Time display
      ctx.fillStyle = this._running ? '#10b981' : '#f0f4ff';
      ctx.font = 'bold 48px system-ui';
      ctx.textAlign = 'center';
      ctx.fillText(`${mins}:${secs}`, w / 2, h / 2 + 10);

      // Status
      ctx.fillStyle = '#94a3b8';
      ctx.font = '13px system-ui';
      ctx.fillText(this._running ? 'FOCUSING' : 'PAUSED', w / 2, h / 2 + 40);

      // Progress arc
      const cx = w / 2, cy = h / 2 - 5;
      const r = 70;
      const progress = 1 - (this._remaining / (25 * 60));
      ctx.strokeStyle = '#334155';
      ctx.lineWidth = 4;
      ctx.beginPath();
      ctx.arc(cx, cy, r, -Math.PI / 2, Math.PI * 1.5);
      ctx.stroke();
      if (progress > 0) {
        ctx.strokeStyle = this._running ? '#10b981' : '#3b82f6';
        ctx.lineWidth = 4;
        ctx.beginPath();
        ctx.arc(cx, cy, r, -Math.PI / 2, -Math.PI / 2 + Math.PI * 2 * progress);
        ctx.stroke();
      }
    }

    setup(app, Quasar) {
      const card = this;

      app.component('pomodoro-panel', {
        template: `
          <div style="padding:20px;text-align:center">
            <div style="font-size:64px;font-weight:bold;font-family:monospace;color:var(--el-text)">
              {{ mins }}:{{ secs }}
            </div>
            <div style="margin:16px 0">
              <q-btn :label="running ? 'Pause' : 'Start'" :color="running ? 'negative' : 'positive'"
                @click="toggle" style="min-width:120px" />
              <q-btn label="Reset" flat color="grey" @click="reset" style="margin-left:8px" />
            </div>
            <q-slider v-model="duration" :min="5" :max="60" :step="5" :disable="running"
              label :label-value="duration + ' min'" style="max-width:300px;margin:0 auto" />
          </div>
        `,
        data() {
          return {
            remaining: card._remaining,
            running: card._running,
            duration: 25,
            timer: null,
          };
        },
        computed: {
          mins() { return String(Math.floor(this.remaining / 60)).padStart(2, '0'); },
          secs() { return String(this.remaining % 60).padStart(2, '0'); },
        },
        methods: {
          toggle() {
            this.running = !this.running;
            card._running = this.running;
            if (this.running) {
              this.timer = setInterval(() => {
                if (this.remaining > 0) {
                  this.remaining--;
                  card._remaining = this.remaining;
                } else {
                  this.running = false;
                  card._running = false;
                  clearInterval(this.timer);
                  Quasar.Notify.create({ message: 'Pomodoro complete!', color: 'positive' });
                }
              }, 1000);
            } else {
              clearInterval(this.timer);
            }
            card.vault.set('state', { remaining: this.remaining, running: this.running });
          },
          reset() {
            this.running = false;
            card._running = false;
            clearInterval(this.timer);
            this.remaining = this.duration * 60;
            card._remaining = this.remaining;
            card.vault.set('state', { remaining: this.remaining, running: false });
          },
        },
        watch: {
          duration(v) {
            if (!this.running) {
              this.remaining = v * 60;
              card._remaining = this.remaining;
            }
          },
        },
        unmounted() {
          clearInterval(this.timer);
        },
      });
    }
  }

  LlmingClient.register(PomodoroCard);
})();
