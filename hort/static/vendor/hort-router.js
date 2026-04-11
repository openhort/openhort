/**
 * HortRouter — Unified SPA router for openhort (History API).
 *
 * Everything is a llming. Clean URL scheme:
 *
 *   /                                         — picker (home)
 *   /{provider}/{name}                        — open llming
 *   /{provider}/{name}/{sub}                  — llming with sub-route
 *   /{provider}/{name}/{sub}?key=val          — llming with sub-route + params
 *
 * Float windows are overlays and do NOT push routes.
 *
 * Back button behavior:
 *   - If navigated within the session → history.back() (browser handles it)
 *   - If at a deep URL on fresh load → navigate to parent/home
 *   - If at root with no session history → "Leave openhort?" dialog
 */
(function (root) {
  'use strict';

  var _onNavigate = null;
  var _Quasar = null;
  var _current = null;
  var _basePath = '';
  var _depth = 0;             // how many push() calls in this session
  var _guardDialogOpen = false;

  // ── Route parsing ────────────────────────────────────────────────

  function parsePathname(pathname) {
    var path = pathname || '/';
    if (_basePath && path.indexOf(_basePath) === 0) {
      path = path.substring(_basePath.length) || '/';
    }
    var qIdx = path.indexOf('?');
    var cleanPath = qIdx >= 0 ? path.substring(0, qIdx) : path;

    if (cleanPath === '/' || cleanPath === '') {
      return { view: 'picker' };
    }

    var m = cleanPath.match(/^\/llming\/([^/]+)\/([^/]+)(?:\/(.+))?$/);
    if (m) {
      return {
        view: 'llming',
        provider: m[1],
        name: m[2],
        sub: m[3] || null,
        params: new URLSearchParams(location.search),
      };
    }

    return null;
  }

  function buildPath(provider, name, sub, params) {
    var p = _basePath + '/llming/' + provider + '/' + name;
    if (sub != null) p += '/' + String(sub);
    if (params) {
      var qs = typeof params === 'string' ? params
        : (params instanceof URLSearchParams ? params.toString() : new URLSearchParams(params).toString());
      if (qs) p += '?' + qs;
    }
    return p;
  }

  // ── Leave guard ──────────────────────────────────────────────────

  function showLeaveDialog() {
    if (_guardDialogOpen) return;
    _guardDialogOpen = true;

    if (_Quasar && _Quasar.Dialog) {
      _Quasar.Dialog.create({
        title: 'Leave openhort?',
        message: 'Are you sure you want to leave?',
        dark: true,
        ok: { label: 'Leave', color: 'negative', flat: true },
        cancel: { label: 'Stay', color: 'primary' },
      }).onOk(function () {
        _guardDialogOpen = false;
        // Actually leave the page
        history.back();
      }).onCancel(function () {
        _guardDialogOpen = false;
      }).onDismiss(function () {
        _guardDialogOpen = false;
      });
    } else {
      _guardDialogOpen = false;
    }
  }

  // ── popstate listener ────────────────────────────────────────────

  function onPopState() {
    var route = parsePathname(location.pathname);
    if (!route) {
      history.replaceState(null, '', _basePath + '/');
      route = parsePathname('/');
    }

    if (route.view === 'llming') {
      route.params = new URLSearchParams(location.search);
    }

    // Track depth — popstate means we went back (or forward)
    if (_depth > 0) _depth--;

    _current = route;
    if (_onNavigate) _onNavigate(route);
  }

  // ── Public API ───────────────────────────────────────────────────

  var HortRouter = {
    init: function (onNavigate, Quasar) {
      _onNavigate = onNavigate;
      _Quasar = Quasar;
      _basePath = (typeof LlmingClient !== 'undefined' && LlmingClient.basePath) || '';

      // Migrate legacy hash URLs to clean paths
      if (location.hash && location.hash.length > 2) {
        var hashPath = location.hash.replace(/^#/, '');
        // Add /llming prefix if missing
        if (hashPath.match(/^\/[^/]+\/[^/]+/) && !hashPath.startsWith('/llming/')) {
          hashPath = '/llming' + hashPath;
        }
        history.replaceState(null, '', _basePath + hashPath);
      }

      _current = parsePathname(location.pathname);
      if (_current && _current.view === 'llming') {
        _current.params = new URLSearchParams(location.search);
      }

      window.addEventListener('popstate', onPopState);

      if (_current && _onNavigate) {
        _onNavigate(_current);
      }
    },

    push: function (path) {
      var fullPath = _basePath + path;
      history.pushState(null, '', fullPath);
      _depth++;
      _current = parsePathname(fullPath);
      if (_current && _current.view === 'llming') {
        _current.params = new URLSearchParams(new URL(fullPath, location.origin).search);
      }
      if (_onNavigate) _onNavigate(_current);
    },

    replace: function (path) {
      var fullPath = _basePath + path;
      history.replaceState(null, '', fullPath);
      _current = parsePathname(fullPath);
      if (_current && _current.view === 'llming') {
        _current.params = new URLSearchParams(new URL(fullPath, location.origin).search);
      }
    },

    /**
     * Go back. Three cases:
     *   1. Session history exists (depth > 0) → history.back()
     *   2. At a deep URL on fresh load (depth 0, not root) → navigate home
     *   3. At root with no history (depth 0, root) → show leave dialog
     */
    back: function () {
      if (_depth > 0) {
        // We have session history — use browser back
        history.back();
        return true;
      }
      if (_current && _current.view !== 'picker') {
        // Fresh load at a deep URL — go home
        HortRouter.push('/');
        return true;
      }
      // At root with no history — ask to leave
      showLeaveDialog();
      return false;
    },

    current: function () { return _current; },
    buildPath: buildPath,
    parsePathname: parsePathname,
  };

  root.HortRouter = HortRouter;
})(window);
