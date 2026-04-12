export default {
  setup() {
    localStorage.setItem('pomodoro', JSON.stringify({
      remaining: 1500,
      duration: 25,
      running: true,
    }));
  },

  teardown() {
    localStorage.removeItem('pomodoro');
  }
}
