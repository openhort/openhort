/* card-shim.js — runs INSIDE a sandboxed card iframe.
 *
 * Provides drop-in shims for everything a card.vue might use:
 *   - window.LlmingClient (register, openSubapp, openLlming, etc.)
 *   - window.useStream / vaultRef (closures injected by vue_loader)
 *   - $llming (vault, subscribe, call, callOn, local)
 *
 * Every operation goes through postMessage to the host bridge — the
 * iframe has no other way out (opaque origin, no cookies, no host DOM).
 *
 * See docs/manual/internals/security/card-sandbox.md for the protocol.
 */

(function (root) {
  'use strict';

  // --- RPC ---------------------------------------------------------------

  let _seq = 0;
  const _pending = new Map();   // id → resolve

  function rpc(op, payload) {
    const id = ++_seq;
    return new Promise((resolve) => {
      _pending.set(id, resolve);
      try { window.parent.postMessage(Object.assign({ id, op }, payload), '*'); } catch {}
      // Timeout fallback to keep the page alive if the host disappears
      setTimeout(() => { if (_pending.has(id)) { _pending.delete(id); resolve({ ok: false, error: 'timeout' }); } }, 10000);
    });
  }

  // --- Push handlers ------------------------------------------------------

  const _vaultListeners = new Map();   // "owner:key" → Set of (data) => void
  const _pulseListeners = new Map();   // channel → Set of (payload) => void
  const _streamListeners = new Map();  // channel → Set of (data) => void
  const _localListeners = new Map();   // key → Set of (data) => void

  function _onPush(msg) {
    if (msg.op === 'vault.update') {
      const set = _vaultListeners.get(msg.namespace + ':' + msg.key);
      if (set) for (const fn of set) try { fn(msg.data); } catch {}
    } else if (msg.op === 'pulse.event') {
      const set = _pulseListeners.get(msg.channel);
      if (set) for (const fn of set) try { fn(msg.payload); } catch {}
    } else if (msg.op === 'stream.frame') {
      const set = _streamListeners.get(msg.channel);
      if (set) for (const fn of set) try { fn(msg.data); } catch {}
    } else if (msg.op === 'local.update') {
      const set = _localListeners.get(msg.key);
      if (set) for (const fn of set) try { fn(msg.data); } catch {}
    }
  }

  window.addEventListener('message', (e) => {
    if (e.source !== window.parent) return;
    const msg = e.data;
    if (!msg || typeof msg !== 'object') return;
    if (msg.id != null && _pending.has(msg.id)) {
      const resolve = _pending.get(msg.id);
      _pending.delete(msg.id);
      resolve(msg);
    } else if (msg.op) {
      _onPush(msg);
    }
  });

  // --- LlmingClient shim --------------------------------------------------

  const _registry = new Map();   // class id → ExtClass
  const _instances = new Map();  // id → instance
  let _myLlmingId = '';

  class LlmingClient {
    static id = '';
    static cardComponent = '';
    static llmingWidgets = [];

    static register(ExtClass) {
      if (!ExtClass.id) throw new Error('Extension must define static id');
      _registry.set(ExtClass.id, ExtClass);
    }
    static getRegistry() { return _registry; }
    static get(id) { return _instances.get(id); }
    static activateAll(app, Quasar, configs) {
      const cfgs = configs || {};
      for (const [id, ExtClass] of _registry) {
        if (_instances.has(id)) continue;
        const inst = new ExtClass();
        inst.config = cfgs[id] || {};
        if (typeof inst.setup === 'function') inst.setup(app, Quasar);
        _instances.set(id, inst);
      }
    }

    // Compatibility shims for vue_loader-generated code.
    // The generated `vaultRef` closure calls these directly; route them
    // through the same postMessage bridge as the standalone vaultRef().
    static _watchVault(owner, key, entry) {
      const k = owner + ':' + key;
      let set = _vaultListeners.get(k);
      if (!set) { set = new Set(); _vaultListeners.set(k, set); rpc('vault.watch', { namespace: owner, key }); }
      const handler = (data) => {
        const nv = entry.extract ? entry.extract(data) : data;
        const nj = JSON.stringify(nv);
        if (entry.lastJson !== nj) {
          if (entry.ref) entry.ref.value = nv;
          entry.lastJson = nj;
          if (entry.onChange) try { entry.onChange(nv); } catch {}
        }
      };
      entry.__handler = handler;
      set.add(handler);
    }
    static _unwatchVault(owner, key, entry) {
      const k = owner + ':' + key;
      const set = _vaultListeners.get(k);
      if (!set || !entry.__handler) return;
      set.delete(entry.__handler);
      if (!set.size) { _vaultListeners.delete(k); rpc('vault.unwatch', { namespace: owner, key }); }
    }
    static _notifyVaultUpdate() { /* host-only — no-op inside iframe */ }

    // Window opening — proxied to host
    static openSubapp(parentId, widget, props, opts) {
      rpc('subapp.open', { widget, props: props || {}, opts: opts || {} });
    }
    static openLlming(id, sub) {
      rpc('app.open', { llming: id, sub });
    }
    static closeFloat() { /* host-managed; no-op from inside */ }
    static getFloatWindows() { return []; }

    // Optional chrome
    static basePath = '';
    static setProvider() {}
    static getProvider() { return ''; }
    static navigate(path) { rpc('navigate', { path }); }

    // Per-instance vault helper
    get vault() {
      const id = this.constructor.id;
      return {
        async get(key, dflt) {
          const r = await rpc('vault.read', { namespace: id, key });
          return (r.ok && r.data !== undefined) ? r.data : (dflt || {});
        },
        async set(key, data, ttl) { await rpc('vault.write', { namespace: id, key, data, ttl: ttl || null }); },
        async delete(key) { await rpc('vault.write', { namespace: id, key, data: null }); },
      };
    }

    vaults(owner) {
      return {
        async get(key, dflt) {
          const r = await rpc('vault.read', { namespace: owner, key });
          return (r.ok && r.data !== undefined) ? r.data : (dflt || {});
        },
      };
    }

    subscribe(channel, fn) {
      let set = _pulseListeners.get(channel);
      if (!set) { set = new Set(); _pulseListeners.set(channel, set); rpc('pulse.subscribe', { channel }); }
      set.add(fn);
      return () => set.delete(fn);
    }

    async call(power, args) {
      const r = await rpc('power.call', { llming: this.constructor.id, power, args: args || {} });
      return r.result;
    }
    async callOn(llming, power, args) {
      const r = await rpc('power.call', { llming, power, args: args || {} });
      return r.result;
    }
  }

  // --- useStream / vaultRef / $llming (the closures vue_loader injects) ---

  function useStream(channel, opts) {
    const Vue = root.Vue;
    const frame = Vue.ref(null);
    const active = Vue.ref(false);

    let _ready = true;
    let _pendingFrame = null;

    function _deliver(url) {
      _ready = false;
      if (frame.value && typeof frame.value === 'string' && frame.value.startsWith('blob:')) {
        URL.revokeObjectURL(frame.value);
      }
      frame.value = url;
      active.value = true;
      let fired = false;
      function ack() {
        if (fired) return;
        fired = true;
        _ready = true;
        rpc('stream.ack', { channel });
        if (_pendingFrame) { const p = _pendingFrame; _pendingFrame = null; _deliver(p); }
      }
      requestAnimationFrame(ack);
      setTimeout(ack, 250);
    }

    let set = _streamListeners.get(channel);
    if (!set) { set = new Set(); _streamListeners.set(channel, set); rpc('stream.subscribe', { channel, opts: opts || {} }); }
    const handler = (data) => {
      // Bridge sends Blob objects (origin-bound URLs can't cross the
      // sandbox boundary); turn them into our own origin's blob URL.
      let url = data;
      if (data instanceof Blob) {
        url = URL.createObjectURL(data);
      }
      if (!_ready) { _pendingFrame = url; return; }
      _deliver(url);
    };
    set.add(handler);
    if (Vue.onUnmounted) Vue.onUnmounted(() => set.delete(handler));

    return { frame, active };
  }

  function vaultRef(owner, path, defaultValue) {
    const Vue = root.Vue;
    const ref = Vue.ref(defaultValue);
    const dot = path.indexOf('.');
    const vkey = dot >= 0 ? path.slice(0, dot) : path;
    const props = dot >= 0 ? path.slice(dot + 1).split('.') : [];

    function extract(d) {
      let v = d;
      for (const p of props) { if (v == null) return defaultValue; v = v[p]; }
      return v ?? defaultValue;
    }

    const key = owner + ':' + vkey;
    let listeners = _vaultListeners.get(key);
    if (!listeners) { listeners = new Set(); _vaultListeners.set(key, listeners); rpc('vault.watch', { namespace: owner, key: vkey }); }
    const handler = (data) => { ref.value = extract(data); };
    listeners.add(handler);
    if (Vue.onUnmounted) Vue.onUnmounted(() => {
      listeners.delete(handler);
      if (!listeners.size) { _vaultListeners.delete(key); rpc('vault.unwatch', { namespace: owner, key: vkey }); }
    });
    return ref;
  }

  // $llming-style local store helpers
  const local = {
    async get(key, dflt) { const r = await rpc('local.read', { key }); return (r.ok && r.data !== undefined) ? r.data : dflt; },
    async set(key, data) { const r = await rpc('local.write', { key, data }); return r.ok; },
    async delete(key) { const r = await rpc('local.delete', { key }); return r.ok; },
    async keys() { const r = await rpc('local.keys'); return (r.ok && r.data) || []; },
  };

  // localRef — Vue.ref backed by $llming.local with cross-iframe sync.
  // Every iframe of the same llming reads from / writes to the same host
  // IndexedDB row, and the bridge pushes `local.update` to all of them on
  // every write. So a widget changing this value is seen by an open
  // subapp/fullscreen of the same llming on the next tick, and vice versa.
  function localRef(key, defaultValue) {
    const Vue = root.Vue;
    const ref = Vue.ref(defaultValue);
    let writingFromHere = false;

    let set = _localListeners.get(key);
    if (!set) { set = new Set(); _localListeners.set(key, set); }
    const handler = (data) => {
      if (writingFromHere) return;  // suppress echo from our own local.write
      ref.value = (data === undefined) ? defaultValue : data;
    };
    set.add(handler);

    // Seed initial value (host returns current value with the watch ack)
    rpc('local.watch', { key }).then(r => {
      if (r.ok && r.data !== undefined) ref.value = r.data;
    });

    // Vue.watch(ref, …) would be nice but we want Vue available without
    // forcing the import. Manually mirror writes by exposing a setter
    // wrapper on the ref's value via Vue.watch when available.
    if (Vue.watch) {
      Vue.watch(ref, async (nv) => {
        writingFromHere = true;
        try { await rpc('local.write', { key, data: nv }); }
        finally { setTimeout(() => { writingFromHere = false; }, 0); }
      }, { deep: true });
    }
    if (Vue.onUnmounted) Vue.onUnmounted(() => {
      set.delete(handler);
      if (!set.size) _localListeners.delete(key);
    });
    return ref;
  }

  // --- Close interception (apps with unsaved state can veto) -------------

  const _beforeCloseHandlers = new Set();

  /**
   * Register a handler that runs before the host closes this app.
   * Return `true` (or a truthy value) / Promise<true> to allow the close.
   * Return `false` to veto — the app then OWNS the close flow (show its
   * own dialog, then call `$llming.closeSelf()` to actually close).
   * Returning a value within ~200 ms keeps the UX snappy; if no handler
   * responds in time, close proceeds.
   */
  function onBeforeClose(handler) {
    _beforeCloseHandlers.add(handler);
    const Vue = root.Vue;
    if (Vue && Vue.onUnmounted) Vue.onUnmounted(() => _beforeCloseHandlers.delete(handler));
    return () => _beforeCloseHandlers.delete(handler);
  }

  // App can request its own close (bypasses onBeforeClose hooks for the
  // SAME instance, since we treat closeSelf as "I already handled it").
  function closeSelf() { rpc('app.closeSelf', {}); }

  window.addEventListener('message', async (e) => {
    if (e.source !== window.parent) return;
    const m = e.data;
    if (!m || m.op !== 'app.beforeClose') return;
    let allow = true;
    for (const h of _beforeCloseHandlers) {
      try {
        const r = await h();
        if (r === false) { allow = false; break; }
      } catch (err) { /* swallow handler errors — don't block close */ }
    }
    try {
      window.parent.postMessage({ op: 'app.beforeCloseResponse', requestId: m.requestId, allow }, '*');
    } catch {}
  });

  // --- Activate registered cards into the iframe's Vue app ----------------

  function activateInto(app, Quasar) {
    // Build a synthetic LlmingClient instance bound to this iframe's
    // llming id, then expose its vault/subscribe/call surface as $llming.
    // Activation also registers any Vue components the card declared.
    LlmingClient.activateAll(app, Quasar, {});
    const fakeCard = Object.create(LlmingClient.prototype);
    Object.defineProperty(fakeCard, 'constructor', { value: { id: _myLlmingId } });
    const $llming = {
      name: _myLlmingId,
      vault: fakeCard.vault,
      vaults: (owner) => fakeCard.vaults(owner),
      subscribe: (ch, fn) => fakeCard.subscribe(ch, fn),
      call: (power, args) => fakeCard.call(power, args),
      callOn: (llming, power, args) => fakeCard.callOn(llming, power, args),
      local,
      localRef,
      onBeforeClose,
      closeSelf,
    };
    if (app.provide) app.provide('llming', $llming);
    app.config.globalProperties.$llming = $llming;
    app.config.globalProperties.LlmingClient = LlmingClient;
  }

  // --- Expose globals (the same names vue_loader expects) -----------------

  root.LlmingClient = LlmingClient;
  root.useStream = useStream;
  root.vaultRef = vaultRef;
  root.localRef = localRef;
  root.onBeforeClose = onBeforeClose;
  root.closeSelf = closeSelf;
  root.LlmingClientShim = {
    _setLlmingId(id) { _myLlmingId = id; LlmingClient.id = id; },
    activateInto,
  };

})(typeof globalThis !== 'undefined' ? globalThis : window);
