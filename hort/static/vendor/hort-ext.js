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
  }

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

  // Patch activateAll to also register shared components
  const _origActivateAll = HortExtension.activateAll;
  HortExtension.activateAll = function (app, Quasar, configs) {
    HortExtension._registerSharedComponents(app);
    _origActivateAll.call(this, app, Quasar, configs);
  };

  /** Base path for API calls (empty string when local, proxy prefix when remote). */
  HortExtension.basePath = _basePath;

  // Expose globally
  root.HortExtension = HortExtension;

})(typeof globalThis !== 'undefined' ? globalThis : window);
