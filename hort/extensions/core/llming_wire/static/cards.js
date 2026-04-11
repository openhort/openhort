/* LlmingWire — built-in chat UI with IndexedDB persistence */
/* global LlmingClient */

(function () {
  'use strict';

  // Load CSS
  const link = document.createElement('link');
  link.rel = 'stylesheet';
  link.href = (document.querySelector('base')?.getAttribute('href') || '/') + 'ext/llming_wire/static/llming-wire.css';
  document.head.appendChild(link);

  // ── IndexedDB helper ─────────────────────────────────────────
  const DB_NAME = 'llming-wire';
  const DB_VERSION = 2;
  let _db = null;

  function openDB() {
    if (_db) return Promise.resolve(_db);
    return new Promise((resolve, reject) => {
      const req = indexedDB.open(DB_NAME, DB_VERSION);
      req.onupgradeneeded = (e) => {
        const db = req.result;
        if (!db.objectStoreNames.contains('conversations')) {
          db.createObjectStore('conversations', { keyPath: 'id' });
        }
        if (!db.objectStoreNames.contains('messages')) {
          const ms = db.createObjectStore('messages', { keyPath: 'id' });
          ms.createIndex('cid', 'cid');
        }
        // Media store: images, videos, files — referenced by messages
        // Each media entry tracks which messages reference it (refIds).
        // When a conversation is deleted, orphaned media is garbage collected.
        if (!db.objectStoreNames.contains('media')) {
          db.createObjectStore('media', { keyPath: 'id' });
        }
      };
      req.onsuccess = () => { _db = req.result; resolve(_db); };
      req.onerror = () => reject(req.error);
    });
  }

  async function dbPut(store, obj) {
    const db = await openDB();
    return new Promise((resolve, reject) => {
      const tx = db.transaction(store, 'readwrite');
      tx.objectStore(store).put(obj);
      tx.oncomplete = () => resolve();
      tx.onerror = () => reject(tx.error);
    });
  }

  async function dbGetAll(store, indexName, key) {
    const db = await openDB();
    return new Promise((resolve, reject) => {
      const tx = db.transaction(store, 'readonly');
      const os = tx.objectStore(store);
      const req = indexName ? os.index(indexName).getAll(key) : os.getAll();
      req.onsuccess = () => resolve(req.result || []);
      req.onerror = () => reject(req.error);
    });
  }

  async function dbGet(store, key) {
    const db = await openDB();
    return new Promise((resolve, reject) => {
      const tx = db.transaction(store, 'readonly');
      const req = tx.objectStore(store).get(key);
      req.onsuccess = () => resolve(req.result);
      req.onerror = () => reject(req.error);
    });
  }

  async function dbDelete(store, key) {
    const db = await openDB();
    return new Promise((resolve, reject) => {
      const tx = db.transaction(store, 'readwrite');
      tx.objectStore(store).delete(key);
      tx.oncomplete = () => resolve();
      tx.onerror = () => reject(tx.error);
    });
  }

  // ── Media helpers ─────────────────────────────────────────────

  /**
   * Save a media blob to IndexedDB.
   * @param {Blob} blob - The binary data (image, video, file).
   * @param {string} mime - MIME type (e.g. 'image/jpeg', 'video/mp4').
   * @param {string} msgId - The message ID that references this media.
   * @returns {string} The media ID (use as mediaRef in the message).
   */
  async function mediaSave(blob, mime, msgId) {
    const id = Date.now().toString(36) + Math.random().toString(36).slice(2, 6);
    await dbPut('media', {
      id,
      blob,
      mime,
      size: blob.size,
      created: Date.now(),
      refIds: [msgId],  // messages referencing this media
    });
    return id;
  }

  /** Get a media entry by ID. Returns { id, blob, mime, size } or undefined. */
  async function mediaGet(id) {
    return dbGet('media', id);
  }

  /**
   * Garbage collect orphaned media.
   * Scans all media entries and deletes any whose refIds don't match
   * any existing message. Called after conversation deletion.
   */
  async function mediaGC() {
    try {
      const allMedia = await dbGetAll('media');
      if (!allMedia.length) return;
      const allMessages = await dbGetAll('messages');
      const msgIds = new Set(allMessages.map(m => m.id));
      for (const m of allMedia) {
        // Keep media if ANY referencing message still exists
        const alive = (m.refIds || []).some(rid => msgIds.has(rid));
        if (!alive) {
          await dbDelete('media', m.id);
        }
      }
    } catch (e) { /* best effort */ }
  }

  /**
   * Add a message reference to an existing media entry.
   * Used when the same media is shared across messages.
   */
  async function mediaAddRef(mediaId, msgId) {
    try {
      const m = await mediaGet(mediaId);
      if (m && !m.refIds.includes(msgId)) {
        m.refIds.push(msgId);
        await dbPut('media', m);
      }
    } catch (e) { /* best effort */ }
  }

  // ── Panel ────────────────────────────────────────────────────

  class LlmingWirePanel extends LlmingClient {
    static id = 'llming-wire';
    static name = 'LlmingWire';
    static llmingTitle = 'LlmingWire';
    static llmingIcon = 'ph ph-chat-dots';
    static llmingDescription = 'Chat with your hort';
    static llmingWidgets = ['llming-wire-chat'];
    static autoShow = true;
    static deviceTypes = ['phone', 'tablet', 'desktop'];
    // Float sizes — read from manifest.json ui_float
    static ui_float = { width_pct: 35, height_pct: 75, min_width: 380, min_height: 500 };

    setup(app) {
      app.component('llming-wire-chat', {
        template: `
          <div class="llming-wire-root">
            <!-- Conversation list (sidebar) -->
            <div v-if="showSidebar" class="llming-wire-sidebar">
              <div class="llming-wire-sidebar-header">
                <span>Chats</span>
                <button class="llming-wire-new-btn" @click="newConversation" title="New chat">
                  <i class="ph ph-plus"></i>
                </button>
              </div>
              <div v-for="c in conversations" :key="c.id"
                   :class="['llming-wire-conv-item', c.id === activeConvId ? 'active' : '']"
                   @click="switchConversation(c.id)">
                <div class="llming-wire-conv-title">{{ c.title || 'New chat' }}</div>
                <div class="llming-wire-conv-preview">{{ c.lastMsg || '' }}</div>
                <div class="llming-wire-conv-time">{{ formatDate(c.lastActive) }}</div>
                <button class="llming-wire-conv-delete" @click.stop="deleteConversation(c.id)"
                        title="Delete"><i class="ph ph-x"></i></button>
              </div>
              <div v-if="conversations.length === 0" style="padding:20px;text-align:center;opacity:0.4">
                No conversations yet
              </div>
            </div>

            <!-- Chat area -->
            <div class="llming-wire-chat-area">
              <!-- Chat header -->
              <div class="llming-wire-chat-header">
                <button class="llming-wire-toggle-sidebar" @click="showSidebar = !showSidebar">
                  <i :class="showSidebar ? 'ph ph-caret-left' : 'ph ph-list'"></i>
                </button>
                <span class="llming-wire-chat-title">{{ activeTitle }}</span>
                <button class="llming-wire-new-btn" @click="newConversation" title="New chat">
                  <i class="ph ph-plus"></i>
                </button>
              </div>

              <!-- Messages -->
              <div class="llming-wire-messages" ref="msgList" @click="onMsgClick">
                <div v-if="messages.length === 0" class="llming-wire-empty">
                  <i class="ph ph-chat-dots" style="font-size:48px;opacity:0.15"></i>
                  <div style="margin-top:8px;opacity:0.3;font-size:14px">Say something...</div>
                </div>
                <div v-for="msg in messages" :key="msg.id"
                     :class="['llming-wire-bubble', msg.role === 'user' ? 'llming-wire-user' : 'llming-wire-ai']">
                  <img v-if="msg.image" :src="msg.image" @click="zoomImage = msg.image"
                       style="max-width:100%;border-radius:8px;margin-bottom:4px;cursor:zoom-in" loading="lazy" />
                  <span class="llming-wire-bubble-text" v-html="linkify(msg.text)"></span>
                  <span class="llming-wire-ts">
                    {{ formatTime(msg.ts) }}
                    <span v-if="msg.role === 'user'" class="llming-wire-check">&#10003;&#10003;</span>
                  </span>
                  <div v-if="msg.buttons && msg.buttons.length" class="llming-wire-buttons">
                    <button v-for="btn in msg.buttons" :key="btn.id"
                            class="llming-wire-btn" @click="sendCallbackButton(btn)">
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

              <!-- Input bar -->
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

            <!-- Photobox zoom overlay -->
            <div v-if="zoomImage" class="llming-wire-zoom" @click.self="zoomImage = null"
                 @keydown.esc="zoomImage = null" tabindex="0" ref="zoomOverlay">
              <button class="llming-wire-zoom-close" @click="zoomImage = null">
                <i class="ph ph-x"></i>
              </button>
              <img :src="zoomImage" class="llming-wire-zoom-img" />
            </div>
          </div>
        `,

        data() {
          return {
            conversations: [],
            messages: [],
            draft: '',
            loading: false,
            activeConvId: null,
            serverConvId: null,   // server-side conversation ID
            sessionId: null,      // Claude session_id for --resume
            showSidebar: false,
            zoomImage: null,
          };
        },

        computed: {
          activeTitle() {
            const c = this.conversations.find(x => x.id === this.activeConvId);
            return c?.title || 'New chat';
          },
        },

        unmounted() {
          if (this._escHandler) document.removeEventListener('keydown', this._escHandler);
        },

        async mounted() {
          this._escHandler = (e) => this.onKeydown(e);
          document.addEventListener('keydown', this._escHandler);
          await this.loadConversations();
          if (this.conversations.length > 0) {
            // Resume most recent conversation
            await this.switchConversation(this.conversations[0].id);
          } else {
            await this.newConversation();
          }
        },

        methods: {
          // ── IndexedDB operations ──────────────────────────────
          async loadConversations() {
            try {
              const all = await dbGetAll('conversations');
              this.conversations = all.sort((a, b) => (b.lastActive || 0) - (a.lastActive || 0));
            } catch (e) { this.conversations = []; }
          },

          async loadMessages(convId) {
            try {
              this.messages = await dbGetAll('messages', 'cid', convId);
              this.messages.sort((a, b) => a.ts - b.ts);
              const withImg = this.messages.filter(m => m.image);
              if (withImg.length) console.log('[wire] loaded ' + this.messages.length + ' msgs, ' + withImg.length + ' with images');
            } catch (e) { this.messages = []; }
            this.scrollBottom();
          },

          async saveMessage(msg) {
            try {
              // Deep-clone to plain object — Vue reactive proxies and
              // non-cloneable objects break IndexedDB's structured clone
              const plain = JSON.parse(JSON.stringify(msg));
              await dbPut('messages', plain);
            } catch (e) { console.error('[wire] save failed:', e); }
          },

          async saveConversation(conv) {
            try { await dbPut('conversations', JSON.parse(JSON.stringify(conv))); } catch (e) { /* best effort */ }
          },

          // ── Conversation management ───────────────────────────
          async newConversation() {
            const id = Date.now().toString(36) + Math.random().toString(36).slice(2, 6);
            const conv = { id, title: '', lastMsg: '', lastActive: Date.now(), sessionId: null, serverConvId: null };
            await this.saveConversation(conv);
            await this.loadConversations();
            await this.switchConversation(id);
          },

          async switchConversation(convId) {
            this.activeConvId = convId;
            await this.loadMessages(convId);
            const conv = await dbGet('conversations', convId);
            this.sessionId = conv?.sessionId || null;
            this.serverConvId = conv?.serverConvId || null;
            // Create server-side conversation if needed
            if (!this.serverConvId) {
              try {
                const r = await fetch(this.apiUrl('conversations'), { method: 'POST' });
                const data = await r.json();
                this.serverConvId = data.id;
                if (conv) { conv.serverConvId = data.id; await this.saveConversation(conv); }
              } catch (e) { /* offline ok */ }
            }
            this.showSidebar = false;
          },

          async deleteConversation(convId) {
            try {
              await dbDelete('conversations', convId);
              // Delete messages for this conversation
              const msgs = await dbGetAll('messages', 'cid', convId);
              for (const m of msgs) await dbDelete('messages', m.id);
              // Garbage collect orphaned media (images, videos)
              await mediaGC();
            } catch (e) { /* best effort */ }
            await this.loadConversations();
            if (this.activeConvId === convId) {
              if (this.conversations.length > 0) {
                await this.switchConversation(this.conversations[0].id);
              } else {
                await this.newConversation();
              }
            }
          },

          // ── Messaging ─────────────────────────────────────────
          async send() {
            const text = this.draft.trim();
            if (!text || this.loading || !this.activeConvId) return;
            this.draft = '';

            // Show user message immediately
            const userMsg = {
              id: Date.now().toString() + 'u',
              cid: this.activeConvId,
              role: 'user',
              text, ts: Date.now() / 1000,
            };
            this.messages.push(userMsg);
            await this.saveMessage(userMsg);
            this.loading = true;
            this.scrollBottom();

            // Auto-title from first message
            const conv = await dbGet('conversations', this.activeConvId);
            if (conv && !conv.title) {
              conv.title = text.slice(0, 40) + (text.length > 40 ? '...' : '');
              conv.lastMsg = text.slice(0, 50);
              conv.lastActive = Date.now();
              await this.saveConversation(conv);
              await this.loadConversations();
            }

            try {
              // Ensure server conversation exists
              if (!this.serverConvId) {
                const r = await fetch(this.apiUrl('conversations'), { method: 'POST' });
                const data = await r.json();
                this.serverConvId = data.id;
                if (conv) { conv.serverConvId = data.id; await this.saveConversation(conv); }
              }

              const r = await fetch(
                this.apiUrl('conversations/' + this.serverConvId + '/messages'),
                {
                  method: 'POST',
                  headers: { 'Content-Type': 'application/json' },
                  body: JSON.stringify({ text, session_id: this.sessionId }),
                }
              );
              const msg = await r.json();

              // Save session_id for --resume on reconnect
              if (msg.session_id && conv) {
                this.sessionId = msg.session_id;
                conv.sessionId = msg.session_id;
                await this.saveConversation(conv);
              }

              const aiMsg = {
                id: (msg.id || Date.now().toString()) + 'a',
                cid: this.activeConvId,
                role: 'assistant',
                text: msg.error || msg.text || '(no response)',
                ts: msg.ts || Date.now() / 1000,
                buttons: msg.buttons || [],
                image: msg.image || null,
              };
              this.messages.push(aiMsg);
              await this.saveMessage(aiMsg);

              // Update conversation preview
              if (conv) {
                conv.lastMsg = aiMsg.text.slice(0, 50);
                conv.lastActive = Date.now();
                await this.saveConversation(conv);
                await this.loadConversations();
              }
            } catch (e) {
              const errMsg = {
                id: Date.now().toString() + 'e',
                cid: this.activeConvId,
                role: 'assistant',
                text: 'Error: ' + e.message,
                ts: Date.now() / 1000, buttons: [],
              };
              this.messages.push(errMsg);
              await this.saveMessage(errMsg);
            } finally {
              this.loading = false;
              this.scrollBottom();
            }
          },

          onKeydown(e) {
            if (e.key === 'Escape' && this.zoomImage) { this.zoomImage = null; e.preventDefault(); }
          },

          onMsgClick(e) {
            const link = e.target.closest('.llming-wire-cmd-link');
            if (link) {
              e.preventDefault();
              const cmd = link.dataset.cmd;
              if (cmd) { this.draft = cmd; this.send(); }
            }
          },

          async sendButton(btn) {
            this.draft = btn.label;
            await this.send();
          },

          async sendCallbackButton(btn) {
            // For callback buttons (from /windows etc.), send the callback_data
            // to the server which dispatches to the plugin's callback handler
            this.loading = true;
            this.scrollBottom();
            try {
              const r = await fetch(
                this.apiUrl('conversations/' + this.serverConvId + '/callback'),
                {
                  method: 'POST',
                  headers: { 'Content-Type': 'application/json' },
                  body: JSON.stringify({ callback_data: btn.id }),
                }
              );
              const msg = await r.json();
              if (msg.text || msg.image) {
                this.messages.push({
                  id: (msg.id || Date.now().toString()) + 'cb',
                  cid: this.activeConvId,
                  role: 'assistant',
                  text: msg.text || '',
                  image: msg.image || null,
                  ts: msg.ts || Date.now() / 1000,
                  buttons: msg.buttons || [],
                });
                await this.saveMessage(this.messages[this.messages.length - 1]);
              }
            } catch (e) {
              this.messages.push({
                id: Date.now().toString() + 'e',
                cid: this.activeConvId,
                role: 'assistant',
                text: 'Error: ' + e.message,
                ts: Date.now() / 1000,
              });
            } finally {
              this.loading = false;
              this.scrollBottom();
            }
          },

          scrollBottom() {
            this.$nextTick(() => {
              const el = this.$refs.msgList;
              if (el) el.scrollTop = el.scrollHeight;
            });
          },

          linkify(text) {
            if (!text) return '';
            // SECURITY: escape ALL HTML first — prevents XSS from any source.
            // Then add back ONLY safe patterns (URLs, /commands) as links.
            let s = text
              .replace(/&/g, '&amp;')
              .replace(/</g, '&lt;')
              .replace(/>/g, '&gt;')
              .replace(/"/g, '&quot;');
            // URLs → clickable links (only http/https, no javascript:)
            s = s.replace(
              /\bhttps?:\/\/[^\s&lt;]+/g,
              m => '<a href="' + m + '" target="_blank" rel="noopener noreferrer" style="color:#6ab3e8">' + m + '</a>'
            );
            // /commands → clickable (sends the command via data attribute, no href)
            s = s.replace(
              /(^|[\s])(\/([\w_]+))/gm,
              '$1<a href="#" class="llming-wire-cmd-link" data-cmd="/$3" style="color:#6ab3e8;cursor:pointer" onclick="return false">$2</a>'
            );
            // **bold** → <b> (safe, no nesting exploits with escaped HTML)
            s = s.replace(/\*\*(.+?)\*\*/g, '<b>$1</b>');
            return s;
          },

          formatTime(ts) {
            if (!ts) return '';
            return new Date(ts * 1000).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
          },

          formatDate(ts) {
            if (!ts) return '';
            const d = new Date(ts);
            const now = new Date();
            if (d.toDateString() === now.toDateString()) return this.formatTime(ts / 1000);
            return d.toLocaleDateString([], { month: 'short', day: 'numeric' });
          },

          apiUrl(path) {
            const base = document.querySelector('base');
            const prefix = base ? base.getAttribute('href') : '/';
            return prefix + 'api/llmings/llming-wire/' + path;
          },
        },
      });
    }

    renderThumbnail(ctx, w, h) {
      ctx.fillStyle = '#0e1621';
      ctx.fillRect(0, 0, w, h);
      const bubbles = [
        { y: 30, w: 120, text: 'How\u2019s the server?', user: true },
        { y: 70, w: 150, text: 'All good \u2014 CPU 12%', user: false },
        { y: 115, w: 80, text: 'Thanks!', user: true },
      ];
      for (const b of bubbles) {
        const bx = b.user ? 12 : w - b.w - 12;
        ctx.fillStyle = b.user ? '#2b5278' : '#182533';
        ctx.beginPath(); ctx.roundRect(bx, b.y, b.w, 28, 8); ctx.fill();
        ctx.fillStyle = b.user ? '#93c5fd' : '#94a3b8';
        ctx.font = '11px system-ui'; ctx.textAlign = 'left';
        ctx.fillText(b.text, bx + 8, b.y + 18);
      }
      ctx.fillStyle = '#17212b';
      ctx.fillRect(0, h - 30, w, 30);
      ctx.beginPath(); ctx.roundRect(8, h - 26, w - 50, 20, 6); ctx.fill();
      ctx.fillStyle = '#4a6580'; ctx.font = '10px system-ui';
      ctx.fillText('Type a message...', 16, h - 12);
    }
  }

  LlmingClient.register(LlmingWirePanel);
})();
