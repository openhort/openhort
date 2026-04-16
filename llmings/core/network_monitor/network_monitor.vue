<template>
  <div class="netmon">
    <div class="netmon-down-row">
      <i class="ph ph-arrow-down netmon-arrow-down"></i>
      <span class="netmon-down-value">{{ downSpeed.val }}</span>
      <span class="netmon-down-unit">{{ downSpeed.unit }}</span>
    </div>

    <div class="netmon-up-row">
      <i class="ph ph-arrow-up netmon-arrow-up"></i>
      <span class="netmon-up-value">{{ upSpeed.val }}</span>
      <span class="netmon-up-unit">{{ upSpeed.unit }}</span>
    </div>

    <svg class="netmon-spark" viewBox="0 0 100 20" preserveAspectRatio="none">
      <defs>
        <linearGradient id="netGrad" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stop-color="var(--success)" stop-opacity="0.3" />
          <stop offset="100%" stop-color="var(--success)" stop-opacity="0" />
        </linearGradient>
      </defs>
      <polygon :points="fillPoints" fill="url(#netGrad)" />
      <polyline :points="linePoints" fill="none" stroke="var(--success)" stroke-width="1.5" />
    </svg>
  </div>
</template>

<script setup>
import { ref, computed, watch } from 'vue'
import { vaultRef } from 'llming'

const downloadBps = vaultRef('network-monitor', 'state.total_download_bps', 0)
const uploadBps   = vaultRef('network-monitor', 'state.total_upload_bps', 0)

const history = ref(Array(20).fill(0))

watch(downloadBps, (v) => {
  history.value = [...history.value.slice(-19), v]
})

function fmtSpeed(bps) {
  if (bps == null || bps === 0) return { val: '0', unit: 'B/s' }
  if (bps >= 1024 * 1024) return { val: (bps / (1024 * 1024)).toFixed(1), unit: 'MB/s' }
  if (bps >= 1024) return { val: (bps / 1024).toFixed(1), unit: 'KB/s' }
  return { val: Math.round(bps).toString(), unit: 'B/s' }
}

const downSpeed = computed(() => fmtSpeed(downloadBps.value))
const upSpeed   = computed(() => fmtSpeed(uploadBps.value))

function toPoints(arr) {
  return arr.map((v, i) => {
    const x = (i / (arr.length - 1)) * 100
    const maxBps = Math.max(...arr, 1)
    const y = 18 - (Math.min(v, maxBps) / maxBps) * 16
    return `${x},${y}`
  }).join(' ')
}

function toFillPoints(arr) {
  const line = toPoints(arr)
  return `0,19 ${line} 100,19`
}

const linePoints = computed(() => toPoints(history.value))
const fillPoints = computed(() => toFillPoints(history.value))
</script>

<style scoped>
.netmon {
  width: 100%;
  height: 100%;
  padding: 12px;
  display: flex;
  flex-direction: column;
  justify-content: space-between;
  text-align: left;
}

.netmon-down-row {
  display: flex;
  align-items: baseline;
  gap: 4px;
}

.netmon-arrow-down {
  font-size: 20px;
  color: var(--success);
  font-weight: 800;
  align-self: center;
}

.netmon-down-value {
  font-size: 34px;
  font-weight: 800;
  color: var(--success);
  line-height: 1;
  letter-spacing: -1px;
}

.netmon-down-unit {
  font-size: 13px;
  font-weight: 600;
  color: var(--success);
  opacity: 0.7;
}

.netmon-up-row {
  display: flex;
  align-items: baseline;
  gap: 4px;
  margin-top: 2px;
}

.netmon-arrow-up {
  font-size: 13px;
  color: rgba(255, 255, 255, 0.35);
  align-self: center;
}

.netmon-up-value {
  font-size: 16px;
  font-weight: 600;
  color: rgba(255, 255, 255, 0.35);
  line-height: 1;
}

.netmon-up-unit {
  font-size: 11px;
  color: rgba(255, 255, 255, 0.25);
}

.netmon-spark {
  width: 100%;
  height: 36px;
  flex-shrink: 0;
  margin-top: auto;
}
</style>
