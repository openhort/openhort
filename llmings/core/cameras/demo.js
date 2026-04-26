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
    const canvas = document.createElement('canvas');
    canvas.width = 640;
    canvas.height = 360;
    const drawCtx = canvas.getContext('2d');
    drawCtx.imageSmoothingEnabled = true;
    drawCtx.imageSmoothingQuality = 'high';
    const blobUrls = {};
    const streams = {};

    for (const key of camKeys) {
      streams[key] = ctx.stream('cameras:' + key);
      runDecoderLoop(key);
    }

    // Decode animated WebP frame-by-frame via ImageDecoder. <img> playback
    // gets aggressively throttled by Chromium when the element isn't
    // visibly composited (clip-path, off-screen, opacity 0 — all of those
    // freeze the animation). ImageDecoder runs in worker-friendly land
    // with no visibility hooks, giving us deterministic frame advance at
    // the cadence the source file declares.
    async function runDecoderLoop(key) {
      const url = ctx.assetUrl('cam-' + key + '.webp');
      let resp;
      try { resp = await fetch(url); }
      catch (e) { ctx.timeout(() => runDecoderLoop(key), 1000); return; }
      const buf = await resp.arrayBuffer();
      if (typeof ImageDecoder === 'undefined') {
        // Fallback: legacy <img> path (rarely hit; very old browser).
        const img = new Image();
        img.src = url;
        await img.decode().catch(() => {});
        let i = 0;
        const tick = () => {
          drawCtx.drawImage(img, 0, 0, 640, 360);
          canvas.toBlob(b => { if (b) emitBlob(key, b); }, 'image/webp', 0.7);
          i++; ctx.timeout(tick, 100);
        };
        tick();
        return;
      }
      const decoder = new ImageDecoder({ data: buf, type: 'image/webp' });
      await decoder.tracks.ready;
      const track = decoder.tracks.selectedTrack;
      const frameCount = track.frameCount || 1;
      let idx = 0;
      while (true) {
        let result;
        try { result = await decoder.decode({ frameIndex: idx % frameCount }); }
        catch (e) { await new Promise(r => ctx.timeout(r, 100)); continue; }
        const { image, complete: _c } = result;
        const dur = (image.duration || 100000) / 1000; // µs → ms
        drawCtx.drawImage(image, 0, 0, 640, 360);
        image.close();
        await new Promise(resolve => {
          canvas.toBlob(b => { if (b) emitBlob(key, b); resolve(); }, 'image/webp', 0.7);
        });
        idx++;
        // Pace to the source's declared frame duration; clamp to keep CPU sane.
        await new Promise(r => ctx.timeout(r, Math.max(40, Math.min(dur, 250))));
      }
    }

    function emitBlob(key, blob) {
      if (blobUrls[key]) URL.revokeObjectURL(blobUrls[key]);
      blobUrls[key] = URL.createObjectURL(blob);
      // Push through the same stream API a real backend would use —
      // never via the vault. The ACK gate on the consumer paces us.
      streams[key].emit(blobUrls[key]);
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
