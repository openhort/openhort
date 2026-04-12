<template>
  <q-card flat bordered class="system-card">
    <div class="row no-wrap justify-around items-center q-py-md q-px-sm">
      <div v-for="g in gauges" :key="g.label" class="column items-center gauge-col">
        <div class="gauge-ring">
          <q-circular-progress
            :value="g.value"
            :size="gaugeSize"
            :thickness="0.18"
            :color="g.color"
            track-color="grey-9"
            center-color="dark"
            rounded
          />
          <div class="gauge-center">
            <span class="gauge-value">{{ g.value }}</span>
            <span class="gauge-unit">%</span>
          </div>
        </div>
        <div class="gauge-label q-mt-xs">{{ g.label }}</div>
      </div>
    </div>
  </q-card>
</template>

<script setup>
import { ref, computed } from 'vue'
import { vaultRef } from 'llming'

const cpu  = vaultRef('system-monitor', 'state.cpu_percent', 0)
const mem  = vaultRef('system-monitor', 'state.mem_percent', 0)
const disk = vaultRef('system-monitor', 'state.disk_percent', 0)

const gaugeSize = '85px'

function color(val, warn, crit) {
  if (val >= crit) return 'red-5'
  if (val >= warn) return 'orange-5'
  return 'green-5'
}

const gauges = computed(() => [
  { label: 'CPU',  value: Math.round(cpu.value),  color: color(cpu.value, 70, 90) },
  { label: 'MEM',  value: Math.round(mem.value),  color: color(mem.value, 75, 90) },
  { label: 'DISK', value: Math.round(disk.value), color: color(disk.value, 80, 95) },
])
</script>

<style scoped>
.system-card {
  max-width: 380px;
  margin: 0 auto;
}
.gauge-ring {
  position: relative;
  display: inline-block;
}
.gauge-center {
  position: absolute;
  inset: 0;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  pointer-events: none;
}
.gauge-value {
  font-size: 18px;
  font-weight: 700;
  font-family: 'Courier New', monospace;
  color: #e2e8f0;
  line-height: 1;
}
.gauge-unit {
  font-size: 10px;
  color: #64748b;
  margin-top: 1px;
}
.gauge-label {
  font-size: 11px;
  font-weight: 600;
  color: #94a3b8;
  letter-spacing: 1px;
  text-transform: uppercase;
}
</style>
