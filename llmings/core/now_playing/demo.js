export default {
  vault: {
    'state': {
      track: 'Midnight City',
      artist: 'M83',
      album: "Hurry Up, We're Dreaming",
      playing: true,
      position: 158,
      duration: 243
    }
  },

  simulate(ctx) {
    let state = { ...this.vault.state };

    ctx.interval(() => {
      if (!state.playing) return;

      state.position += 1;
      if (state.position >= state.duration) {
        state.position = 0;
      }

      ctx.vault.set('state', { ...state });
    }, 1000);
  }
}
