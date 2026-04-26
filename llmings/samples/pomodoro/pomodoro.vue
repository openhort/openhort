<template>
  <div class="pomodoro-card">
    <div class="pomo-overline">POMODORO</div>

    <div class="progress-ring">
      <svg :width="ringSize" :height="ringSize" viewBox="0 0 100 100" class="ring-svg">
        <circle cx="50" cy="50" :r="ringR" fill="none" stroke="var(--track)" :stroke-width="ringStroke" />
        <circle cx="50" cy="50" :r="ringR" fill="none" :stroke="ringColor" :stroke-width="ringStroke"
          stroke-linecap="round"
          :stroke-dasharray="ringCirc"
          :stroke-dashoffset="ringOffset"
          transform="rotate(-90 50 50)" />
      </svg>
      <div class="ring-center">
        <span class="time-display" :class="{ running }">{{ mins }}:{{ secs }}</span>
        <span class="status-label">{{ statusLabel }}</span>
      </div>
    </div>

    <div class="pomo-controls">
      <button class="btn-primary" :class="{ paused: running }" @click="toggle">
        <i :class="running ? 'ph ph-pause' : 'ph ph-play'"></i>
        {{ running ? 'Pause' : 'Start' }}
      </button>
      <button class="btn-flat" @click="reset">
        <i class="ph ph-arrow-counter-clockwise"></i> Reset
      </button>
    </div>

    <div class="pomo-duration">
      <div class="dur-label">Duration <span class="dur-value">{{ duration }} min</span></div>
      <input type="range" v-model.number="duration" min="5" max="60" step="5" :disabled="running" class="dur-slider">
    </div>
  </div>
</template>

<script setup>
import { ref, computed, watch, onUnmounted } from 'vue'

const ringSize = 200
const ringStroke = 8
const ringR = (100 - ringStroke) / 2
const ringCirc = 2 * Math.PI * ringR

const duration = ref(25)
const remaining = ref(25 * 60)
const running = ref(false)

const mins = computed(() => String(Math.floor(remaining.value / 60)).padStart(2, '0'))
const secs = computed(() => String(remaining.value % 60).padStart(2, '0'))
const progress = computed(() => {
  const total = duration.value * 60
  return total > 0 ? ((total - remaining.value) / total) * 100 : 0
})
const ringOffset = computed(() => ringCirc * (1 - progress.value / 100))
const ringColor = computed(() => running.value ? '#22c55e' : '#3b82f6')
const statusLabel = computed(() => {
  if (running.value) return 'FOCUSING'
  return remaining.value === duration.value * 60 ? 'READY' : 'PAUSED'
})

const state = localRef('timer', { remaining: 25 * 60, running: false, duration: 25 })
watch([remaining, running, duration], () => {
  state.value = { remaining: remaining.value, running: running.value, duration: duration.value }
})
watch(state, (s) => {
  if (!s) return
  if (s.remaining != null) remaining.value = s.remaining
  if (s.duration) duration.value = s.duration
  if (s.running != null) running.value = s.running
}, { immediate: true })

watch(duration, (val) => {
  if (!running.value) remaining.value = val * 60
})

let timer
watch(running, (on) => {
  clearInterval(timer)
  if (on) {
    timer = setInterval(() => {
      if (remaining.value > 0) remaining.value--
      else running.value = false
    }, 1000)
  }
})
onUnmounted(() => clearInterval(timer))

function toggle() { running.value = !running.value }
function reset() {
  running.value = false
  remaining.value = duration.value * 60
}
</script>

<style scoped>
.pomodoro-card {
  --track: rgba(148,163,184,0.18);
  max-width: 380px;
  margin: 0 auto;
  padding: 24px;
  text-align: center;
  background: var(--el-surface, transparent);
  border: 1px solid var(--border, rgba(148,163,184,0.2));
  border-radius: 10px;
}
.pomo-overline {
  font-size: 11px;
  letter-spacing: 1.5px;
  color: var(--el-text-dim, #94a3b8);
  margin-bottom: 12px;
}
.progress-ring {
  position: relative;
  display: inline-block;
  margin: 8px 0 16px;
}
.ring-center {
  position: absolute;
  inset: 0 0 8px 0;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  pointer-events: none;
}
.time-display {
  font-family: 'Courier New', monospace;
  font-size: 38px;
  font-weight: bold;
  letter-spacing: 2px;
  color: var(--el-text, #f1f5f9);
}
.time-display.running { color: #22c55e; }
.status-label {
  margin-top: 4px;
  font-size: 11px;
  color: var(--el-text-dim, #94a3b8);
}
.pomo-controls {
  display: flex;
  gap: 8px;
  justify-content: center;
  margin-bottom: 16px;
}
.btn-primary, .btn-flat {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 8px 18px;
  border: none;
  border-radius: 999px;
  cursor: pointer;
  font-size: 13px;
}
.btn-primary {
  background: #22c55e;
  color: #fff;
  min-width: 130px;
  justify-content: center;
}
.btn-primary.paused { background: #ef4444; }
.btn-flat {
  background: transparent;
  color: var(--el-text-dim, #94a3b8);
}
.pomo-duration { text-align: left; }
.dur-label {
  font-size: 11px;
  color: var(--el-text-dim, #94a3b8);
  margin-bottom: 4px;
  display: flex;
  justify-content: space-between;
}
.dur-value { color: #3b82f6; font-weight: bold; }
.dur-slider { width: 100%; }
</style>