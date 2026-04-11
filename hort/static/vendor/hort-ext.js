/**
 * hort-ext.js — Client-side extension base for openhort.
 *
 * Extensions that provide UI panels inherit from LlmingClient and
 * register Quasar/Vue components.  The host app loads extensions
 * dynamically and mounts their panels into the viewer.
 *
 * Usage (inside an extension's cards.js):
 *
 *   class MyPanel extends LlmingClient {
 *     static id   = 'my-panel';
 *     static name = 'My Panel';
 *
 *     setup(app, Quasar) {
 *       // Register Vue component(s)
 *       app.component('my-panel', {
 *         template: `<q-card><q-card-section>Hello</q-card-section></q-card>`,
 *         setup() { ... }
 *       });
 *     }
 *   }
 *   LlmingClient.register(MyPanel);
 */

/* global Vue, Quasar */

(function (root) {
  'use strict';

  /** @type {Map<string, typeof LlmingClient>} */
  const _registry = new Map();

  /** @type {Map<string, LlmingClient>} */
  const _instances = new Map();

  // Detect proxy base path from <base> tag (injected by access server)
  const _bEl = typeof document !== 'undefined' && document.querySelector('base');
  const _basePath = _bEl ? new URL(_bEl.href).pathname.replace(/\/$/, '') : '';

  /**
   * Base class for all client-side extensions.
   *
   * Subclasses MUST define static `id` and `name` properties.
   * They SHOULD override `setup()` to register Vue/Quasar components
   * and `destroy()` to clean up.
   */
  class LlmingClient {
    /** Llming title shown in the launcher (set to enable llming mode). */
    static llmingTitle = '';

    /** Phosphor icon class for the grid card (e.g. 'ph ph-chart-bar'). */
    static llmingIcon = 'ph ph-puzzle-piece';

    /** Description shown in the launcher. */
    static llmingDescription = '';

    /** Widget component names this llming provides (for inline rendering). */
    static llmingWidgets = [];

    /** Auto-show UI in the grid on startup (like auto-launching a window). */
    static autoShow = false;

    /**
     * Device types this llming's UI is optimized for.
     *
     * Set by the llming author:
     * - ``['phone']``                  — phone-only UI (e.g. simple chat)
     * - ``['phone', 'tablet']``        — mobile optimized
     * - ``['desktop']``                — desktop-only (e.g. complex editor)
     * - ``['phone', 'tablet', 'desktop']`` — works everywhere (default)
     *
     * The system uses this + available screen space to decide presentation:
     * - If there's enough space → float (stays on grid as overlay)
     * - If screen is too small → fullscreen (own page with back button)
     */
    static deviceTypes = ['phone', 'tablet', 'desktop'];

    /**
     * Float window sizing — read from manifest.json ``ui_float`` field.
     * Values are viewport-relative (pct) with absolute minimums (px).
     * Set via manifest, not hardcoded in JS.
     *
     * Defaults: 30% width, 65% height, min 320x400.
     */
    static ui_float = null;  // set from manifest.json

    /** Unique extension identifier (kebab-case, must match server-side name). */
    static id = '';

    /** Human-readable display name shown in the UI. */
    static name = '';

    /** Extension configuration (set by the host before activate). */
    config = {};

    // ---- Lifecycle ----

    /**
     * Called once when the extension is mounted into the Vue app.
     * Override to register components, routes, and set up watchers.
     *
     * @param {import('vue').App} app - The Vue application instance.
     * @param {object} Quasar - The Quasar framework object.
     */
    setup(app, Quasar) {} // eslint-disable-line no-unused-vars

    /**
     * Called when the extension is about to be unloaded.
     * Override to tear down event listeners, intervals, etc.
     */
    destroy() {}

    /**
     * Render a thumbnail preview for the grid card.
     *
     * Override to draw plugin status into a standardized 320×200 canvas.
     * The host calls this every ~5s for active plugins. The result is
     * displayed as the grid card thumbnail (same position as window screenshots).
     *
     * @param {CanvasRenderingContext2D} ctx - 2D context (320×200 canvas)
     * @param {number} width - Canvas width (320)
     * @param {number} height - Canvas height (200)
     */
    renderThumbnail(ctx, width, height) {
      // Default: icon + name centered
      ctx.fillStyle = getComputedStyle(document.documentElement)
        .getPropertyValue('--el-surface').trim() || '#111827';
      ctx.fillRect(0, 0, width, height);
      ctx.fillStyle = getComputedStyle(document.documentElement)
        .getPropertyValue('--el-text-dim').trim() || '#94a3b8';
      ctx.font = '14px system-ui';
      ctx.textAlign = 'center';
      ctx.fillText(this.constructor.name || this.constructor.id, width / 2, height / 2);
    }

    // ---- API helpers ----

    /**
     * Fetch JSON from the server (auto-prefixes /api/ext/<id>/).
     *
     * @param {string} path - Relative path (e.g. "data" → /api/ext/my-ext/data).
     * @param {RequestInit} [opts] - Fetch options.
     * @returns {Promise<any>}
     */
    async api(path, opts) {
      const url = `${location.origin}${_basePath}/api/ext/${this.constructor.id}/${path}`;
      const resp = await fetch(url, opts);
      return resp.json();
    }

    /**
     * POST JSON to the extension's server-side API.
     *
     * @param {string} path - Relative path.
     * @param {object} body - JSON body.
     * @returns {Promise<any>}
     */
    async apiPost(path, body) {
      return this.api(path, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });
    }

    /**
     * Open a WebSocket to the extension's server-side endpoint.
     *
     * @param {string} path - Relative path (e.g. "stream").
     * @returns {WebSocket}
     */
    ws(path) {
      const proto = location.protocol === 'https:' ? 'wss' : 'ws';
      return new WebSocket(`${proto}://${location.host}${_basePath}/ws/ext/${this.constructor.id}/${path}`);
    }

    // ---- Card API (pulse, vaults, powers) ----

    /**
     * Subscribe to a named pulse channel. Server pushes events.
     *
     * @param {string} channel - Channel name (e.g. "disk_usage", "tick:1hz")
     * @param {function(object): void} handler - Called with event data
     */
    subscribe(channel, handler) {
      if (!this._pulseHandlers) this._pulseHandlers = {};
      if (!this._pulseHandlers[channel]) this._pulseHandlers[channel] = [];
      this._pulseHandlers[channel].push(handler);
      // Tell server to push events for this channel
      if (window.hortWS) {
        window.hortWS.request({ type: 'card.subscribe', channel });
      }
    }

    /**
     * Read from a vault (own or another llming's).
     *
     * @param {string} key - Key to read
     * @param {string} [owner] - Vault owner (default: own llming)
     * @returns {Promise<object>}
     */
    async vaultRead(key, owner) {
      if (!window.hortWS) return {};
      const msg = await window.hortWS.request({
        type: 'card.vault.read',
        owner: owner || this.constructor.id,
        key,
      });
      return msg && msg.data ? msg.data : {};
    }

    /**
     * Write to own vault.
     *
     * @param {string} key - Key to write
     * @param {object} data - Data to store
     */
    async vaultWrite(key, data) {
      if (!window.hortWS) return;
      await window.hortWS.request({
        type: 'card.vault.write',
        owner: this.constructor.id,
        key,
        data,
      });
    }

    /**
     * Execute a power on own llming or another llming.
     *
     * @param {string} power - Power name
     * @param {object} [args={}] - Arguments
     * @param {string} [llming] - Target llming (default: own)
     * @returns {Promise<object>}
     */
    async call(power, args, llming) {
      if (!window.hortWS) return { error: 'not connected' };
      const msg = await window.hortWS.request({
        type: 'card.power',
        llming: llming || this.constructor.id,
        power,
        args: args || {},
      });
      return msg && msg.result ? msg.result : msg;
    }

    /**
     * Query a scrolls collection.
     *
     * @param {string} collection - Collection name
     * @param {object} [filter={}] - MongoDB-style filter
     * @param {object} [opts={}] - { owner, limit }
     * @returns {Promise<object[]>}
     */
    async scrollsQuery(collection, filter, opts) {
      if (!window.hortWS) return [];
      const msg = await window.hortWS.request({
        type: 'card.scrolls.query',
        owner: (opts && opts.owner) || this.constructor.id,
        collection,
        filter: filter || {},
        limit: (opts && opts.limit) || 50,
      });
      return msg && msg.data ? msg.data : [];
    }

    /** @internal Handle incoming pulse push from server. */
    _handlePulse(channel, data) {
      const handlers = (this._pulseHandlers || {})[channel] || [];
      for (const h of handlers) {
        try { h(data); } catch (e) { console.error('[pulse]', channel, e); }
      }
    }

    // ---- Quasar helpers ----

    /**
     * Show a Quasar notification (toast).
     *
     * @param {string} message
     * @param {string} [type='info'] - 'positive' | 'negative' | 'warning' | 'info'
     */
    notify(message, type) {
      if (typeof Quasar !== 'undefined' && Quasar.Notify) {
        Quasar.Notify.create({ message, type: type || 'info', position: 'bottom' });
      }
    }

    // ---- Static registry ----

    /**
     * Register an extension class.  Called by each extension's script.
     *
     * @param {typeof LlmingClient} ExtClass
     */
    static register(ExtClass) {
      if (!ExtClass.id) throw new Error('Extension must define static id');
      _registry.set(ExtClass.id, ExtClass);
    }

    /**
     * Instantiate and activate all registered extensions.
     * Called by the host app after all extension scripts have loaded.
     *
     * @param {import('vue').App} app
     * @param {object} Quasar
     * @param {Object<string, object>} [configs={}] - Per-extension config.
     */
    static activateAll(app, Quasar, configs) {
      const cfgs = configs || {};
      for (const [id, ExtClass] of _registry) {
        if (_instances.has(id)) continue; // skip already activated
        const instance = new ExtClass();
        instance.config = cfgs[id] || {};
        instance.setup(app, Quasar);
        _instances.set(id, instance);
        // If WS already connected, fire onConnect immediately
        if (window.hortWS) {
          try { instance.onConnect(); } catch (e) { console.error('[ext:connect]', id, e); }
        }
      }
    }

    /**
     * Destroy and remove all active extension instances.
     */
    static destroyAll() {
      for (const [, instance] of _instances) {
        instance.destroy();
      }
      _instances.clear();
    }

    /**
     * Notify all active extensions that the WS connected.
     * Extensions override onConnect() for init that needs a live connection.
     */
    static notifyConnect() {
      for (const [, instance] of _instances) {
        try { instance.onConnect(); } catch (e) { console.error('[ext:connect]', e); }
      }
    }

    /** Override in subclass: called on every WS connect/reconnect. */
    onConnect() {}

    /** Override in subclass: called on WS disconnect. */
    onDisconnect() {}

    /**
     * Get a running extension instance by id.
     *
     * @param {string} id
     * @returns {LlmingClient|undefined}
     */
    static get(id) {
      return _instances.get(id);
    }

    /**
     * Get all registered extension classes.
     *
     * @returns {Map<string, typeof LlmingClient>}
     */
    static getRegistry() {
      return _registry;
    }

    // ---- Device detection ----

    /**
     * Detect the current device type from viewport size.
     *
     * @returns {'phone'|'tablet'|'desktop'}
     */
    static getDeviceType() {
      const w = window.innerWidth || 0;
      if (w < 820) return 'phone';
      if (w < 1024) return 'tablet';
      return 'desktop';
    }

    /**
     * Determine how a llming should open based on available screen space.
     *
     * Rules:
     * - If viewport has room for a floating overlay (>= 640px wide AND
     *   >= 500px tall) → float (overlay on the grid)
     * - If viewport is too small (phone) → fullscreen (own page, back button)
     *
     * The llming's ``deviceTypes`` is informational — it tells the system
     * what the UI was designed for, not how to display it.
     *
     * @param {typeof LlmingClient} ExtClass
     * @returns {'fullscreen'|'float'}
     */
    static resolveDisplayMode(ExtClass) {
      // Fullscreen-capable llmings (e.g. llming-lens viewer) always go fullscreen
      if (ExtClass.fullscreenCapable) return 'fullscreen';
      const w = window.innerWidth || 0;
      const h = window.innerHeight || 0;
      // Float only on screens with enough room (desktop / landscape tablet)
      if (w >= 1024 && h >= 600) return 'float';
      return 'fullscreen';
    }
  }

  // ── Shared floating window state ────────────────────────────────
  //
  // Float windows are rendered by the Vue app (not raw DOM), so Vue
  // components mount correctly.  This just manages the open/close state.

  const _floatWindows = new Map(); // id → { widgetName, title, minimized }

  /** Reactive callback — the Vue app watches this to render floats. */
  LlmingClient._floatChangeCallback = null;

  LlmingClient.openFloat = function (id, widgetName, opts) {
    const o = opts || {};
    if (_floatWindows.has(id)) return _floatWindows.get(id);
    const ExtClass = _registry.get(id);
    const vw = window.innerWidth || 800;
    const vh = window.innerHeight || 600;

    // Read sizing from extension's ui_float (manifest) or use defaults
    const uf = ExtClass?.ui_float || o.ui_float || {};
    const wpct = uf.width_pct || 30;
    const hpct = uf.height_pct || 65;
    const minW = uf.min_width || 320;
    const minH = uf.min_height || 400;

    // Compute from viewport percentage, clamp to min/max
    const fw = Math.max(minW, Math.min(Math.round(vw * wpct / 100), vw - 40));
    const fh = Math.max(minH, Math.min(Math.round(vh * hpct / 100), vh - 40));

    // Center on screen
    const cx = Math.round((vw - fw) / 2);
    const cy = Math.round((vh - fh) / 2);

    const win = {
      id, widgetName,
      title: o.title || id,
      width: fw, height: fh,
      minWidth: minW, minHeight: minH,
      minimized: false,
      x: cx, y: cy,
    };
    _floatWindows.set(id, win);
    if (LlmingClient._floatChangeCallback) LlmingClient._floatChangeCallback();
    return win;
  };

  LlmingClient.closeFloat = function (id) {
    _floatWindows.delete(id);
    if (LlmingClient._floatChangeCallback) LlmingClient._floatChangeCallback();
  };

  LlmingClient.isFloatOpen = function (id) {
    return _floatWindows.has(id);
  };

  LlmingClient.getFloatWindows = function () {
    return Array.from(_floatWindows.values());
  };

  /**
   * Promote a floating window to fullscreen.
   * Closes the float and opens the llming in fullscreen view via the router.
   */
  LlmingClient.promoteToFullscreen = function (id) {
    LlmingClient.closeFloat(id);
    var provider = LlmingClient.getProvider(id);
    LlmingClient.navigate('/llming/' + provider + '/' + id);
  };

  LlmingClient.toggleMinimize = function (id) {
    const win = _floatWindows.get(id);
    if (!win) return;
    if (!win.minimized) {
      // Save position before minimizing
      win._savedX = win.x;
      win._savedY = win.y;
      // Move to bottom center
      const vw = window.innerWidth || 800;
      win.x = Math.round((vw - 240) / 2);
      win.y = (window.innerHeight || 600) - 44;
      win.minimized = true;
    } else {
      // Restore to saved position
      win.x = win._savedX ?? win.x;
      win.y = win._savedY ?? win.y;
      win.minimized = false;
    }
    if (LlmingClient._floatChangeCallback) LlmingClient._floatChangeCallback();
  };

  // ---- Shared components ----

  /**
   * Register shared UI components available to all extensions.
   * Called by LlmingClient.activateAll() automatically.
   *
   * **hort-qr** — QR code display with clickable URL.
   *
   * Props:
   *   - url (String, required) — the URL to encode as QR code
   *   - label (String) — caption below the QR code (default: "Scan to open")
   *   - maxUrlLen (Number) — truncate displayed URL after this length (default: 60)
   *
   * Example:
   *   <hort-qr :url="myLoginUrl" label="Scan with your phone" />
   */
  LlmingClient._registerSharedComponents = function (app) {
    app.component('hort-qr', {
      props: {
        url: { type: String, required: true },
        label: { type: String, default: 'Scan to open' },
        maxUrlLen: { type: Number, default: 200 },
      },
      setup(props) {
        const qrImage = Vue.ref('');

        Vue.watch(() => props.url, async (url) => {
          if (!url) { qrImage.value = ''; return; }
          try {
            const resp = await fetch(_basePath + '/api/qr?url=' + encodeURIComponent(url));
            if (resp.ok) { qrImage.value = (await resp.json()).qr || ''; }
          } catch { qrImage.value = ''; }
        }, { immediate: true });

        const displayUrl = Vue.computed(() => {
          const u = props.url || '';
          return u.length > props.maxUrlLen ? u.slice(0, props.maxUrlLen) + '...' : u;
        });

        return { qrImage, displayUrl };
      },
      template: `
        <div v-if="url" style="text-align:center">
          <div v-if="qrImage" class="qr-wrap"><img :src="qrImage" alt="QR Code"></div>
          <div v-if="label" style="color:var(--el-text-dim);font-size:11px;margin:4px 0">{{ label }}</div>
          <a :href="url" target="_blank" rel="noopener"
             style="color:var(--el-primary);font-size:11px;word-break:break-all;text-decoration:none"
             :title="url">{{ displayUrl }}</a>
        </div>
      `,
    });
  };

  /**
   * hort-tile-grid — Reusable grid/list of cards with thumbnails.
   *
   * Props:
   *   - items (Array, required): [{id, title, subtitle, icon, thumbnail}]
   *     - thumbnail: base64 JPEG string or data URL
   *   - mode (String): 'grid' (default) or 'list'
   *   - columns (Number): grid columns (default: auto based on width)
   *
   * Events:
   *   - @select(item): emitted when a card is clicked
   *
   * Example:
   *   <hort-tile-grid :items="screens" @select="onSelect" />
   */
  LlmingClient._registerSharedComponents_extra = function (app) {
    app.component('hort-tile-grid', {
      props: {
        items: { type: Array, required: true },
        mode: { type: String, default: 'grid' },
        columns: { type: Number, default: 0 },
      },
      emits: ['select'],
      template: `
        <div :class="mode === 'list' ? 'hort-tile-list' : 'hort-tile-grid'" :style="gridStyle">
          <div v-for="item in items" :key="item.id"
               class="hort-tile-card"
               :class="{ 'list-item': mode === 'list' }"
               @click="$emit('select', item)">
            <div class="hort-tile-thumb" v-if="mode !== 'list'">
              <img v-if="item.thumbnail" :src="thumbSrc(item)" alt="" />
              <div v-else class="hort-tile-icon">
                <i :class="item.icon || 'ph ph-image'" style="font-size:32px"></i>
              </div>
            </div>
            <div class="hort-tile-info">
              <i v-if="mode === 'list' && item.icon" :class="item.icon" style="font-size:20px;flex-shrink:0"></i>
              <div>
                <div class="hort-tile-title">{{ item.title }}</div>
                <div v-if="item.subtitle" class="hort-tile-subtitle">{{ item.subtitle }}</div>
              </div>
            </div>
          </div>
        </div>
      `,
      setup(props) {
        function thumbSrc(item) {
          if (!item.thumbnail) return '';
          if (item.thumbnail.startsWith('data:')) return item.thumbnail;
          return 'data:image/jpeg;base64,' + item.thumbnail;
        }
        const gridStyle = Vue.computed(() => {
          if (props.mode === 'list') return {};
          const cols = props.columns || 'auto-fill';
          return {
            display: 'grid',
            gridTemplateColumns: typeof cols === 'number' && cols > 0
              ? `repeat(${cols}, 1fr)`
              : 'repeat(auto-fill, minmax(200px, 1fr))',
            gap: '12px',
          };
        });
        return { thumbSrc, gridStyle };
      },
    });
  };

  // Inject CSS for hort-tile-grid
  if (typeof document !== 'undefined') {
    const style = document.createElement('style');
    style.textContent = `
      .hort-tile-grid { padding: 0; }
      .hort-tile-list { display: flex; flex-direction: column; gap: 8px; }
      .hort-tile-card {
        background: var(--el-surface, #16213e);
        border: 1px solid var(--el-border, #2a3a5a);
        border-radius: 8px;
        cursor: pointer;
        overflow: hidden;
        transition: border-color 0.15s;
      }
      .hort-tile-card:hover { border-color: var(--el-primary, #7c4dff); }
      .hort-tile-card.list-item {
        display: flex;
        align-items: center;
        gap: 12px;
        padding: 12px 16px;
      }
      .hort-tile-thumb {
        width: 100%;
        aspect-ratio: 16/9;
        background: var(--el-bg, #0f1724);
        display: flex;
        align-items: center;
        justify-content: center;
        overflow: hidden;
      }
      .hort-tile-thumb img { width: 100%; height: 100%; object-fit: cover; }
      .hort-tile-icon { color: var(--el-text-dim, #666); }
      .hort-tile-info { padding: 8px 10px; }
      .hort-tile-card.list-item .hort-tile-info { padding: 0; display: flex; align-items: center; gap: 10px; }
      .hort-tile-title { font-size: 13px; font-weight: 600; color: var(--el-text, #e0e0e0); }
      .hort-tile-subtitle { font-size: 11px; color: var(--el-text-dim, #888); margin-top: 2px; }
    `;
    document.head.appendChild(style);
  }

  // Patch activateAll to also register shared components
  const _origActivateAll = LlmingClient.activateAll;
  LlmingClient.activateAll = function (app, Quasar, configs) {
    LlmingClient._registerSharedComponents(app);
    LlmingClient._registerSharedComponents_extra(app);
    _origActivateAll.call(this, app, Quasar, configs);
  };

  /** Base path for API calls (empty string when local, proxy prefix when remote). */
  LlmingClient.basePath = _basePath;

  // ── Navigation API ─────────────────────────────────────────────
  //
  // Extensions use these instead of touching state.view directly.
  // Backed by HortRouter (hort-router.js), which must be loaded first
  // or at the same time.

  /** @type {Object<string, string>} id → provider mapping */
  const _providerMap = {};

  /**
   * Store the provider for an extension (called during plugin discovery).
   * @param {string} id - Extension id (e.g. 'llming-lens')
   * @param {string} provider - Provider namespace (e.g. 'core')
   */
  LlmingClient.setProvider = function (id, provider) {
    _providerMap[id] = provider;
  };

  /**
   * Get the provider for an extension.
   * @param {string} id
   * @returns {string} provider (defaults to 'core')
   */
  LlmingClient.getProvider = function (id) {
    return _providerMap[id] || 'core';
  };

  /**
   * Navigate to a route. Extensions use this instead of touching state.view.
   * @param {string} path - Hash path, e.g. '/core/llming-wire'
   */
  LlmingClient.navigate = function (path) {
    if (root.HortRouter) root.HortRouter.push(path);
  };

  /**
   * Go back in navigation history.
   * @returns {boolean} false if already at root
   */
  LlmingClient.back = function () {
    if (root.HortRouter) return root.HortRouter.back();
    return false;
  };

  /**
   * Open the viewer for a specific window (llming-lens/screens sub-route).
   * @param {number} windowId - OS window ID (-1 for desktop)
   * @param {string} [targetId] - Target machine ID
   */
  LlmingClient.openViewer = function (windowId, targetId) {
    var provider = LlmingClient.getProvider('llming-lens');
    var path = '/llming/' + provider + '/llming-lens/screens/' + windowId;
    if (targetId) path += '?target=' + encodeURIComponent(targetId);
    LlmingClient.navigate(path);
  };

  /**
   * Open a terminal session.
   * @param {string} terminalId
   */
  LlmingClient.openTerminal = function (terminalId) {
    var provider = LlmingClient.getProvider('terminal');
    LlmingClient.navigate('/llming/' + provider + '/terminal/' + terminalId);
  };

  /**
   * Open a llming by id (fullscreen or float based on screen size).
   * @param {string} id - Extension id (e.g. 'llming-wire')
   * @param {string} [sub] - Optional sub-route
   */
  LlmingClient.openLlming = function (id, sub) {
    var ExtClass = _registry.get(id);
    if (!sub && ExtClass && ExtClass.llmingWidgets && ExtClass.llmingWidgets.length) {
      var mode = LlmingClient.resolveDisplayMode(ExtClass);
      if (mode === 'float') {
        LlmingClient.openFloat(id, ExtClass.llmingWidgets[0], {
          title: ExtClass.llmingTitle || ExtClass.name || id,
        });
        return;
      }
    }
    var provider = LlmingClient.getProvider(id);
    var path = '/llming/' + provider + '/' + id;
    if (sub != null) path += '/' + encodeURIComponent(String(sub));
    LlmingClient.navigate(path);
  };

  // Expose globally
  root.LlmingClient = LlmingClient;

})(typeof globalThis !== 'undefined' ? globalThis : window);
