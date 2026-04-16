<template>
  <div class="cw-card">
    <!-- Hero session -->
    <div class="cw-hero">
      <div class="cw-hero-header">
        <div class="cw-ring" :class="{ active: heroActive }">
          <div class="cw-dot" :style="{ background: heroActive ? 'var(--purple)' : '#666' }"></div>
        </div>
        <div class="cw-hero-info">
          <div class="cw-hero-name">{{ heroName }}</div>
          <div class="cw-hero-dur">{{ heroDuration }}</div>
        </div>
      </div>
      <div class="cw-output">{{ heroOutput }}</div>
      <div class="cw-token-row">
        <div class="cw-token-bar">
          <div class="cw-token-fill" :style="{ width: tokenPct + '%', background: 'var(--purple)' }"></div>
        </div>
        <span class="cw-token-label">{{ tokenLabel }}</span>
      </div>
    </div>

    <!-- Compact sessions -->
    <div class="cw-compact-row">
      <div class="cw-compact" v-for="s in compactSessions" :key="s.name">
        <div class="cw-compact-dot" :style="{ background: s.color }"></div>
        <div class="cw-compact-info">
          <div class="cw-compact-name">{{ s.name }}</div>
          <div class="cw-compact-status" :style="{ color: s.color }">{{ s.status }}</div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { vaultRef } from 'llming'

const heroName     = vaultRef('code-watch', 'state.hero_name', 'claude_dev')
const heroActive   = vaultRef('code-watch', 'state.hero_active', true)
const heroDuration = vaultRef('code-watch', 'state.hero_duration', '23m')
const heroOutput   = vaultRef('code-watch', 'state.hero_output', '> Building project...\n  Compiling 42 modules\n  Tests: 18 passed')
const tokenUsed    = vaultRef('code-watch', 'state.token_used', 14200)
const tokenMax     = vaultRef('code-watch', 'state.token_max', 20000)
const sess1Name    = vaultRef('code-watch', 'state.sess1_name', 'claude_test')
const sess1Status  = vaultRef('code-watch', 'state.sess1_status', 'idle 4m')
const sess1Color   = vaultRef('code-watch', 'state.sess1_color', '#666')
const sess2Name    = vaultRef('code-watch', 'state.sess2_name', 'claude_fix')
const sess2Status  = vaultRef('code-watch', 'state.sess2_status', 'done 8m')
const sess2Color   = vaultRef('code-watch', 'state.sess2_color', 'var(--success)')

const tokenPct = computed(() => {
  if (!tokenMax.value) return 0
  return Math.min(100, (tokenUsed.value / tokenMax.value) * 100)
})

const tokenLabel = computed(() => {
  const k = tokenUsed.value / 1000
  return k >= 10 ? Math.round(k) + 'k' : k.toFixed(1) + 'k'
})

const compactSessions = computed(() => [
  { name: sess1Name.value, status: sess1Status.value, color: sess1Color.value },
  { name: sess2Name.value, status: sess2Status.value, color: sess2Color.value },
])
</script>

<style scoped>
.cw-card {
  width: 100%;
  height: 100%;
  padding: 8px;
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.cw-hero {
  flex: 2;
  background: rgba(167, 139, 250, 0.06);
  border: 1px solid rgba(167, 139, 250, 0.12);
  border-radius: 8px;
  padding: 8px;
  display: flex;
  flex-direction: column;
  gap: 4px;
  min-height: 0;
}

.cw-hero-header {
  display: flex;
  align-items: center;
  gap: 8px;
}

.cw-hero-info {
  display: flex;
  align-items: baseline;
  gap: 6px;
  flex: 1;
  min-width: 0;
}

.cw-hero-name {
  font-size: 14px;
  font-weight: 700;
  color: var(--purple);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.cw-hero-dur {
  font-size: 11px;
  color: rgba(255, 255, 255, 0.4);
  flex-shrink: 0;
}

.cw-ring {
  width: 18px;
  height: 18px;
  border-radius: 50%;
  border: 2px solid rgba(255, 255, 255, 0.1);
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}

.cw-ring.active {
  border-color: var(--purple);
}

.cw-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
}

.cw-output {
  font-size: 10px;
  font-family: 'SF Mono', 'Fira Code', monospace;
  color: rgba(255, 255, 255, 0.5);
  white-space: pre-wrap;
  line-height: 1.4;
  max-height: 42px;
  overflow: hidden;
}

.cw-token-bar {
  flex: 1;
  height: 4px;
  background: rgba(255, 255, 255, 0.06);
  border-radius: 2px;
  overflow: hidden;
}

.cw-token-fill {
  height: 100%;
  border-radius: 2px;
  transition: width 0.3s ease;
}

.cw-token-row {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-top: auto;
}

.cw-token-label {
  font-size: 10px;
  color: rgba(255, 255, 255, 0.35);
  flex-shrink: 0;
}

.cw-compact-row {
  flex: 1;
  display: flex;
  gap: 4px;
}

.cw-compact {
  flex: 1;
  background: rgba(255, 255, 255, 0.03);
  border: 1px solid rgba(255, 255, 255, 0.06);
  border-radius: 6px;
  padding: 6px 8px;
  display: flex;
  align-items: center;
  gap: 6px;
  min-width: 0;
}

.cw-compact-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  flex-shrink: 0;
}

.cw-compact-info {
  min-width: 0;
}

.cw-compact-name {
  font-size: 11px;
  font-weight: 600;
  color: rgba(255, 255, 255, 0.7);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.cw-compact-status {
  font-size: 10px;
  color: rgba(255, 255, 255, 0.3);
}
</style>
