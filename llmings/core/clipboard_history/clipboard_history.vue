<template>
  <div class="clip-thumb">
    <div class="clip-badge">{{ count }}</div>
    <div class="clip-stack">
      <div class="clip-card" v-for="(entry, i) in entries" :key="i">
        <div class="clip-card-icon" :style="{ background: entry.bg }">
          <i :class="entry.icon" :style="{ color: entry.color }"></i>
        </div>
        <div class="clip-card-text">{{ entry.text }}</div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { vaultRef } from 'llming'

const clipCount = vaultRef('clipboard-history', 'state.count', 0)
const clip1Text = vaultRef('clipboard-history', 'state.clip1', '')
const clip2Text = vaultRef('clipboard-history', 'state.clip2', '')
const clip3Text = vaultRef('clipboard-history', 'state.clip3', '')
const clip1Type = vaultRef('clipboard-history', 'state.clip1_type', 'text')
const clip2Type = vaultRef('clipboard-history', 'state.clip2_type', 'text')
const clip3Type = vaultRef('clipboard-history', 'state.clip3_type', 'text')

const count = computed(() => clipCount.value)

function entryMeta(type) {
  if (type === 'code') return { icon: 'ph ph-brackets-curly', color: '#c084fc', bg: 'rgba(192, 132, 252, 0.15)' }
  if (type === 'url')  return { icon: 'ph ph-link', color: '#60a5fa', bg: 'rgba(96, 165, 250, 0.15)' }
  return { icon: 'ph ph-text-aa', color: 'rgba(255,255,255,0.35)', bg: 'rgba(255,255,255,0.06)' }
}

const entries = computed(() => [
  { ...entryMeta(clip1Type.value), text: clip1Text.value },
  { ...entryMeta(clip2Type.value), text: clip2Text.value },
  { ...entryMeta(clip3Type.value), text: clip3Text.value },
])
</script>

<style scoped>
.clip-thumb {
  width: 100%;
  height: 100%;
  position: relative;
  padding: 8px;
  display: flex;
  flex-direction: column;
}

.clip-badge {
  position: absolute;
  top: 4px;
  left: 4px;
  z-index: 10;
  background: var(--primary, #3b82f6);
  color: #fff;
  font-size: 9px;
  font-weight: 700;
  min-width: 22px;
  height: 22px;
  border-radius: 11px;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 0 6px;
}

.clip-stack {
  display: flex;
  flex-direction: column;
  gap: 6px;
  flex: 1;
  justify-content: center;
  padding: 0 2px;
}

.clip-card {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 10px;
  background: var(--s2, rgba(255, 255, 255, 0.04));
  border: 1px solid var(--border, rgba(255, 255, 255, 0.08));
  border-radius: 10px;
}

.clip-card-icon {
  width: 28px;
  height: 28px;
  border-radius: 8px;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  font-size: 14px;
}

.clip-card-text {
  font-size: 11px;
  color: rgba(255, 255, 255, 0.6);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  min-width: 0;
  flex: 1;
}
</style>
