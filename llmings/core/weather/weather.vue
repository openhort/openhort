<template>
  <div class="weather-card">
    <div class="weather-main">
      <div class="weather-temp">{{ Math.round(temp) }}<span class="weather-deg">&deg;</span></div>
      <i :class="weatherIcon" class="weather-icon"></i>
    </div>
    <div class="weather-condition">{{ condition }}</div>
    <div class="weather-forecast">
      <div v-for="slot in forecast" :key="slot.t" class="forecast-slot">
        <div class="forecast-bar-track">
          <div class="forecast-bar-fill" :style="barStyle(slot.v)"></div>
        </div>
        <div class="forecast-temp">{{ slot.v }}&deg;</div>
        <div class="forecast-time">{{ slot.t }}</div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed } from 'vue'
import { vaultRef } from 'llming'

const temp = vaultRef('weather', 'state.temp', 18)
const condition = vaultRef('weather', 'state.condition', 'Partly cloudy')
const icon = vaultRef('weather', 'state.icon', 'day')
const forecast = vaultRef('weather', 'state.forecast', [
  { t: '12p', v: 19 },
  { t: '3p', v: 17 },
  { t: '6p', v: 14 },
  { t: '9p', v: 11 }
])

const weatherIcon = computed(() => {
  return icon.value === 'night'
    ? 'ph-fill ph-moon-stars'
    : 'ph-fill ph-cloud-sun'
})

function barStyle(v) {
  const temps = forecast.value.map(s => s.v)
  const min = Math.min(...temps) - 2
  const max = Math.max(...temps) + 2
  const pct = ((v - min) / (max - min)) * 100
  const hue = Math.max(0, Math.min(240, (1 - (v - min) / (max - min)) * 240))
  return {
    height: pct + '%',
    backgroundColor: `hsl(${hue}, 60%, 55%)`
  }
}
</script>

<style scoped>
.weather-card {
  width: 100%;
  height: 100%;
  padding: 12px;
  display: flex;
  flex-direction: column;
  justify-content: space-between;
}
.weather-main {
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.weather-temp {
  font-size: 36px;
  font-weight: 200;
  color: #e2e8f0;
  line-height: 1;
}
.weather-deg {
  font-size: 20px;
  vertical-align: super;
  color: #94a3b8;
}
.weather-icon {
  font-size: 32px;
  color: #fbbf24;
}
.weather-condition {
  font-size: 13px;
  color: #94a3b8;
  margin-top: 4px;
}
.weather-forecast {
  display: flex;
  gap: 8px;
  align-items: flex-end;
  margin-top: auto;
  padding-top: 12px;
}
.forecast-slot {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 4px;
}
.forecast-bar-track {
  width: 16px;
  height: 40px;
  background: rgba(255, 255, 255, 0.06);
  border-radius: 4px;
  display: flex;
  align-items: flex-end;
  overflow: hidden;
}
.forecast-bar-fill {
  width: 100%;
  border-radius: 4px 4px 0 0;
  transition: height 0.3s ease;
}
.forecast-temp {
  font-size: 11px;
  color: #cbd5e1;
  font-weight: 600;
}
.forecast-time {
  font-size: 10px;
  color: #64748b;
}
</style>
