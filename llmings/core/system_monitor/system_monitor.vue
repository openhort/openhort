<template>
  <div class="sysmon">
    <div class="sysmon-cpu-row">
      <span class="sysmon-cpu-value" :style="{ color: cpuColor }">{{ Math.round(cpu) }}</span>
      <span class="sysmon-cpu-unit" :style="{ color: cpuColor }">%</span>
    </div>

    <svg class="sysmon-spark" viewBox="0 0 100 28" preserveAspectRatio="none">
      <defs>
        <linearGradient id="cpuGrad" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" :stop-color="cpuColor" stop-opacity="0.3" />
          <stop offset="100%" :stop-color="cpuColor" stop-opacity="0" />
        </linearGradient>
        <linearGradient id="memGrad" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stop-color="#a78bfa" stop-opacity="0.2" />
          <stop offset="100%" stop-color="#a78bfa" stop-opacity="0" />
        </linearGradient>
      </defs>
      <!-- MEM fill -->
      <polygon :points="memFillPoints" fill="url(#memGrad)" />
      <!-- CPU fill -->
      <polygon :points="cpuFillPoints" fill="url(#cpuGrad)" />
      <!-- MEM line -->
      <polyline :points="memLinePoints" fill="none" stroke="#a78bfa" stroke-width="1.2" stroke-dasharray="3,2" />
      <!-- CPU line -->
      <polyline :points="cpuLinePoints" fill="none" :stroke="cpuColor" stroke-width="1.5" />
    </svg>

    <div class="sysmon-legend">
      <span class="sysmon-legend-item">
        <span class="sysmon-dot" :style="{ background: cpuColor }"></span>
        CPU
      </span>
      <span class="sysmon-legend-item">
        <span class="sysmon-dot" style="background:#a78bfa"></span>
        RAM {{ Math.round(mem) }}%
      </span>
      <span class="sysmon-legend-item sysmon-dim">
        <i class="ph ph-hard-drives sysmon-disk-icon"></i>
        Disk {{ Math.round(disk) }}%
      </span>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, watch } from 'vue'
import { vaultRef } from 'llming'

const cpu  = vaultRef('system-monitor', 'state.cpu_percent', 0)
const mem  = vaultRef('system-monitor', 'state.mem_percent', 0)
const disk = vaultRef('system-monitor', 'state.disk_percent', 0)

const cpuHistory = ref(Array(20).fill(0))
const memHistory = ref(Array(20).fill(0))

watch(cpu, (v) => {
  cpuHistory.value = [...cpuHistory.value.slice(-19), v]
})
watch(mem, (v) => {
  memHistory.value = [...memHistory.value.slice(-19), v]
})

const cpuColor = computed(() => {
  const v = cpu.value
  if (v >= 90) return '#ef4444'
  if (v >= 70) return '#f59e0b'
  return '#22d3ee'
})

function toPoints(arr) {
  return arr.map((v, i) => {
    const x = (i / (arr.length - 1)) * 100
    const y = 26 - (Math.min(v, 100) / 100) * 24
    return `${x},${y}`
  }).join(' ')
}

function toFillPoints(arr) {
  const line = toPoints(arr)
  return `0,27 ${line} 100,27`
}

const cpuLinePoints = computed(() => toPoints(cpuHistory.value))
const memLinePoints = computed(() => toPoints(memHistory.value))
const cpuFillPoints = computed(() => toFillPoints(cpuHistory.value))
const memFillPoints = computed(() => toFillPoints(memHistory.value))
</script>

<style scoped>
.sysmon {
  width: 100%;
  height: 100%;
  padding: 12px;
  display: flex;
  flex-direction: column;
  text-align: left;
}

.sysmon-cpu-row {
  display: flex;
  align-items: baseline;
  gap: 1px;
  margin-bottom: 6px;
}

.sysmon-cpu-value {
  font-size: 38px;
  font-weight: 800;
  letter-spacing: -1px;
  line-height: 1;
}

.sysmon-cpu-unit {
  font-size: 16px;
  font-weight: 700;
  opacity: 0.7;
}

.sysmon-spark {
  width: 100%;
  height: 28px;
  flex-shrink: 0;
  margin-bottom: 8px;
}

.sysmon-legend {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}

.sysmon-legend-item {
  display: flex;
  align-items: center;
  gap: 4px;
  font-size: 10px;
  color: rgba(255, 255, 255, 0.6);
  font-weight: 500;
}

.sysmon-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  flex-shrink: 0;
}

.sysmon-dim {
  color: rgba(255, 255, 255, 0.3);
}

.sysmon-disk-icon {
  font-size: 11px;
}
</style>
