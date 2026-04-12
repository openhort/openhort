<template>
  <q-card flat bordered class="pomodoro-card q-pa-lg">
    <q-card-section class="text-center">
      <div class="text-overline text-grey-6 q-mb-sm">POMODORO</div>

      <q-circular-progress
        :value="progress"
        size="200px"
        :thickness="0.08"
        :color="running ? 'green-5' : 'blue-5'"
        track-color="grey-9"
        center-color="dark"
        rounded
        class="q-mb-md"
      >
        <div class="column items-center justify-center">
          <span
            class="time-display text-h3 text-weight-bold"
            :class="{ 'text-green-5': running, 'text-grey-1': !running }"
          >
            {{ mins }}:{{ secs }}
          </span>
          <span class="text-caption text-grey-6 q-mt-xs">
            {{ statusLabel }}
          </span>
        </div>
      </q-circular-progress>
    </q-card-section>

    <q-card-section class="text-center q-pt-none">
      <div class="q-gutter-sm">
        <q-btn
          :label="running ? 'Pause' : 'Start'"
          :color="running ? 'red-5' : 'green-6'"
          :icon="running ? 'pause' : 'play_arrow'"
          unelevated
          rounded
          style="min-width: 130px"
          @click="toggle"
        />
        <q-btn
          label="Reset"
          icon="restart_alt"
          flat
          rounded
          color="grey-5"
          @click="reset"
        />
      </div>
    </q-card-section>

    <q-card-section class="q-pt-sm">
      <div class="text-caption text-grey-6 q-mb-xs">Duration</div>
      <q-slider
        v-model="duration"
        :min="5"
        :max="60"
        :step="5"
        :disable="running"
        label
        :label-value="duration + ' min'"
        color="blue-5"
        label-always
        switch-label-side
      />
    </q-card-section>
  </q-card>
</template>

<script>
export default {
  name: 'PomodoroTimer',

  data() {
    return {
      remaining: 25 * 60,
      running: false,
      duration: 25,
    };
  },

  computed: {
    mins() {
      return String(Math.floor(this.remaining / 60)).padStart(2, '0');
    },
    secs() {
      return String(this.remaining % 60).padStart(2, '0');
    },
    progress() {
      const total = this.duration * 60;
      return total > 0 ? ((total - this.remaining) / total) * 100 : 0;
    },
    statusLabel() {
      if (this.running) return 'FOCUSING';
      return this.remaining === this.duration * 60 ? 'READY' : 'PAUSED';
    },
  },

  async mounted() {
    // Load saved state from vault
    const state = await this.$llming.vault.get('state');
    if (state && state.remaining !== undefined) {
      this.remaining = state.remaining;
      this.duration = state.duration || 25;
    }

    // Use system tick:1hz pulse — no setInterval needed
    this.$llming.subscribe('tick:1hz', () => {
      if (this.running && this.remaining > 0) {
        this.remaining--;
        this.saveState();
      } else if (this.running && this.remaining <= 0) {
        this.running = false;
        this.$q.notify({
          message: 'Pomodoro complete!',
          color: 'positive',
          icon: 'check_circle',
          position: 'top',
        });
        this.saveState();
      }
    });
  },

  methods: {
    toggle() {
      this.running = !this.running;
      this.saveState();
    },

    reset() {
      this.running = false;
      this.remaining = this.duration * 60;
      this.saveState();
    },

    saveState() {
      this.$llming.vault.set('state', {
        remaining: this.remaining,
        running: this.running,
        duration: this.duration,
      });
    },
  },

  watch: {
    duration(val) {
      if (!this.running) {
        this.remaining = val * 60;
      }
    },
  },
};
</script>

<style scoped>
.pomodoro-card {
  max-width: 380px;
  margin: 0 auto;
}

.time-display {
  font-family: 'Courier New', monospace;
  letter-spacing: 2px;
}
</style>
