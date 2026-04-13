export default {
  vault: {
    'state': {
      events: [
        { id: 1, title: 'Sprint Review', time: '10:30 AM', location: 'Room 4B', color: '#3b82f6', hasVideo: true },
        { id: 2, title: '1:1 with Sarah', time: '2:00 PM', location: 'Zoom', color: '#a855f7', hasVideo: true },
        { id: 3, title: 'Design Sync', time: '4:30 PM', location: 'Slack Huddle', color: '#22c55e', hasVideo: false }
      ],
      minutesToNext: 23
    }
  },

  simulate(ctx) {
    let minutes = 23;

    ctx.interval(() => {
      minutes = Math.max(1, minutes - 1);
      if (minutes <= 1) minutes = 45;

      const state = ctx.vault.get('state');
      ctx.vault.set('state', {
        ...state,
        minutesToNext: minutes
      });
    }, 60000);
  }
}
