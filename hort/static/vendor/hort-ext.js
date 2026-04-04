/**
 * hort-ext.js — Client-side extension base for openhort.
 *
 * Extensions that provide UI panels inherit from HortExtension and
 * register Quasar/Vue components.  The host app loads extensions
 * dynamically and mounts their panels into the viewer.
 *
 * Usage (inside an extension's panel.js):
 *
 *   class MyPanel extends HortExtension {
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
 *   HortExtension.register(MyPanel);
 */

/* global Vue, Quasar */

(function (root) {
  'use strict';

  /** @type {Map<string, typeof HortExtension>} */
  const _registry = new Map();

  /** @type {Map<string, HortExtension>} */
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
  class HortExtension {
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
     * Float window sizing — read from extension.json ``ui_float`` field.
     * Values are viewport-relative (pct) with absolute minimums (px).
     * Set via manifest, not hardcoded in JS.
     *
     * Defaults: 30% width, 65% height, min 320x400.
     */
    static ui_float = null;  // set from extension.json

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
     * @param {typeof HortExtension} ExtClass
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
     * Get a running extension instance by id.
     *
     * @param {string} id
     * @returns {HortExtension|undefined}
     */
    static get(id) {
      return _instances.get(id);
    }

    /**
     * Get all registered extension classes.
     *
     * @returns {Map<string, typeof HortExtension>}
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
     * @param {typeof HortExtension} ExtClass
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
  HortExtension._floatChangeCallback = null;

  HortExtension.openFloat = function (id, widgetName, opts) {
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
    if (HortExtension._floatChangeCallback) HortExtension._floatChangeCallback();
    return win;
  };

  HortExtension.closeFloat = function (id) {
    _floatWindows.delete(id);
    if (HortExtension._floatChangeCallback) HortExtension._floatChangeCallback();
  };

  HortExtension.isFloatOpen = function (id) {
    return _floatWindows.has(id);
  };

  HortExtension.getFloatWindows = function () {
    return Array.from(_floatWindows.values());
  };

  /**
   * Promote a floating window to fullscreen.
   * Closes the float and opens the llming in fullscreen view.
   * The llming calls this when it needs more space (e.g., viewer mode).
   */
  HortExtension.promoteToFullscreen = function (id) {
    HortExtension.closeFloat(id);
    // The host app listens for this and opens fullscreen
    if (HortExtension._promoteCallback) {
      HortExtension._promoteCallback(id);
    }
  };

  HortExtension._promoteCallback = null;

  HortExtension.toggleMinimize = function (id) {
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
    if (HortExtension._floatChangeCallback) HortExtension._floatChangeCallback();
  };

  // ---- Shared components ----

  /**
   * Register shared UI components available to all extensions.
   * Called by HortExtension.activateAll() automatically.
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
  HortExtension._registerSharedComponents = function (app) {
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
  HortExtension._registerSharedComponents_extra = function (app) {
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
  const _origActivateAll = HortExtension.activateAll;
  HortExtension.activateAll = function (app, Quasar, configs) {
    HortExtension._registerSharedComponents(app);
    HortExtension._registerSharedComponents_extra(app);
    _origActivateAll.call(this, app, Quasar, configs);
  };

  /** Base path for API calls (empty string when local, proxy prefix when remote). */
  HortExtension.basePath = _basePath;

  // Expose globally
  root.HortExtension = HortExtension;

})(typeof globalThis !== 'undefined' ? globalThis : window);
