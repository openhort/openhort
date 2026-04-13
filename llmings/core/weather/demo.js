export default {
  vault: {
    'state': {
      temp: 18,
      condition: 'Partly cloudy',
      icon: 'day',
      forecast: [
        { t: '12p', v: 19 },
        { t: '3p', v: 17 },
        { t: '6p', v: 14 },
        { t: '9p', v: 11 }
      ]
    }
  },

  simulate(ctx) {
    let temp = 18;
    let isDay = true;
    let tick = 0;

    ctx.interval(() => {
      tick++;

      // Temperature: random walk with mean-revert
      temp += (Math.random() - 0.5) * 1.2;
      temp += (18 - temp) * 0.03;
      temp = Math.max(5, Math.min(35, temp));

      // Toggle day/night every 30s
      if (tick % 30 === 0) {
        isDay = !isDay;
      }

      const condition = isDay
        ? (temp > 25 ? 'Sunny' : 'Partly cloudy')
        : (temp < 10 ? 'Clear night' : 'Mild evening');

      // Forecast: derive from current temp with offsets
      const forecast = [
        { t: '12p', v: Math.round(temp + 1 + Math.random()) },
        { t: '3p', v: Math.round(temp - 1 + Math.random()) },
        { t: '6p', v: Math.round(temp - 4 + Math.random()) },
        { t: '9p', v: Math.round(temp - 7 + Math.random()) }
      ];

      ctx.vault.set('state', {
        temp: Math.round(temp * 10) / 10,
        condition,
        icon: isDay ? 'day' : 'night',
        forecast
      });
    }, 2000);
  }
}
