/**
 * LlmingLens — Remote Desktop Viewer Extension
 *
 * Provides screen streaming, window browsing, and input control.
 * Appears as a single card on the main grid with a live desktop
 * thumbnail preview.
 *
 * Architecture:
 * - Grid card: shows desktop preview thumbnail (captured every 10s)
 * - Click: opens fullscreen submenu with Screen/Windows options
 * - Screen: enters the stream viewer (full remote desktop)
 * - Windows: shows the window picker grid
 *
 * Uses the shared control WebSocket via window.__hort for
 * all commands (list_windows, stream_config, input, etc.)
 */
class LlmingLensExt extends LlmingClient {
  static id = 'llming-lens';
  static name = 'LlmingLens';
  static llmingTitle = 'LlmingLens';
  static llmingIcon = 'ph ph-monitor';
  static llmingDescription = 'Remote desktop viewer & control';
  static llmingWidgets = ['llming-lens-panel'];
  static autoShow = true;
  static fullscreenCapable = true;

  _previewImg = null;
  _statusData = null;

  _feedStore(data) {
    this._statusData = data;
  }

  onConnect() {
    this.subscribe('lens_update', (data) => {
      if (data) this._statusData = data;
    });
    this.vault.get('state').then(data => {
      if (data && (data.preview !== undefined || data.window_thumbs !== undefined)) {
        this._statusData = data;
      }
    });
  }

  renderThumbnail(ctx, width, height) {
    const data = this._statusData;
    if (data && data.preview) {
      // Draw the desktop preview JPEG
      if (!this._previewImg || this._previewImg._src !== data.preview) {
        const img = new Image();
        img._src = data.preview;
        img.src = 'data:image/jpeg;base64,' + data.preview;
        img.onload = () => { this._previewImg = img; };
      }
      if (this._previewImg && this._previewImg.complete) {
        const scale = Math.min(width / this._previewImg.width, height / this._previewImg.height);
        const w = this._previewImg.width * scale;
        const h = this._previewImg.height * scale;
        ctx.drawImage(this._previewImg, (width - w) / 2, (height - h) / 2, w, h);
        return;
      }
    }
    // Fallback: dark background with icon
    ctx.fillStyle = '#0f1724';
    ctx.fillRect(0, 0, width, height);
    ctx.fillStyle = '#4a5568';
    ctx.font = 'bold 24px system-ui';
    ctx.textAlign = 'center';
    ctx.fillText('🖥', width / 2, height / 2 - 10);
    ctx.font = '12px system-ui';
    ctx.fillText('LlmingLens', width / 2, height / 2 + 15);
  }

  setup(app) {
    const ext = this;

    app.component('llming-lens-panel', {
      template: `
        <div class="llming-lens" style="width:100%;height:100%;padding:16px">
          <hort-tile-grid :items="menuItems" @select="onSelect" :columns="3" />
        </div>
      `,
      setup() {
        // Get desktop preview thumbnail from the extension's status data
        const previewThumb = Vue.computed(() => {
          const inst = typeof LlmingClient !== 'undefined' ? LlmingClient.get('llming-lens') : null;
          return inst?._statusData?.preview || '';
        });

        // Stacked windows thumbnail — uses real window captures when available
        const windowsThumb = Vue.ref('');
        const _thumbImages = {};

        function updateWindowsThumb() {
          const inst = typeof LlmingClient !== 'undefined' ? LlmingClient.get('llming-lens') : null;
          const thumbs = inst?._statusData?.window_thumbs || [];

          const c = document.createElement('canvas');
          c.width = 320; c.height = 180;
          const ctx = c.getContext('2d');

          ctx.fillStyle = '#0f1724';
          ctx.fillRect(0, 0, 320, 180);

          // Positions for 3 stacked windows (back to front)
          const positions = [
            { x: 20, y: 12, w: 190, h: 130 },
            { x: 60, y: 28, w: 190, h: 130 },
            { x: 100, y: 44, w: 190, h: 130 },
          ];

          const titleColors = ['#3a6b9f', '#4080bf', '#4a95df'];

          for (let i = 0; i < positions.length; i++) {
            const p = positions[i];
            const thumb = thumbs[i];

            // Shadow
            ctx.fillStyle = 'rgba(0,0,0,0.35)';
            ctx.fillRect(p.x + 4, p.y + 4, p.w, p.h);

            // Window body
            ctx.fillStyle = '#1a2d4a';
            ctx.fillRect(p.x, p.y, p.w, p.h);

            // Draw real thumbnail if available
            if (thumb && thumb.b64) {
              const key = thumb.id + ':' + thumb.b64.substring(0, 20);
              if (!_thumbImages[key]) {
                const img = new Image();
                img.src = 'data:image/jpeg;base64,' + thumb.b64;
                img._key = key;
                img.onload = () => { _thumbImages[key] = img; updateWindowsThumb(); };
              }
              const img = _thumbImages[key];
              if (img && img.complete && img.naturalWidth > 0) {
                ctx.drawImage(img, p.x, p.y + 16, p.w, p.h - 16);
              }
            } else {
              // Fake content lines
              ctx.fillStyle = 'rgba(255,255,255,0.1)';
              for (let j = 0; j < 4; j++) {
                ctx.fillRect(p.x + 10, p.y + 26 + j * 14, 40 + Math.random() * 80, 5);
              }
            }

            // Title bar
            ctx.fillStyle = titleColors[i] || '#4080bf';
            ctx.fillRect(p.x, p.y, p.w, 16);

            // Traffic lights
            ctx.fillStyle = '#ff5f57';
            ctx.beginPath(); ctx.arc(p.x + 10, p.y + 8, 3, 0, Math.PI * 2); ctx.fill();
            ctx.fillStyle = '#ffbd2e';
            ctx.beginPath(); ctx.arc(p.x + 20, p.y + 8, 3, 0, Math.PI * 2); ctx.fill();
            ctx.fillStyle = '#28c840';
            ctx.beginPath(); ctx.arc(p.x + 30, p.y + 8, 3, 0, Math.PI * 2); ctx.fill();

            // Window border
            ctx.strokeStyle = 'rgba(255,255,255,0.08)';
            ctx.lineWidth = 1;
            ctx.strokeRect(p.x, p.y, p.w, p.h);
          }

          windowsThumb.value = c.toDataURL('image/png');
        }

        // Update when status data changes
        Vue.watchEffect(() => {
          const inst = typeof LlmingClient !== 'undefined' ? LlmingClient.get('llming-lens') : null;
          if (inst?._statusData?.window_thumbs) updateWindowsThumb();
        });
        // Initial render with fake content
        Vue.onMounted(updateWindowsThumb);

        const menuItems = Vue.computed(() => [
          {
            id: 'desktop',
            title: 'Desktop',
            subtitle: 'Full screen capture',
            icon: 'ph ph-desktop',
            thumbnail: previewThumb.value,
            windowId: -1,
          },
          {
            id: 'windows',
            title: 'Windows',
            subtitle: 'Browse individual windows',
            icon: 'ph ph-squares-four',
            thumbnail: windowsThumb.value,
          },
        ]);

        function onSelect(item) {
          if (item.id === 'windows') {
            // Open window overview (screens index)
            LlmingClient.openLlming('llming-lens', 'screens');
          } else {
            LlmingClient.openViewer(item.windowId);
          }
        }

        return { menuItems, onSelect };
      },
    });
  }
}

LlmingClient.register(LlmingLensExt);
