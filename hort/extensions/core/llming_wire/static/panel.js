/* LlmingWire — built-in chat UI */
/* global HortExtension, Vue */

(function () {
  'use strict';

  // Load CSS
  const link = document.createElement('link');
  link.rel = 'stylesheet';
  link.href = (document.querySelector('base')?.getAttribute('href') || '/') + 'ext/llming_wire/static/llming-wire.css';
  document.head.appendChild(link);

  class LlmingWirePanel extends HortExtension {
    static id = 'llming-wire';
    static name = 'LlmingWire';
    static llmingTitle = 'LlmingWire';
    static llmingIcon = 'ph ph-chat-dots';
    static llmingDescription = 'Chat with your hort';
    static llmingWidgets = ['llming-wire-chat'];
    static autoShow = true;

    setup(app) {
      app.component('llming-wire-chat', {
        template: `
          <div class="llming-wire-root">
            <div class="llming-wire-messages" ref="msgList">
              <div v-if="messages.length === 0" class="llming-wire-empty">
                <i class="ph ph-chat-dots" style="font-size:48px;opacity:0.2"></i>
                <div style="margin-top:8px;opacity:0.4">Say something...</div>
              </div>
              <div v-for="msg in messages" :key="msg.id"
                   :class="['llming-wire-bubble', msg.role === 'user' ? 'llming-wire-user' : 'llming-wire-ai']">
                <span class="llming-wire-bubble-text">{{ msg.text }}</span>
                <span class="llming-wire-ts">
                  {{ formatTime(msg.ts) }}
                  <span v-if="msg.role === 'user'" class="llming-wire-check">&#10003;&#10003;</span>
                </span>
                <div v-if="msg.buttons && msg.buttons.length" class="llming-wire-buttons">
                  <button v-for="btn in msg.buttons" :key="btn.id"
                          class="llming-wire-btn" @click="sendButton(btn)">
                    {{ btn.label }}
                  </button>
                </div>
              </div>
              <div v-if="loading" class="llming-wire-bubble llming-wire-ai llming-wire-typing">
                <span class="llming-wire-dot"></span>
                <span class="llming-wire-dot"></span>
                <span class="llming-wire-dot"></span>
              </div>
            </div>
            <div class="llming-wire-input-bar">
              <input v-model="draft" class="llming-wire-input"
                     placeholder="Type a message..."
                     @keydown.enter="send"
                     :disabled="loading" />
              <button class="llming-wire-send" @click="send" :disabled="!draft.trim() || loading">
                <i class="ph ph-paper-plane-right"></i>
              </button>
            </div>
          </div>
        `,

        data() {
          return {
            messages: [],
            draft: '',
            loading: false,
            conversationId: null,
          };
        },

        async mounted() {
          await this.createConversation();
        },

        methods: {
          async createConversation() {
            try {
              const r = await fetch(this.apiUrl('conversations'), { method: 'POST' });
              const data = await r.json();
              this.conversationId = data.id;
            } catch (e) {
              console.error('LlmingWire: failed to create conversation', e);
            }
          },

          async send() {
            const text = this.draft.trim();
            if (!text || this.loading || !this.conversationId) return;
            this.draft = '';

            // Show user message immediately
            this.messages.push({
              id: Date.now().toString(),
              role: 'user',
              text: text,
              ts: Date.now() / 1000,
            });
            this.loading = true;
            this.scrollBottom();

            try {
              const r = await fetch(
                this.apiUrl('conversations/' + this.conversationId + '/messages'),
                {
                  method: 'POST',
                  headers: { 'Content-Type': 'application/json' },
                  body: JSON.stringify({ text }),
                }
              );
              const msg = await r.json();
              if (msg.error) {
                this.messages.push({ id: Date.now().toString(), role: 'assistant', text: msg.error, ts: Date.now() / 1000, buttons: [] });
              } else {
                // Add AI response (user msg already shown)
                this.messages.push(msg);
              }
            } catch (e) {
              this.messages.push({
                id: Date.now().toString(),
                role: 'assistant',
                text: 'Error: ' + e.message,
                ts: Date.now() / 1000,
                buttons: [],
              });
            } finally {
              this.loading = false;
              this.scrollBottom();
            }
          },

          async sendButton(btn) {
            this.draft = btn.label;
            await this.send();
          },

          async refreshMessages() {
            if (!this.conversationId) return;
            try {
              const r = await fetch(this.apiUrl('conversations/' + this.conversationId + '/messages'));
              this.messages = await r.json();
              this.scrollBottom();
            } catch (e) { /* ignore */ }
          },

          scrollBottom() {
            this.$nextTick(() => {
              const el = this.$refs.msgList;
              if (el) el.scrollTop = el.scrollHeight;
            });
          },

          formatTime(ts) {
            if (!ts) return '';
            const d = new Date(ts * 1000);
            return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
          },

          apiUrl(path) {
            const base = document.querySelector('base');
            const prefix = base ? base.getAttribute('href') : '/';
            return prefix + 'api/plugins/llming-wire/' + path;
          },
        },
      });
    }

    renderThumbnail(ctx, w, h) {
      ctx.fillStyle = '#0a0e1a';
      ctx.fillRect(0, 0, w, h);

      // Draw chat bubbles preview
      const bubbles = [
        { x: 12, y: 30, w: 120, text: 'How\u2019s the server?', user: true },
        { x: w - 170, y: 70, w: 150, text: 'All good \u2014 CPU 12%', user: false },
        { x: 12, y: 115, w: 80, text: 'Thanks!', user: true },
      ];

      for (const b of bubbles) {
        const bx = b.user ? 12 : w - b.w - 12;
        ctx.fillStyle = b.user ? '#1e3a5f' : '#1e293b';
        ctx.beginPath();
        ctx.roundRect(bx, b.y, b.w, 28, 8);
        ctx.fill();

        ctx.fillStyle = b.user ? '#93c5fd' : '#94a3b8';
        ctx.font = '11px system-ui';
        ctx.textAlign = 'left';
        ctx.fillText(b.text, bx + 8, b.y + 18);
      }

      // Input bar
      ctx.fillStyle = '#111827';
      ctx.fillRect(0, h - 30, w, 30);
      ctx.fillStyle = '#1e293b';
      ctx.beginPath();
      ctx.roundRect(8, h - 26, w - 50, 20, 6);
      ctx.fill();
      ctx.fillStyle = '#475569';
      ctx.font = '10px system-ui';
      ctx.fillText('Type a message...', 16, h - 12);
    }
  }

  HortExtension.register(LlmingWirePanel);
})();
