export default {
  vault: {
    'state': {
      cameras: [
        { id: 'frontdoor', motion: false },
        { id: 'backyard', motion: false },
        { id: 'garage', motion: false },
      ]
    }
  },

  simulate(ctx) {
    ctx.interval(() => {
      const cameras = ctx.vault.get('state')?.cameras;
      if (!cameras) return;

      // Trigger motion on frontdoor
      const updated = cameras.map(c => ({
        ...c,
        motion: c.id === 'frontdoor' ? true : c.motion,
      }));
      ctx.vault.set('state', { cameras: updated });

      // Clear motion after 8 seconds
      setTimeout(() => {
        const current = ctx.vault.get('state')?.cameras;
        if (!current) return;
        const cleared = current.map(c => ({
          ...c,
          motion: c.id === 'frontdoor' ? false : c.motion,
        }));
        ctx.vault.set('state', { cameras: cleared });
      }, 8000);
    }, 20000 + Math.random() * 10000);
  }
}
