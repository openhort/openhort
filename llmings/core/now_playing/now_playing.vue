<template>
  <div class="now-playing">
    <div class="np-top">
      <div class="np-album-art">
        <i class="ph ph-music-notes np-art-icon"></i>
      </div>
      <div class="np-track-info">
        <div class="np-track-title">{{ track }}</div>
        <div class="np-track-artist">{{ artist }} — {{ album }}</div>
      </div>
    </div>

    <div class="np-controls">
      <button class="np-btn" @click="skipBack">
        <i class="ph ph-skip-back"></i>
      </button>
      <button class="np-btn np-play-btn" @click="togglePlay">
        <i :class="playing ? 'ph ph-pause' : 'ph ph-play'"></i>
      </button>
      <button class="np-btn" @click="skipForward">
        <i class="ph ph-skip-forward"></i>
      </button>
    </div>

    <div class="np-progress-area">
      <div class="music-progress">
        <div class="music-progress-fill" :style="{ width: progressPct + '%' }"></div>
      </div>
      <div class="np-time">-{{ remaining }}</div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed } from 'vue'
import { vaultRef } from 'llming'

const track    = vaultRef('now-playing', 'state.track', 'Midnight City')
const artist   = vaultRef('now-playing', 'state.artist', 'M83')
const album    = vaultRef('now-playing', 'state.album', "Hurry Up, We're Dreaming")
const playing  = vaultRef('now-playing', 'state.playing', true)
const position = vaultRef('now-playing', 'state.position', 158)
const duration = vaultRef('now-playing', 'state.duration', 243)

const progressPct = computed(() => {
  if (!duration.value || duration.value <= 0) return 0
  return Math.min(100, (position.value / duration.value) * 100)
})

const remaining = computed(() => {
  const rem = Math.max(0, duration.value - position.value)
  const m = Math.floor(rem / 60)
  const s = Math.floor(rem % 60)
  return `${m}:${s.toString().padStart(2, '0')}`
})

function togglePlay() {}
function skipBack() {}
function skipForward() {}
</script>

<style scoped>
.now-playing {
  width: 100%;
  height: 100%;
  position: relative;
  overflow: hidden;
  background: linear-gradient(145deg, #1a0a2e, #2d1b4e 40%, #1e1245 60%, #0f1a3e);
  padding: 12px;
  display: flex;
  flex-direction: column;
  justify-content: space-between;
}

.np-top {
  display: flex;
  align-items: center;
  gap: 10px;
}

.np-album-art {
  width: 56px;
  height: 56px;
  min-width: 56px;
  border-radius: 8px;
  background: linear-gradient(135deg, #6b21a8, #a855f7 50%, #7c3aed);
  display: flex;
  align-items: center;
  justify-content: center;
}

.np-art-icon {
  font-size: 24px;
  color: rgba(255, 255, 255, 0.7);
}

.np-track-info {
  min-width: 0;
  flex: 1;
}

.np-track-title {
  font-size: 15px;
  font-weight: 700;
  color: #fff;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.np-track-artist {
  font-size: 11px;
  color: rgba(255, 255, 255, 0.5);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  margin-top: 2px;
}

.np-controls {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 16px;
}

.np-btn {
  background: none;
  border: none;
  color: rgba(255, 255, 255, 0.7);
  font-size: 18px;
  cursor: pointer;
  padding: 4px;
  display: flex;
  align-items: center;
  justify-content: center;
}

.np-play-btn {
  width: 32px;
  height: 32px;
  border-radius: 50%;
  background: rgba(255, 255, 255, 0.15);
  color: #fff;
  font-size: 16px;
}

.np-progress-area {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.music-progress {
  width: 100%;
  height: 3px;
  background: rgba(255, 255, 255, 0.1);
  border-radius: 2px;
  overflow: hidden;
}

.music-progress-fill {
  height: 100%;
  background: linear-gradient(90deg, #a855f7, #c084fc);
  border-radius: 2px;
  transition: width 0.3s linear;
}

.np-time {
  font-size: 9px;
  color: rgba(255, 255, 255, 0.4);
  text-align: right;
}
</style>
