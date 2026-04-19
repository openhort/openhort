export default {
  vault: {
    'state': {
      cameras: [
        { id: 'frontdoor', name: 'Front', motion: false },
        { id: 'backyard', name: 'Back', motion: false },
        { id: 'garage', name: 'Garage', motion: false },
      ],
    }
  },

  simulate(ctx) {
    const camKeys = ['frontdoor', 'backyard', 'garage'];
    const videos = {};
    const canvas = document.createElement('canvas');
    canvas.width = 640;
    canvas.height = 360;
    const drawCtx = canvas.getContext('2d');
    drawCtx.imageSmoothingEnabled = true;
    drawCtx.imageSmoothingQuality = 'high';
    const blobUrls = {};
    const streams = {};

    for (const key of camKeys) {
      const video = document.createElement('video');
      video.src = '/static/vendor/demo/cam-' + key + '.mp4';
      video.muted = true;
      video.loop = true;
      video.playsInline = true;
      video.style.cssText = 'position:fixed;top:-9999px;width:1px;height:1px;opacity:0';
      document.body.appendChild(video);
      video.play().catch(() => {});
      videos[key] = video;
      streams[key] = ctx.stream('cameras:' + key);
    }

    // Pull-based: capture next frame only after previous blob is created.
    // Each camera runs its own async loop — no timer accumulation, no queue.
    for (const key of camKeys) {
      captureLoop(key);
    }

    function captureLoop(key) {
      const video = videos[key];
      if (!video || video.readyState < 2) {
        // Video not ready yet — retry shortly
        ctx.timeout(() => captureLoop(key), 200);
        return;
      }
      drawCtx.drawImage(video, 0, 0, 640, 360);
      canvas.toBlob(blob => {
        if (!blob) { ctx.timeout(() => captureLoop(key), 100); return; }
        if (blobUrls[key]) URL.revokeObjectURL(blobUrls[key]);
        blobUrls[key] = URL.createObjectURL(blob);
        // Push through the same stream API a real backend would use —
        // never via the vault. The ACK gate on the consumer paces us.
        streams[key].emit(blobUrls[key]);
        requestAnimationFrame(() => captureLoop(key));
      }, 'image/webp', 0.7);
    }

    // Motion simulation
    ctx.interval(() => {
      const state = ctx.vault.get('state') || {};
      const cameras = (state.cameras || []).map(c => ({
        ...c,
        motion: c.id === 'frontdoor' ? true : c.motion,
      }));
      ctx.vault.set('state', { ...state, cameras });

      ctx.timeout(() => {
        const cur = ctx.vault.get('state') || {};
        const cleared = (cur.cameras || []).map(c => ({
          ...c,
          motion: c.id === 'frontdoor' ? false : c.motion,
        }));
        ctx.vault.set('state', { ...cur, cameras: cleared });
      }, 8000);
    }, 20000 + Math.random() * 10000);
  }
}
