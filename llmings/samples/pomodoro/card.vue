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

<script setup>
import { ref, computed, watch, onMounted, onUnmounted } from 'vue'

const duration = ref(25)
const remaining = ref(25 * 60)
const running = ref(false)

const mins = computed(() => String(Math.floor(remaining.value / 60)).padStart(2, '0'))
const secs = computed(() => String(remaining.value % 60).padStart(2, '0'))
const progress = computed(() => {
  const total = duration.value * 60
  return total > 0 ? ((total - remaining.value) / total) * 100 : 0
})
const statusLabel = computed(() => {
  if (running.value) return 'FOCUSING'
  return remaining.value === duration.value * 60 ? 'READY' : 'PAUSED'
})

// Persist to localStorage
watch([remaining, duration], () => {
  localStorage.setItem('pomodoro', JSON.stringify({
    remaining: remaining.value,
    duration: duration.value,
  }))
})

onMounted(() => {
  const saved = JSON.parse(localStorage.getItem('pomodoro') || '{}')
  if (saved.remaining != null) remaining.value = saved.remaining
  if (saved.duration) duration.value = saved.duration
})

// Reset remaining when duration slider changes while paused
watch(duration, (val) => {
  if (!running.value) remaining.value = val * 60
})

// Timer — standard setInterval, no framework dependency
let timer
watch(running, (on) => {
  clearInterval(timer)
  if (on) {
    timer = setInterval(() => {
      if (remaining.value > 0) {
        remaining.value--
      } else {
        running.value = false
      }
    }, 1000)
  }
})
onUnmounted(() => clearInterval(timer))

function toggle() {
  running.value = !running.value
}

function reset() {
  running.value = false
  remaining.value = duration.value * 60
}
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
