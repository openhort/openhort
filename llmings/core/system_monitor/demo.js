export default {
  vault: {
    'state': { cpu_percent: 22, mem_percent: 77, disk_percent: 53 }
  },

  simulate(ctx) {
    ctx.interval(() => {
      const cpu = 15 + Math.random() * 40 | 0;
      const mem = 70 + Math.random() * 15 | 0;
      ctx.vault.set('state', { cpu_percent: cpu, mem_percent: mem, disk_percent: 53 });
      ctx.emit('system_metrics', { cpu_percent: cpu, mem_percent: mem, disk_percent: 53 });
    }, 1000);
  }
}
