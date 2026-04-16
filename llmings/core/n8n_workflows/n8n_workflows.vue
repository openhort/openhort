<template>
  <div class="n8n-root">
    <div class="n8n-cards">
      <div class="n8n-stat n8n-stat-passed">
        <i class="ph-fill ph-check-circle n8n-stat-icon n8n-icon-green"></i>
        <div class="n8n-stat-count n8n-count-green">{{ passed }}</div>
        <div class="n8n-stat-label">passed</div>
        <svg class="n8n-sparkline" viewBox="0 0 40 12" preserveAspectRatio="none">
          <polyline :points="passedSparkline" fill="none" stroke="rgba(34,197,94,.5)" stroke-width="1.5" />
        </svg>
      </div>

      <div class="n8n-stat" :class="failed > 0 ? 'n8n-stat-failed n8n-fail-glow' : 'n8n-stat-neutral'">
        <i class="ph-fill ph-x-circle n8n-stat-icon" :class="failed > 0 ? 'n8n-icon-red' : 'n8n-icon-dim'"></i>
        <div class="n8n-stat-count" :class="failed > 0 ? 'n8n-count-red' : 'n8n-count-dim'">{{ failed }}</div>
        <div class="n8n-stat-label">failed</div>
        <svg class="n8n-sparkline" viewBox="0 0 40 12" preserveAspectRatio="none">
          <polyline :points="failedSparkline" fill="none" :stroke="failed > 0 ? 'rgba(239,68,68,.5)' : 'rgba(255,255,255,.1)'" stroke-width="1.5" />
        </svg>
      </div>

      <div class="n8n-stat n8n-stat-running">
        <i class="ph-fill ph-play-circle n8n-stat-icon n8n-icon-blue"></i>
        <div class="n8n-stat-count n8n-count-blue">{{ running }}</div>
        <div class="n8n-stat-label">active</div>
        <svg class="n8n-sparkline" viewBox="0 0 40 12" preserveAspectRatio="none">
          <polyline :points="runningSparkline" fill="none" stroke="rgba(96,165,250,.5)" stroke-width="1.5" />
        </svg>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, watch } from 'vue'
import { vaultRef } from 'llming'

const passed  = vaultRef('n8n-workflows', 'state.passed', 12)
const failed  = vaultRef('n8n-workflows', 'state.failed', 0)
const running = vaultRef('n8n-workflows', 'state.running', 2)

const passedHistory  = ref(Array(10).fill(12))
const failedHistory  = ref(Array(10).fill(0))
const runningHistory = ref(Array(10).fill(2))

watch(passed, (v) => {
  passedHistory.value = [...passedHistory.value.slice(-9), v]
})
watch(failed, (v) => {
  failedHistory.value = [...failedHistory.value.slice(-9), v]
})
watch(running, (v) => {
  runningHistory.value = [...runningHistory.value.slice(-9), v]
})

function sparkPoints(arr) {
  if (!arr.length) return ''
  const max = Math.max(...arr, 1)
  return arr.map((v, i) => {
    const x = (i / (arr.length - 1)) * 40
    const y = 10 - (v / max) * 8
    return `${x},${y}`
  }).join(' ')
}

const passedSparkline  = computed(() => sparkPoints(passedHistory.value))
const failedSparkline  = computed(() => sparkPoints(failedHistory.value))
const runningSparkline = computed(() => sparkPoints(runningHistory.value))
</script>

<style scoped>
.n8n-root {
  width: 100%;
  height: 100%;
  display: flex;
  align-items: center;
  padding: 10px;
}

.n8n-cards {
  display: flex;
  gap: 8px;
  justify-content: center;
  width: 100%;
}

.n8n-stat {
  flex: 1;
  border-radius: 10px;
  padding: 8px 4px;
  text-align: center;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 1px;
  position: relative;
  overflow: hidden;
}

.n8n-stat-passed {
  background: rgba(34, 197, 94, 0.08);
  border: 1px solid rgba(34, 197, 94, 0.2);
}

.n8n-stat-failed {
  background: rgba(239, 68, 68, 0.1);
  border: 1px solid rgba(239, 68, 68, 0.25);
}

.n8n-stat-neutral {
  background: rgba(255, 255, 255, 0.03);
  border: 1px solid rgba(255, 255, 255, 0.06);
}

.n8n-stat-running {
  background: rgba(96, 165, 250, 0.08);
  border: 1px solid rgba(96, 165, 250, 0.2);
}

.n8n-fail-glow {
  box-shadow: 0 0 12px rgba(239, 68, 68, 0.15);
}

.n8n-stat-icon {
  font-size: 18px;
}

.n8n-icon-green { color: #22c55e; }
.n8n-icon-red   { color: #ef4444; }
.n8n-icon-blue  { color: #60a5fa; }
.n8n-icon-dim   { color: rgba(255, 255, 255, 0.2); }

.n8n-stat-count {
  font-size: 24px;
  font-weight: 700;
  line-height: 1;
}

.n8n-count-green { color: #22c55e; }
.n8n-count-red   { color: #ef4444; }
.n8n-count-blue  { color: #60a5fa; }
.n8n-count-dim   { color: rgba(255, 255, 255, 0.25); }

.n8n-stat-label {
  font-size: 10px;
  color: rgba(255, 255, 255, 0.35);
  text-transform: uppercase;
  letter-spacing: 0.5px;
}

.n8n-sparkline {
  width: 100%;
  height: 12px;
  margin-top: 4px;
}
</style>
