export default {
  vault: {
    'state': { solar: 3.2, usage: 2.1, battery: 87 }
  },

  simulate(ctx) {
    let solar = 3.2, usage = 2.1, battery = 87;

    ctx.interval(() => {
      // Solar: slow random walk around 3.0-3.5
      solar += (Math.random() - 0.5) * 0.15;
      solar += (3.25 - solar) * 0.03;
      solar = Math.max(0.5, Math.min(5.5, solar));

      // Usage: varies around 2.0-2.5
      usage += (Math.random() - 0.5) * 0.12;
      usage += (2.25 - usage) * 0.03;
      usage = Math.max(0.3, Math.min(4.0, usage));

      // Battery: slow drift based on net export
      const net = solar - usage;
      battery += net * 0.1 + (Math.random() - 0.5) * 0.3;
      battery = Math.max(10, Math.min(100, battery));

      ctx.vault.set('state', {
        solar: Math.round(solar * 10) / 10,
        usage: Math.round(usage * 10) / 10,
        battery: Math.round(battery),
      });
    }, 3000);
  }
}
