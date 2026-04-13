export default {
  vault: {
    'state': { passed: 12, failed: 0, running: 2 }
  },

  simulate(ctx) {
    let passed = 12, failed = 0, running = 2;

    ctx.interval(() => {
      // Slowly increment passed
      if (Math.random() < 0.3) {
        passed += 1;
      }

      // Occasionally add failures
      if (Math.random() < 0.05) {
        failed += 1;
      }
      // Occasionally clear failures
      if (failed > 0 && Math.random() < 0.1) {
        failed = Math.max(0, failed - 1);
      }

      // Running fluctuates
      if (Math.random() < 0.2) {
        running = Math.max(0, Math.min(5, running + (Math.random() < 0.5 ? 1 : -1)));
      }

      ctx.vault.set('state', { passed, failed, running });
    }, 3000);
  }
}
