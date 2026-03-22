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

  /**
   * Base class for all client-side extensions.
   *
   * Subclasses MUST define static `id` and `name` properties.
   * They SHOULD override `setup()` to register Vue/Quasar components
   * and `destroy()` to clean up.
   */
  class HortExtension {
    /** Panel title shown in the "New Panel" dialog (set to enable panel mode). */
    static panelTitle = '';

    /** Phosphor icon class for the grid card (e.g. 'ph ph-chart-bar'). */
    static panelIcon = 'ph ph-puzzle-piece';

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

    // ---- API helpers ----

    /**
     * Fetch JSON from the server (auto-prefixes /api/ext/<id>/).
     *
     * @param {string} path - Relative path (e.g. "data" → /api/ext/my-ext/data).
     * @param {RequestInit} [opts] - Fetch options.
     * @returns {Promise<any>}
     */
    async api(path, opts) {
      const url = `${location.origin}/api/ext/${this.constructor.id}/${path}`;
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
      return new WebSocket(`${proto}://${location.host}/ws/ext/${this.constructor.id}/${path}`);
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

  // Expose globally
  root.HortExtension = HortExtension;

})(typeof globalThis !== 'undefined' ? globalThis : window);
