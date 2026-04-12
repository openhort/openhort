export default {
  setup(ctx) {
    // Pomodoro uses localStorage directly — seed it for demo
    localStorage.setItem('pomodoro', JSON.stringify({
      remaining: 1500,
      duration: 25,
    }));
  },

  teardown() {
    localStorage.removeItem('pomodoro');
  }
}
