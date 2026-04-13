<template>
  <div class="energy-root">
    <div class="energy-row">
      <div class="energy-stat solar">
        <i class="ph-fill ph-sun" />
        <span class="energy-value">{{ solar.toFixed(1) }}</span>
        <span class="energy-unit">kW</span>
        <span class="energy-label">Solar</span>
      </div>
      <div class="energy-stat usage">
        <i class="ph-fill ph-plug" />
        <span class="energy-value">{{ usage.toFixed(1) }}</span>
        <span class="energy-unit">kW</span>
        <span class="energy-label">Usage</span>
      </div>
    </div>

    <div class="energy-flow">
      <svg viewBox="0 0 200 24" class="flow-svg">
        <defs>
          <linearGradient id="flowGrad" x1="0" y1="0" x2="1" y2="0">
            <stop offset="0%" stop-color="rgb(34,197,94)" />
            <stop offset="100%" stop-color="rgb(59,130,246)" />
          </linearGradient>
        </defs>
        <rect x="10" y="9" width="180" height="6" rx="3" fill="rgba(255,255,255,.06)" />
        <rect x="10" y="9" width="180" height="6" rx="3" fill="url(#flowGrad)" opacity=".3" />
        <circle :cx="flowX" cy="12" r="5" fill="url(#flowGrad)" opacity=".8">
          <animate attributeName="cx" :from="flowFrom" :to="flowTo" dur="2s" repeatCount="indefinite" />
        </circle>
      </svg>
    </div>

    <div class="energy-row">
      <div class="energy-stat export">
        <i class="ph-fill ph-arrow-fat-up" v-if="netExport >= 0" />
        <i class="ph-fill ph-arrow-fat-down" v-else />
        <span class="energy-value" :class="{ positive: netExport >= 0, negative: netExport < 0 }">
          {{ netExport >= 0 ? '+' : '' }}{{ netExport.toFixed(1) }}
        </span>
        <span class="energy-unit">kW</span>
        <span class="energy-label">{{ netExport >= 0 ? 'Export' : 'Import' }}</span>
      </div>
      <div class="energy-stat battery">
        <i :class="batteryIcon" />
        <span class="energy-value">{{ battery }}</span>
        <span class="energy-unit">%</span>
        <span class="energy-label">Battery</span>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed } from 'vue'
import { vaultRef } from 'llming'

const solarRef = vaultRef('energy', 'state.solar', 3.2)
const usageRef = vaultRef('energy', 'state.usage', 2.1)
const batteryRef = vaultRef('energy', 'state.battery', 87)

const solar = computed(() => solarRef.value || 0)
const usage = computed(() => usageRef.value || 0)
const battery = computed(() => batteryRef.value || 0)

const netExport = computed(() => solar.value - usage.value)

const flowFrom = computed(() => netExport.value >= 0 ? '20' : '180')
const flowTo = computed(() => netExport.value >= 0 ? '180' : '20')
const flowX = computed(() => netExport.value >= 0 ? 20 : 180)

const batteryIcon = computed(() => {
  const b = battery.value
  if (b >= 75) return 'ph-fill ph-battery-full'
  if (b >= 50) return 'ph-fill ph-battery-high'
  if (b >= 25) return 'ph-fill ph-battery-medium'
  return 'ph-fill ph-battery-low'
})
</script>

<style scoped>
.energy-root {
  width: 100%;
  height: 100%;
  padding: 12px;
  display: flex;
  flex-direction: column;
  justify-content: space-between;
  box-sizing: border-box;
}

.energy-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.energy-stat {
  display: flex;
  align-items: baseline;
  gap: 4px;
  flex-wrap: wrap;
}

.energy-stat i {
  font-size: 16px;
  align-self: center;
}

.solar i { color: rgb(34, 197, 94); }
.usage i { color: rgb(59, 130, 246); }
.export i { color: rgb(168, 162, 158); }
.battery i { color: rgb(245, 158, 11); }

.energy-value {
  font-size: 24px;
  font-weight: 700;
  color: rgba(255, 255, 255, .85);
  line-height: 1;
}

.energy-value.positive { color: rgb(34, 197, 94); }
.energy-value.negative { color: rgb(239, 68, 68); }

.energy-unit {
  font-size: 11px;
  color: rgba(255, 255, 255, .4);
  font-weight: 500;
}

.energy-label {
  width: 100%;
  font-size: 9px;
  color: rgba(255, 255, 255, .3);
  text-transform: uppercase;
  letter-spacing: 0.5px;
  margin-top: 2px;
}

.energy-flow {
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 4px 0;
}

.flow-svg {
  width: 100%;
  height: 24px;
}
</style>
