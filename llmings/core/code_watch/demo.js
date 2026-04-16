export default {
  vault: {
    'state': {
      hero_name: 'claude_dev',
      hero_active: true,
      hero_duration: '23m',
      hero_output: '> Building project...\n  Compiling 42 modules\n  Tests: 18 passed',
      token_used: 14200,
      token_max: 20000,
      sess1_name: 'claude_test',
      sess1_status: 'idle 4m',
      sess1_color: '#666',
      sess2_name: 'claude_fix',
      sess2_status: 'done 8m',
      sess2_color: 'var(--success)'
    }
  },

  simulate(ctx) {
    let tokens = 14200;
    let minutes = 23;
    let idleMin = 4;
    let doneMin = 8;
    let tick = 0;

    const outputs = [
      '> Building project...\n  Compiling 42 modules\n  Tests: 18 passed',
      '> Running tests...\n  test_session.py: 8 passed\n  test_stream.py: 3 passed',
      '> Analyzing code...\n  Found 2 issues\n  Fixing import order...',
      '> Deploying to staging...\n  Container built (2.1s)\n  Health check OK',
      '> Refactoring handler...\n  Updated 3 files\n  No breaking changes',
    ];

    ctx.interval(() => {
      tick++;

      // Token usage: slowly increases
      tokens += Math.round(80 + Math.random() * 120);
      if (tokens > 19500) tokens = 8000 + Math.random() * 3000;

      // Duration ticks up
      if (tick % 6 === 0) minutes++;
      if (tick % 4 === 0) idleMin++;
      if (tick % 5 === 0) doneMin++;

      // Rotate output every ~15s
      const outputIdx = Math.floor(tick / 15) % outputs.length;

      ctx.vault.set('state', {
        hero_name: 'claude_dev',
        hero_active: true,
        hero_duration: minutes + 'm',
        hero_output: outputs[outputIdx],
        token_used: tokens,
        token_max: 20000,
        sess1_name: 'claude_test',
        sess1_status: 'idle ' + idleMin + 'm',
        sess1_color: '#666',
        sess2_name: 'claude_fix',
        sess2_status: 'done ' + doneMin + 'm',
        sess2_color: 'var(--success)',
      });
    }, 2000);
  }
}
