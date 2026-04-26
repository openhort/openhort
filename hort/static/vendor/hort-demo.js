/**
 * hort-demo.js — Demo mode runtime.
 *
 * Provides an in-memory mock of the openhort server: vault store,
 * pulse bus, vaultRef push, and power interception. Compiled Vue
 * SFC components work unchanged — the mock replaces the WS transport.
 *
 * Each llming can provide a demo.js with:
 *   vault     — initial vault data
 *   setup()   — async init (load files, seed data)
 *   teardown() — cleanup
 *   simulate() — ongoing data generation (auto-cleaned intervals)
 *   powers    — mock power responses
 */

/* global LlmingClient */

(function (root) {
  'use strict';

  // ---- Offline bundle helpers ----
  // The build script (tools/build_demo_bundle.py) injects:
  //   window.__LLMING_OFFLINE__ = true
  //   window.__LLMING_BUNDLE__ = { manifests, assets, shared, demoModules, cardScripts }
  // When present, fetches are replaced by lookups into this map so the
  // demo works as a single self-contained HTML file with no backend.
  function _bundle() { return root.__LLMING_BUNDLE__ || null; }
  function _bundledAsset(llmingId, path) {
    const b = _bundle();
    return (b && b.assets && b.assets[llmingId] && b.assets[llmingId][path]) || null;
  }
  function _bundledShared(path) {
    const b = _bundle();
    return (b && b.shared && b.shared[path]) || null;
  }
  function _isTextPath(path) {
    return /\.(txt|md|csv|html|js|css|svg|xml)$/i.test(path);
  }
  function _dataUrlToText(dataUrl) {
    const comma = dataUrl.indexOf(',');
    const meta = dataUrl.slice(5, comma);
    const body = dataUrl.slice(comma + 1);
    if (meta.endsWith(';base64')) return atob(body);
    return decodeURIComponent(body);
  }

  // ---- In-memory vault store ----
  // Shared across all llmings: { "owner:key": data }
  const _vaultStore = new Map();

  // ---- Pulse bus ----
  const _pulseHandlers = new Map(); // channel → [handler, ...]

  // ---- Active demo state ----
  let _active = false;
  const _demos = new Map();    // llmingId → { config, ctx, timers }
  const _savedVault = new Map(); // backup of real vault data

  // ---- Vault operations ----

  function vaultGet(owner, key) {
    const wk = owner + ':' + key;
    return _vaultStore.has(wk) ? structuredClone(_vaultStore.get(wk)) : {};
  }

  function vaultSet(owner, key, data) {
    const wk = owner + ':' + key;
    _vaultStore.set(wk, structuredClone(data));
    // Push to vaultRef watchers (same mechanism as real server)
    if (typeof LlmingClient !== 'undefined') {
      LlmingClient._notifyVaultUpdate(owner, key, data);
    }
  }

  // ---- Mock WS ----

  function createMockWS() {
    return {
      request(msg) {
        const type = msg.type;

        // Offline bundle: serve llmings.list from the embedded manifests so
        // every consumer (HortPlugins, refreshSpirits, openLlming, etc.)
        // sees the same view of the world.
        if (type === 'llmings.list') {
          const b = _bundle();
          return Promise.resolve({ data: (b && b.manifests) || [] });
        }
        if (type === 'llmings.store') {
          return Promise.resolve({ data: { keys: [] } });
        }

        if (type === 'card.vault.read') {
          return Promise.resolve({ data: vaultGet(msg.owner, msg.key) });
        }
        if (type === 'card.vault.write') {
          vaultSet(msg.owner, msg.key, msg.data);
          return Promise.resolve({ ok: true });
        }
        if (type === 'card.vault.watch') {
          // Return current data — push is handled by vaultSet above
          return Promise.resolve({ ok: true, data: vaultGet(msg.owner, msg.key) });
        }
        if (type === 'card.vault.unwatch') {
          return Promise.resolve({ ok: true });
        }
        if (type === 'card.subscribe') {
          return Promise.resolve({ ok: true });
        }
        if (type === 'card.unsubscribe') {
          return Promise.resolve({ ok: true });
        }
        if (type === 'card.power') {
          return handlePowerCall(msg.llming, msg.power, msg.args);
        }

        // Pass through for non-card messages (llmings.list etc.)
        if (root._realHortWS) {
          return root._realHortWS.request(msg);
        }
        return Promise.resolve({});
      },
      send() {},
    };
  }

  // ---- Power mocking ----

  async function handlePowerCall(llmingId, power, args) {
    const demo = _demos.get(llmingId);
    if (demo && demo.config.powers && demo.config.powers[power]) {
      const result = await demo.config.powers[power](args || {});
      return { result };
    }
    // Fall through to real server if available
    if (root._realHortWS) {
      return root._realHortWS.request({ type: 'card.power', llming: llmingId, power, args });
    }
    return { result: { code: 501, message: 'Not available in demo' } };
  }

  // ---- Demo context factory ----

  function createContext(llmingId, basePath) {
    const timers = [];

    const ctx = {
      vault: {
        get(key) { return vaultGet(llmingId, key); },
        set(key, data) { vaultSet(llmingId, key, data); },
      },

      emit(channel, data) {
        const payload = Object.assign({}, data, { _source: llmingId, _channel: channel });
        // Deliver to local pulse handlers
        const handlers = _pulseHandlers.get(channel) || [];
        for (const h of handlers) {
          try { h(payload); } catch (e) { console.error('[demo:pulse]', e); }
        }
        // Deliver to LlmingClient pulse handlers
        if (typeof LlmingClient !== 'undefined') {
          for (const [, inst] of LlmingClient.getRegistry()) {
            const active = LlmingClient.get(inst.id || '');
            if (active && active._handlePulse) {
              active._handlePulse(channel, payload);
            }
          }
        }
      },

      async load(path) {
        const bundled = _bundledAsset(llmingId, path);
        if (bundled) {
          if (path.endsWith('.json')) return JSON.parse(_dataUrlToText(bundled));
          if (_isTextPath(path)) return _dataUrlToText(bundled);
          return bundled; // binary → return data URL as-is (caller can use it as a src)
        }
        const url = basePath + '/ext/' + llmingId.replace(/-/g, '_') + '/static/' + path;
        const resp = await fetch(url);
        const ct = resp.headers.get('content-type') || '';
        if (ct.includes('json')) return resp.json();
        return resp.text();
      },

      async shared(path) {
        const bundled = _bundledShared(path);
        if (bundled) {
          if (path.endsWith('.json')) return JSON.parse(_dataUrlToText(bundled));
          if (_isTextPath(path)) return _dataUrlToText(bundled);
          return bundled;
        }
        const url = basePath + '/sample-data/' + path;
        const resp = await fetch(url);
        const ct = resp.headers.get('content-type') || '';
        if (ct.includes('json')) return resp.json();
        return resp.text();
      },

      // assetUrl — return a usable URL for binary assets (images, video,
      // audio). Stable across dev (real /ext/ URL) and offline bundle
      // (data URL from window.__LLMING_BUNDLE__).
      assetUrl(path) {
        const bundled = _bundledAsset(llmingId, path);
        if (bundled) return bundled;
        return basePath + '/ext/' + llmingId.replace(/-/g, '_') + '/static/' + path;
      },

      sharedAssetUrl(path) {
        const bundled = _bundledShared(path);
        if (bundled) return bundled;
        return basePath + '/sample-data/' + path;
      },

      interval(fn, ms) {
        const id = setInterval(fn, ms);
        timers.push({ type: 'interval', id });
        return id;
      },

      timeout(fn, ms) {
        const id = setTimeout(fn, ms);
        timers.push({ type: 'timeout', id });
        return id;
      },

      // Streams — same API shape as the server-side producer.
      // ctx.stream(channel).emit(payload) pushes through the SAME entry
      // point that production WS uses (LlmingClient._handleStreamFrame),
      // so demo and real backends share one delivery path. Demo MUST NOT
      // push frames through the vault.
      stream(channel) {
        return {
          emit(payload) {
            if (typeof LlmingClient !== 'undefined' && LlmingClient._handleStreamFrame) {
              LlmingClient._handleStreamFrame(channel, payload);
            }
          },
        };
      },
    };

    return { ctx, timers };
  }

  // ---- Demo lifecycle ----

  async function activateDemo(llmingId, config, basePath) {
    const { ctx, timers } = createContext(llmingId, basePath);

    // Seed vault
    if (config.vault) {
      for (const [key, data] of Object.entries(config.vault)) {
        vaultSet(llmingId, key, data);
      }
    }

    // Run setup
    if (config.setup) {
      await config.setup(ctx);
    }

    // Start simulation
    if (config.simulate) {
      config.simulate(ctx);
    }

    _demos.set(llmingId, { config, ctx, timers });
  }

  function deactivateDemo(llmingId) {
    const demo = _demos.get(llmingId);
    if (!demo) return;

    // Run teardown
    if (demo.config.teardown) {
      try { demo.config.teardown(demo.ctx); } catch (e) { console.error('[demo:teardown]', e); }
    }

    // Clear all timers
    for (const t of demo.timers) {
      if (t.type === 'interval') clearInterval(t.id);
      else clearTimeout(t.id);
    }

    _demos.delete(llmingId);
  }

  // ---- Toggle demo mode ----

  async function toggleDemoMode() {
    if (_active) {
      // Deactivate
      for (const id of _demos.keys()) {
        deactivateDemo(id);
      }
      _vaultStore.clear();

      // Restore real WS
      if (root._realHortWS) {
        root.hortWS = root._realHortWS;
        root._realHortWS = null;
      }

      _active = false;
      root.HortDemo._epoch++;
      if (root.HortDemo._onToggle) root.HortDemo._onToggle(false);
      console.log('[demo] Demo mode OFF');
      return false;
    }

    // Activate — discover and load demo.js files
    const basePath = (typeof LlmingClient !== 'undefined' && LlmingClient.basePath) || '';

    // Save real WS and install mock. In offline-bundle mode there IS no
    // real WS — keep _realHortWS null so the mock returns empty responses
    // for unhandled message types instead of recursing back through the
    // page's closure-bound sendControlRequest (which then routes to the
    // mock → stack overflow).
    if (!root.__LLMING_OFFLINE__ && root.hortWS && !root._realHortWS) {
      root._realHortWS = root.hortWS;
    }
    root.hortWS = createMockWS();

    // Discover llmings — bundle first, otherwise WS query
    let llmings = [];
    const b = _bundle();
    if (b && Array.isArray(b.manifests)) {
      llmings = b.manifests;
    } else {
      try {
        const msg = await (root._realHortWS || root.hortWS).request({ type: 'llmings.list' });
        llmings = (msg && msg.data) || [];
      } catch (e) {
        console.warn('[demo] Could not list llmings:', e);
      }
    }

    for (const p of llmings) {
      const bundledUrl = b && b.demoModules && b.demoModules[p.name];
      if (!p.demo_url && !bundledUrl) continue;
      try {
        // Offline → data: URL embedded in the bundle. Online → real
        // module URL. Either way it's a normal ES module import — no
        // string munging, no thunks, full language support.
        const url = bundledUrl || (basePath + p.demo_url);
        const module = await import(url);
        const config = module.default || module;
        await activateDemo(p.name, config, basePath);
      } catch (e) {
        // No demo.js or load error — skip silently
      }
    }

    _active = true;
    root.HortDemo._epoch++;
    if (root.HortDemo._onToggle) root.HortDemo._onToggle(true);
    console.log('[demo] Demo mode ON —', _demos.size, 'llmings active');
    return true;
  }

  // ---- Expose ----

  root.HortDemo = {
    get active() { return _active; },
    toggle: toggleDemoMode,
    vaultGet,
    vaultSet,
    getDemos: () => _demos,
    /** @internal Set by the Vue app to sync the reactive demoMode ref. */
    _onToggle: null,
    /** @internal Incremented on each toggle — used as Vue key to force re-mount. */
    _epoch: 0,
  };

})(typeof globalThis !== 'undefined' ? globalThis : window);
