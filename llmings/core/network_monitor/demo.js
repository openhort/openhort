export default {
  vault: {
    'state': { total_download_bps: 24 * 1024 * 1024, total_upload_bps: 3.2 * 1024 * 1024 }
  },

  simulate(ctx) {
    let down = 24 * 1024 * 1024;
    let up = 3.2 * 1024 * 1024;

    ctx.interval(() => {
      // Download: random walk around 24 MB/s with occasional spikes
      down += (Math.random() - 0.5) * 4 * 1024 * 1024;
      if (Math.random() < 0.05) down += 10 * 1024 * 1024;
      down += (24 * 1024 * 1024 - down) * 0.03;
      down = Math.max(512 * 1024, Math.min(80 * 1024 * 1024, down));

      // Upload: random walk around 3 MB/s
      up += (Math.random() - 0.5) * 1024 * 1024;
      up += (3.2 * 1024 * 1024 - up) * 0.04;
      up = Math.max(128 * 1024, Math.min(20 * 1024 * 1024, up));

      ctx.vault.set('state', {
        total_download_bps: Math.round(down),
        total_upload_bps: Math.round(up),
      });
    }, 1000);
  }
}
