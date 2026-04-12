export default {
  vault: {
    'state': { cpu_percent: 22, mem_percent: 77, disk_percent: 53 }
  },

  simulate(ctx) {
    let cpu = 22, mem = 77, disk = 53;

    ctx.interval(() => {
      // CPU: random walk, mean-reverts toward 25%, occasional spikes
      cpu += (Math.random() - 0.52) * 6;
      if (Math.random() < 0.03) cpu += 20 + Math.random() * 15;
      cpu = Math.max(3, Math.min(98, cpu));
      cpu += (25 - cpu) * 0.02;

      // MEM: very slow drift
      mem += (Math.random() - 0.5) * 0.3;
      mem = Math.max(65, Math.min(88, mem));

      // DISK: glacial — changes ~0.1% per minute
      disk += (Math.random() - 0.48) * 0.02;
      disk = Math.max(45, Math.min(70, disk));

      ctx.vault.set('state', {
        cpu_percent: Math.round(cpu),
        mem_percent: Math.round(mem),
        disk_percent: Math.round(disk),
      });
    }, 1000);
  }
}
