export default {
  vault: {
    'state': {
      rooms: [
        { id: 'living', name: 'Living Room', icon: 'ph-fill ph-lamp', lightOn: true, temp: 22 },
        { id: 'bedroom', name: 'Bedroom', icon: 'ph-fill ph-bed', lightOn: false, temp: 19 },
        { id: 'kitchen', name: 'Kitchen', icon: 'ph-fill ph-cooking-pot', lightOn: true, temp: 21 },
        { id: 'office', name: 'Office', icon: 'ph-fill ph-desk', lightOn: false, temp: 20 },
      ]
    }
  },

  simulate(ctx) {
    ctx.interval(() => {
      const rooms = ctx.vault.get('state')?.rooms;
      if (!rooms) return;

      // Pick a random room and toggle it
      const idx = Math.floor(Math.random() * rooms.length);
      const updated = rooms.map((r, i) => {
        if (i !== idx) return r;
        // Slightly vary temp
        const tempDelta = (Math.random() - 0.5) * 0.6;
        return {
          ...r,
          lightOn: !r.lightOn,
          temp: Math.round(Math.max(17, Math.min(25, r.temp + tempDelta))),
        };
      });

      ctx.vault.set('state', { rooms: updated });
    }, 10000 + Math.random() * 5000);
  }
}
