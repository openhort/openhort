/* hort-card-bridge.js — host-side dispatcher for sandboxed cards.
 *
 * Maintains:
 *   - WeakMap<Window, llmingId>           identity registry (forge-proof)
 *   - Map<llmingId, capabilities>         capability table from manifests
 *   - device-local IndexedDB store        per-llming, host-owned, persistent
 *   - vault.watch / pulse / stream proxies that forward to the iframe ONLY
 *     for namespaces the manifest declared.
 *
 * See docs/manual/internals/security/card-sandbox.md for the contract.
 */

/* global LlmingClient */

(function (root) {
  'use strict';

  // --- Identity & capability tables ----------------------------------------

  const _identity = new WeakMap();        // iframe.contentWindow → llmingId
  const _capabilities = new Map();        // llmingId → caps object
  const _watchers = new Map();             // llmingId → Set of {namespace,key} subscribed
  const _streamSubs = new Map();          // llmingId → Set of channel
  const _pulseSubs = new Map();            // llmingId → Set of channel
  const _frames = new Map();              // llmingId → Set<Window>  (every live iframe of this llming)
  const _warnedDenials = new Set();       // "llmingId|why" — log each denial once to avoid console spam

  // ---- Pending iframe registration (handshake-driven init) -------------
  //
  // The host doesn't know an iframe's contentWindow until it loads.
  // Components register a "pending" entry (iframe + claimed llming id +
  // widget + props). When the iframe sends `card.handshake`, we look it
  // up, verify the claimed llming id matches the pending entry for that
  // exact iframe element, register identity, and post init. The iframe
  // cannot forge an identity it wasn't already pre-stamped with.
  const _pending = new Map();    // iframe element → {llmingId, widget, props, manifest}

  function registerPending(iframe, llmingId, widget, props) {
    const ps = (root.HortPlugins && root.HortPlugins.getPlugins()) || [];
    const manifest = ps.find(m => m.name === llmingId) || { name: llmingId, needs: {} };
    _pending.set(iframe, { llmingId, widget, props: props || {}, manifest });
  }
  function unregisterPending(iframe) {
    const entry = _pending.get(iframe);
    if (entry) {
      _pending.delete(iframe);
      unregisterIframe(iframe, entry.llmingId);
    }
  }
  function _findIframeByWindow(w) {
    for (const ifr of document.querySelectorAll('iframe')) {
      if (ifr.contentWindow === w) return ifr;
    }
    return null;
  }
  function _onHandshake(e) {
    if (!e.data || e.data.op !== 'card.handshake') return;
    let iframe = _findIframeByWindow(e.source);
    if (!iframe && e.data.llming) {
      // Fallback: identity matching by claimed llming id when the
      // iframe.contentWindow lookup fails (some browsers replace the
      // contentWindow proxy on cross-origin navigation).
      for (const [el, ent] of _pending) {
        if (ent.llmingId === e.data.llming) { iframe = el; break; }
      }
    }
    if (!iframe) return;
    const entry = _pending.get(iframe);
    if (!entry) return;
    // Forge check: the iframe's claimed id (from URL → handshake) must
    // match the pre-stamped entry. Mismatches are dropped silently.
    if (e.data.llming && e.data.llming !== entry.llmingId) return;
    registerIframe(iframe, entry.llmingId, entry.manifest);
    const dirName = (entry.manifest.dir_name || entry.llmingId.replace(/-/g, '_'));
    const scriptUrl = entry.manifest.ui_script_url || ('/ext/' + dirName + '/static/cards.js');
    const appScriptUrl = entry.manifest.app_script_url || '';
    try {
      iframe.contentWindow.postMessage({
        op: 'init',
        llmingId: entry.llmingId,
        scriptUrl: location.origin + scriptUrl,
        appScriptUrl: appScriptUrl ? (location.origin + appScriptUrl) : '',
        widget: entry.widget,
        props: entry.props,
        capabilities: entry.manifest.needs || {},
      }, '*');
    } catch {}
  }
  window.addEventListener('message', _onHandshake);

  // Optional cold-load probe (toggle via ?perf=1)
  const _perf = location.search.includes('perf=1');
  const _perfReady = [];
  if (_perf) {
    window.addEventListener('message', (e) => {
      if (e.data && e.data.op === 'card.ready') {
        _perfReady.push({ ll: e.data.llmingId, t: Math.round(performance.now()), inner: e.data._perf });
      }
    });
    window.__cardPerf = () => {
      const avg = (k) => Math.round(_perfReady.reduce((s,e) => s + (e.inner?.[k] || 0), 0) / Math.max(1, _perfReady.length));
      return {
        first: _perfReady[0] && _perfReady[0].t,
        last: _perfReady[_perfReady.length - 1] && _perfReady[_perfReady.length - 1].t,
        count: _perfReady.length,
        all: _perfReady,
        avg_inline_at: avg('inline_at'),
        avg_handshake_at: avg('handshake_sent_at'),
        avg_init_recv_at: avg('init_recv_at'),
        avg_wait_for_init: avg('wait_for_init'),
        avg_script: avg('script'),
        avg_mount: avg('mount'),
      };
    };
  }

  function registerIframe(iframe, llmingId, manifest) {
    if (!iframe || !iframe.contentWindow) return;
    _identity.set(iframe.contentWindow, llmingId);
    // Capability table is shared by every iframe of the same llming.
    if (!_capabilities.has(llmingId)) _capabilities.set(llmingId, _compileCaps(manifest));
    let set = _frames.get(llmingId);
    if (!set) { set = new Set(); _frames.set(llmingId, set); }
    set.add(iframe.contentWindow);
  }

  function unregisterIframe(iframe, llmingId) {
    if (!iframe || !iframe.contentWindow) return;
    const target = iframe.contentWindow;
    _identity.delete(target);
    // Remove this iframe from any per-channel stream subscriber sets.
    const byChannel = _streamSubs.get(llmingId);
    if (byChannel) {
      for (const [ch, targets] of byChannel) {
        targets.delete(target);
        if (!targets.size) byChannel.delete(ch);
      }
    }
    const set = _frames.get(llmingId);
    if (set) {
      set.delete(target);
      if (!set.size) {
        _frames.delete(llmingId);
        _capabilities.delete(llmingId);
        // Last iframe gone: tear down upstream subscriptions for this llming.
        const watches = _watchers.get(llmingId);
        if (watches) {
          for (const w of watches) {
            try { LlmingClient._unwatchVault && LlmingClient._unwatchVault(w.namespace, w.key, w.entry); } catch {}
          }
          _watchers.delete(llmingId);
        }
        _streamSubs.delete(llmingId);
        _pulseSubs.delete(llmingId);
      }
    }
  }

  /** Send a push to every live iframe of a given llming. */
  function _broadcast(llmingId, msg) {
    const set = _frames.get(llmingId);
    if (!set) return;
    for (const target of set) {
      try { target.postMessage(msg, '*'); } catch {}
    }
  }

  function _compileCaps(manifest) {
    const needs = (manifest && manifest.needs) || {};
    return {
      vault_read:  _splitSpecs(needs.vault, 'read'),
      vault_write: _splitSpecs(needs.vault_write || needs.vault, 'write'),
      vault_watch: _splitSpecs(needs.vault, 'watch'),
      pulse_sub:   _splitOpSpecs(needs.pulse, 'subscribe'),
      pulse_pub:   _splitOpSpecs(needs.pulse, 'publish'),
      stream:      (needs.stream || []).map(_parseSpec),
      powers:      (needs.powers || []).map(_parseSpec),
      local_quota_mb: (manifest && manifest.local_quota_mb) || 5,
    };
  }

  // pulse specs are 'subscribe:owner:channel' / 'publish:owner:channel'
  function _splitOpSpecs(specs, op) {
    const out = [];
    for (const s of (specs || [])) {
      const parts = s.split(':');
      if (parts.length >= 3 && parts[0] === op) {
        out.push(_parseSpec(parts.slice(1).join(':')));
      }
    }
    return out;
  }
  function _splitSpecs(specs, _op) {
    return (specs || []).map(_parseSpec);
  }
  function _parseSpec(s) {
    const idx = s.indexOf(':');
    if (idx < 0) return { owner: s, key: '*' };
    return { owner: s.slice(0, idx), key: s.slice(idx + 1) };
  }

  function _matchSpec(spec, owner, key) {
    if (spec.owner !== owner && spec.owner !== '*') return false;
    if (spec.key === '*') return true;
    if (spec.key === key) return true;
    if (spec.key.endsWith('.*')) {
      const prefix = spec.key.slice(0, -2);
      return key === prefix || key.startsWith(prefix + '.');
    }
    return false;
  }

  function _allow(llmingId, kind, owner, key) {
    if (owner === llmingId) return true;  // self-access always allowed
    const caps = _capabilities.get(llmingId);
    if (!caps) return false;
    const list = caps[kind] || [];
    return list.some(s => _matchSpec(s, owner, key));
  }

  // --- Device-local IndexedDB (host-owned, per-llming) ---------------------

  const _LOCAL_DB = 'hort-card-local';
  const _LOCAL_STORE = 'kv';
  let _localDb = null;
  function _openLocalDb() {
    if (_localDb) return Promise.resolve(_localDb);
    return new Promise((resolve, reject) => {
      const r = indexedDB.open(_LOCAL_DB, 1);
      r.onupgradeneeded = () => {
        r.result.createObjectStore(_LOCAL_STORE);  // key path = composite "llmingId\u0000key"
      };
      r.onsuccess = () => { _localDb = r.result; resolve(_localDb); };
      r.onerror = () => reject(r.error);
    });
  }
  function _localKey(llmingId, key) { return llmingId + '\u0000' + key; }

  async function _localGet(llmingId, key) {
    const db = await _openLocalDb();
    return new Promise((resolve, reject) => {
      const tx = db.transaction(_LOCAL_STORE, 'readonly');
      const req = tx.objectStore(_LOCAL_STORE).get(_localKey(llmingId, key));
      req.onsuccess = () => resolve(req.result);
      req.onerror = () => reject(req.error);
    });
  }
  async function _localSet(llmingId, key, value) {
    const db = await _openLocalDb();
    return new Promise((resolve, reject) => {
      const tx = db.transaction(_LOCAL_STORE, 'readwrite');
      tx.objectStore(_LOCAL_STORE).put(value, _localKey(llmingId, key));
      tx.oncomplete = () => resolve();
      tx.onerror = () => reject(tx.error);
    });
  }
  async function _localDelete(llmingId, key) {
    const db = await _openLocalDb();
    return new Promise((resolve, reject) => {
      const tx = db.transaction(_LOCAL_STORE, 'readwrite');
      tx.objectStore(_LOCAL_STORE).delete(_localKey(llmingId, key));
      tx.oncomplete = () => resolve();
      tx.onerror = () => reject(tx.error);
    });
  }
  async function _localKeys(llmingId) {
    const db = await _openLocalDb();
    return new Promise((resolve, reject) => {
      const tx = db.transaction(_LOCAL_STORE, 'readonly');
      const req = tx.objectStore(_LOCAL_STORE).getAllKeys();
      req.onsuccess = () => {
        const prefix = llmingId + '\u0000';
        resolve((req.result || [])
          .filter(k => typeof k === 'string' && k.startsWith(prefix))
          .map(k => k.slice(prefix.length)));
      };
      req.onerror = () => reject(req.error);
    });
  }

  // --- Message handler -----------------------------------------------------

  async function _handle(event) {
    const llmingId = _identity.get(event.source);
    if (!llmingId) return;  // unknown sender
    const msg = event.data;
    if (!msg || typeof msg !== 'object' || !msg.op) return;

    function reply(data) {
      try { event.source.postMessage({ id: msg.id, ...data }, '*'); } catch {}
    }
    function deny(why, hintNeeds) {
      // Loud, copy-pasteable manifest hint so the author sees exactly what
      // to add. Suppressed for repeat-denials of the same op to avoid
      // spamming the console; first occurrence is always shown.
      const key = llmingId + '|' + why;
      if (!_warnedDenials.has(key)) {
        _warnedDenials.add(key);
        const hint = hintNeeds ? '\n    "needs": ' + JSON.stringify(hintNeeds) : '';
        console.warn('[card:' + llmingId + '] denied ' + why + hint
          + '\n    See docs/manual/internals/security/card-sandbox.md');
      }
      reply({ ok: false, error: 'denied: ' + why });
    }
    function denyVault(op, ns, key) { return deny(`vault.${op} ${ns}:${key}`, { vault: [`${ns}:${key}`] }); }
    function denyPulse(op, ch) { return deny(`pulse.${op} ${ch}`, { pulse: [`${op}:${ch}`] }); }
    function denyStream(ch) { return deny(`stream.subscribe ${ch}`, { stream: [ch] }); }
    function denyPower(llming, power) { return deny(`power.call ${llming}:${power}`, { powers: [`${llming}:${power}`] }); }

    try {
      switch (msg.op) {
        // ---- vault ----
        case 'vault.read':
          if (!_allow(llmingId, 'vault_read', msg.namespace, msg.key)) return denyVault('read', msg.namespace, msg.key);
          {
            const data = await _wsRequest({ type: 'card.vault.read', owner: msg.namespace, key: msg.key });
            reply({ ok: true, data: data && data.data });
          } return;
        case 'vault.write':
          if (!_allow(llmingId, 'vault_write', msg.namespace, msg.key)) return denyVault('write', msg.namespace, msg.key);
          await _wsRequest({ type: 'card.vault.write', owner: msg.namespace, key: msg.key, data: msg.data, ttl: msg.ttl || null });
          reply({ ok: true }); return;
        case 'vault.watch':
          if (!_allow(llmingId, 'vault_watch', msg.namespace, msg.key)) return denyVault('watch', msg.namespace, msg.key);
          _vaultWatch(llmingId, event.source, msg.namespace, msg.key);
          reply({ ok: true }); return;
        case 'vault.unwatch':
          _vaultUnwatch(llmingId, msg.namespace, msg.key);
          reply({ ok: true }); return;

        // ---- pulse ----
        case 'pulse.subscribe':
          {
            const [owner, ...rest] = msg.channel.split(':');
            const tail = rest.join(':');
            if (!_allow(llmingId, 'pulse_sub', owner, tail || '*')) return denyPulse('subscribe', msg.channel);
            _pulseSubscribe(llmingId, event.source, msg.channel);
            reply({ ok: true });
          } return;
        case 'pulse.publish':
          {
            const [owner, ...rest] = msg.channel.split(':');
            const tail = rest.join(':');
            if (!_allow(llmingId, 'pulse_pub', owner, tail || '*')) return denyPulse('publish', msg.channel);
            await _wsRequest({ type: 'pulse.publish', channel: msg.channel, data: msg.payload || {} });
            reply({ ok: true });
          } return;

        // ---- stream ----
        case 'stream.subscribe':
          {
            const [owner, ...rest] = msg.channel.split(':');
            const tail = rest.join(':');
            if (!_allow(llmingId, 'stream', owner, tail || '*')) return denyStream(msg.channel);
            _streamSubscribe(llmingId, event.source, msg.channel, msg.opts || {});
            reply({ ok: true });
          } return;
        case 'stream.ack':
          // ACK is just a flow signal; forward to the real WS so the producer can pace
          if (root.hortWS) root.hortWS.send({ type: 'stream.ack', channel: msg.channel });
          return;

        // ---- powers ----
        case 'power.call':
          if (!_allow(llmingId, 'powers', msg.llming, msg.power)) return denyPower(msg.llming, msg.power);
          {
            const r = await _wsRequest({ type: 'card.power', llming: msg.llming, power: msg.power, args: msg.args || {} });
            reply({ ok: true, result: r && r.result });
          } return;

        // ---- subapp / app ----
        case 'subapp.open':
          if (root.LlmingClient && root.LlmingClient.openSubapp) {
            root.LlmingClient.openSubapp(llmingId, msg.widget, msg.props || {}, msg.opts || {});
          }
          reply({ ok: true }); return;
        case 'app.open':
          // Allow opening own llming or others — opening another llming is just navigation, not data access.
          if (root.LlmingClient && root.LlmingClient.openLlming) {
            root.LlmingClient.openLlming(msg.llming || llmingId, msg.sub);
          }
          reply({ ok: true }); return;

        // ---- device-local storage ----
        case 'local.read':
          reply({ ok: true, data: await _localGet(llmingId, msg.key) }); return;
        case 'local.write':
          await _localSet(llmingId, msg.key, msg.data);
          // Push to every iframe of this llming so widgets, subapps, and
          // fullscreen apps stay in sync without polling.
          _broadcast(llmingId, { op: 'local.update', key: msg.key, data: msg.data });
          reply({ ok: true }); return;
        case 'local.delete':
          await _localDelete(llmingId, msg.key);
          _broadcast(llmingId, { op: 'local.update', key: msg.key, data: undefined });
          reply({ ok: true }); return;
        case 'local.keys':
          reply({ ok: true, data: await _localKeys(llmingId) }); return;
        case 'local.watch':
          // Watching is a no-op server-side — the iframe just registers
          // a listener locally and waits for `local.update` pushes from
          // local.write. Reply with the current value so the consumer
          // can seed its ref synchronously.
          reply({ ok: true, data: await _localGet(llmingId, msg.key) }); return;

        default:
          reply({ ok: false, error: 'unknown op: ' + msg.op });
      }
    } catch (e) {
      reply({ ok: false, error: String(e && e.message || e) });
    }
  }

  // --- Push: vault watches ------------------------------------------------

  function _vaultWatch(llmingId, target, namespace, key) {
    const entry = {
      ref: { value: null },
      extract: (d) => d,
      lastJson: '',
      onChange(nv) {
        try { target.postMessage({ op: 'vault.update', namespace, key, data: nv }, '*'); } catch {}
      },
    };
    if (root.LlmingClient && root.LlmingClient._watchVault) {
      root.LlmingClient._watchVault(namespace, key, entry);
    }
    let set = _watchers.get(llmingId);
    if (!set) { set = new Set(); _watchers.set(llmingId, set); }
    set.add({ namespace, key, entry });
    // Push initial value
    if (root.hortWS) {
      root.hortWS.request({ type: 'card.vault.read', owner: namespace, key }).then((m) => {
        if (m && m.data !== undefined) entry.onChange(m.data);
      }).catch(() => {});
    }
  }
  function _vaultUnwatch(llmingId, namespace, key) {
    const set = _watchers.get(llmingId);
    if (!set) return;
    for (const w of Array.from(set)) {
      if (w.namespace === namespace && w.key === key) {
        try { root.LlmingClient._unwatchVault && root.LlmingClient._unwatchVault(namespace, key, w.entry); } catch {}
        set.delete(w);
      }
    }
  }

  // --- Push: pulse ---------------------------------------------------------

  // Pulse delivery currently happens through whatever pulse plumbing the host exposes.
  // We register a single host-side handler per (llming, channel) that forwards to the iframe.
  function _pulseSubscribe(llmingId, target, channel) {
    let set = _pulseSubs.get(llmingId);
    if (!set) { set = new Map(); _pulseSubs.set(llmingId, set); }
    if (set.has(channel)) return;
    const handler = (payload) => {
      try { target.postMessage({ op: 'pulse.event', channel, payload }, '*'); } catch {}
    };
    set.set(channel, handler);
    if (root.LlmingClient && root.LlmingClient._subscribePulse) {
      root.LlmingClient._subscribePulse(channel, handler);
    } else if (root.hortWS) {
      root.hortWS.request({ type: 'card.subscribe', channel }).catch(() => {});
    }
  }

  // --- Push: stream --------------------------------------------------------

  // Hook into LlmingClient._handleStreamFrame to dispatch frames to authorized iframes.
  // Multiple iframes of the same llming may subscribe to the same channel
  // (widget + subapp + fullscreen at once); each gets its own postMessage.
  function _streamSubscribe(llmingId, target, channel, opts) {
    let byChannel = _streamSubs.get(llmingId);
    if (!byChannel) { byChannel = new Map(); _streamSubs.set(llmingId, byChannel); }
    let targets = byChannel.get(channel);
    const isFirstForChannel = !targets;
    if (!targets) { targets = new Set(); byChannel.set(channel, targets); }
    targets.add(target);
    // Subscribe upstream once per (llming, channel)
    if (isFirstForChannel && root.hortWS) {
      root.hortWS.request({
        type: 'stream.subscribe',
        channel,
        displayWidth: opts.displayWidth || 320,
        displayHeight: opts.displayHeight || 180,
      }).catch(() => {});
    }
  }

  // Patch _handleStreamFrame to also fan out to subscribed iframes.
  // Blob URLs are bound to the parent's origin — opaque-origin iframes
  // cannot load them. We fetch the blob in the parent and postMessage
  // the Blob itself (structured-clone handles it); the iframe creates
  // its own origin-local URL on receive.
  async function _forwardFrame(target, channel, data) {
    let payload = data;
    if (typeof data === 'string' && data.startsWith('blob:')) {
      try {
        const resp = await fetch(data);
        payload = await resp.blob();
      } catch { /* keep the URL; iframe will likely fail but we tried */ }
    }
    try { target.postMessage({ op: 'stream.frame', channel, data: payload }, '*'); } catch {}
  }
  function _installStreamFanout() {
    if (!root.LlmingClient || !root.LlmingClient._handleStreamFrame) {
      setTimeout(_installStreamFanout, 200);
      return;
    }
    if (root.LlmingClient._handleStreamFrame.__bridgeWrapped) return;
    const orig = root.LlmingClient._handleStreamFrame;
    function wrapped(channel, data) {
      try { orig(channel, data); } catch {}
      for (const [, byChannel] of _streamSubs) {
        const targets = byChannel.get(channel);
        if (!targets) continue;
        for (const target of targets) _forwardFrame(target, channel, data);
      }
    }
    wrapped.__bridgeWrapped = true;
    root.LlmingClient._handleStreamFrame = wrapped;
  }
  _installStreamFanout();

  // --- WS helper -----------------------------------------------------------

  function _wsRequest(msg) {
    if (root.hortWS && root.hortWS.request) return root.hortWS.request(msg);
    return Promise.resolve({});
  }

  // --- Public API ----------------------------------------------------------

  window.addEventListener('message', _handle);

  // Surface iframe console output in the host's devtools (debug aid).
  window.addEventListener('message', (e) => {
    if (!e.data || e.data.op !== 'card.console') return;
    const llmingId = _identity.get(e.source) || '?';
    const fn = console[e.data.level] || console.log;
    fn.call(console, '[card:' + llmingId + ']', ...(e.data.args || []));
  });

  // Background click in the iframe → click on the host widget element.
  // Lets the existing onWidgetClick handler fire for cards inside iframes
  // (the iframe consumes raw clicks; we re-dispatch to the .widget parent).
  window.addEventListener('message', (e) => {
    if (!e.data || e.data.op !== 'card.click') return;
    const iframe = _findIframeByWindow(e.source);
    if (!iframe) return;
    const widget = iframe.closest('.widget') || iframe.parentElement;
    if (!widget) return;
    widget.dispatchEvent(new MouseEvent('click', { bubbles: true }));
  });

  // Escape inside the iframe → re-dispatch on document so the host's
  // global keyboard handler (which closes the topmost app via the
  // beforeClose-aware __hortCloseApp path) fires. Apps that want to
  // handle Esc themselves should register $llming.onBeforeClose() —
  // the negotiation runs before the close completes.
  window.addEventListener('message', (e) => {
    if (!e.data || e.data.op !== 'app.escape') return;
    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
  });

  // ---- Before-close negotiation ----------------------------------------
  //
  // Apps can register `$llming.onBeforeClose(handler)` inside their iframe
  // to veto a close request — useful for "unsaved changes" dialogs. The
  // host calls requestClose(llmingId) which postMessages every iframe of
  // that llming and waits up to ~250 ms for responses. Default = allow
  // (so a missing or buggy handler can never trap the user in an app).

  let _closeReqSeq = 0;
  const _closeReqs = new Map();   // requestId → {resolve, pending, denied, timer}

  function requestClose(llmingId) {
    return new Promise((resolve) => {
      const set = _frames.get(llmingId);
      if (!set || !set.size) return resolve(true);
      const requestId = ++_closeReqSeq;
      const req = { resolve, pending: set.size, denied: false };
      req.timer = setTimeout(() => {
        if (!_closeReqs.has(requestId)) return;
        _closeReqs.delete(requestId);
        resolve(!req.denied);
      }, 250);
      _closeReqs.set(requestId, req);
      for (const target of set) {
        try { target.postMessage({ op: 'app.beforeClose', requestId }, '*'); } catch {
          req.pending--;
        }
      }
      if (req.pending <= 0) {
        clearTimeout(req.timer);
        _closeReqs.delete(requestId);
        resolve(!req.denied);
      }
    });
  }

  window.addEventListener('message', (e) => {
    if (!e.data || e.data.op !== 'app.beforeCloseResponse') return;
    const req = _closeReqs.get(e.data.requestId);
    if (!req) return;
    if (e.data.allow === false) req.denied = true;
    req.pending--;
    if (req.pending <= 0) {
      clearTimeout(req.timer);
      _closeReqs.delete(e.data.requestId);
      req.resolve(!req.denied);
    }
  });

  // ---- App-initiated close (skips the beforeClose hook) ---------------
  // The iframe calls $llming.closeSelf() after handling its own confirm
  // dialog. We route to __hortCloseApp via a sentinel flag so the next
  // close request bypasses the negotiation.
  let _skipNextBeforeClose = false;
  function _consumeBypass() {
    const v = _skipNextBeforeClose;
    _skipNextBeforeClose = false;
    return v;
  }
  window.addEventListener('message', (e) => {
    const llmingId = _identity.get(e.source);
    if (!llmingId) return;
    if (!e.data || e.data.op !== 'app.closeSelf') return;
    _skipNextBeforeClose = true;
    if (typeof window.__hortCloseApp === 'function') window.__hortCloseApp(llmingId);
  });

  // ---- Warm-iframe acquire (skip handshake) ---------------------------
  //
  // The pool pre-loads an app-host iframe with no llming param so Vue +
  // Quasar are already parsed. When the pool hands it to a freshly-opened
  // float, we register identity + post init directly (the original
  // handshake had `llming=''` and was ignored). On float close the
  // iframe is destroyed and the pool spawns a replacement.
  function acquireWarm(iframe, llmingId, widget, props) {
    const ps = (root.HortPlugins && root.HortPlugins.getPlugins()) || [];
    const manifest = ps.find(m => m.name === llmingId) || { name: llmingId, needs: {} };
    registerIframe(iframe, llmingId, manifest);
    const dirName = manifest.dir_name || llmingId.replace(/-/g, '_');
    const scriptUrl = manifest.ui_script_url || ('/ext/' + dirName + '/static/cards.js');
    const appScriptUrl = manifest.app_script_url || '';
    try {
      iframe.contentWindow.postMessage({
        op: 'init',
        llmingId,
        scriptUrl: location.origin + scriptUrl,
        appScriptUrl: appScriptUrl ? (location.origin + appScriptUrl) : '',
        widget,
        props: props || {},
        capabilities: manifest.needs || {},
      }, '*');
    } catch {}
  }

  function destroyAcquired(iframe, llmingId) {
    unregisterIframe(iframe, llmingId);
    if (iframe.parentElement) iframe.parentElement.removeChild(iframe);
  }

  root.HortCardBridge = {
    registerIframe,
    unregisterIframe,
    registerPending,
    unregisterPending,
    requestClose,
    acquireWarm,
    destroyAcquired,
    _consumeBypass,
    /** Test helper: return capabilities snapshot for a llming */
    _capsOf: (id) => _capabilities.get(id),
  };

})(typeof globalThis !== 'undefined' ? globalThis : window);
