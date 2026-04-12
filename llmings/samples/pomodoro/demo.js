export default {
  setup() {
    // Seed localStorage so the pomodoro mounts with clean 25-minute state
    localStorage.setItem('pomodoro', JSON.stringify({
      remaining: 1500,
      duration: 25,
    }));
  },

  teardown() {
    localStorage.removeItem('pomodoro');
  }
}
