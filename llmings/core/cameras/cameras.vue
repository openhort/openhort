<template>
  <div class="cameras-root">
    <div v-for="cam in cams" :key="cam.key" class="cam-feed">
      <video
        :src="`/static/vendor/demo/cam-${cam.key}.mp4`"
        autoplay loop muted playsinline
        class="cam-video"
      />
      <div class="cam-gradient" />
      <div class="cam-rec">
        <span class="rec-dot" />
        <span class="rec-label">REC</span>
      </div>
      <div
        v-if="isMotion(cam.key)"
        class="cam-motion"
      >MOTION</div>
      <div class="cam-name">{{ cam.short }}</div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed } from 'vue'
import { vaultRef } from 'llming'

const cams = [
  { name: 'Front Door', key: 'frontdoor', short: 'Front' },
  { name: 'Backyard', key: 'backyard', short: 'Back' },
  { name: 'Garage', key: 'garage', short: 'Garage' },
]

const camState = vaultRef('cameras', 'state.cameras', [])

function isMotion(key) {
  const cameras = camState.value || []
  const cam = cameras.find(c => c.id === key)
  return cam ? cam.motion : false
}
</script>

<style scoped>
.cameras-root {
  width: 100%;
  height: 100%;
  display: flex;
  gap: 4px;
}

.cam-feed {
  flex: 1;
  position: relative;
  overflow: hidden;
  border-radius: 6px;
  background: #0a0a0a;
}

.cam-video {
  width: 100%;
  height: 100%;
  object-fit: cover;
  filter: saturate(.4) brightness(.7) contrast(1.1);
}

.cam-gradient {
  position: absolute;
  inset: 0;
  background: linear-gradient(to bottom, transparent 60%, rgba(0, 0, 0, .5));
  pointer-events: none;
}

.cam-rec {
  position: absolute;
  top: 6px;
  left: 6px;
  display: flex;
  align-items: center;
  gap: 3px;
}

.rec-dot {
  width: 5px;
  height: 5px;
  border-radius: 50%;
  background: rgba(255, 50, 50, .7);
  animation: pulse-dot 2s ease-in-out infinite;
}

.rec-label {
  font-size: 7px;
  font-weight: 700;
  color: rgba(0, 255, 100, .4);
  letter-spacing: 0.5px;
}

.cam-motion {
  position: absolute;
  top: 6px;
  right: 6px;
  font-size: 7px;
  font-weight: 700;
  color: #fff;
  background: rgba(239, 68, 68, .7);
  padding: 1px 5px;
  border-radius: 3px;
  letter-spacing: 0.5px;
  animation: pulse-motion 1s ease-in-out infinite;
}

.cam-name {
  position: absolute;
  bottom: 6px;
  left: 6px;
  font-size: 9px;
  font-weight: 600;
  color: rgba(0, 255, 100, .4);
  letter-spacing: 0.5px;
}

@keyframes pulse-dot {
  0%, 100% { opacity: 1; }
  50% { opacity: .3; }
}

@keyframes pulse-motion {
  0%, 100% { opacity: 1; }
  50% { opacity: .5; }
}
</style>
