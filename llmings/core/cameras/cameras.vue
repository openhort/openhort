<template>
  <div class="cameras-root">
    <div v-for="cam in camList" :key="cam.id" class="cam-feed">
      <img v-if="cam.frame" :src="cam.frame" class="cam-canvas" />
      <div v-else class="cam-placeholder">
        <i class="ph ph-security-camera" style="font-size:20px;opacity:.3"></i>
      </div>
      <div class="cam-gradient" />
      <div v-if="cam.frame" class="cam-rec">
        <span class="rec-dot" />
        <span class="rec-label">REC</span>
      </div>
      <div v-if="cam.motion" class="cam-motion">MOTION</div>
      <div class="cam-name">{{ cam.name }}</div>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { vaultRef } from 'llming'

// Camera metadata (list + motion state) from vault
const cameras = vaultRef('cameras', 'state.cameras', [])

// Each camera gets its own stream via useStream
const streams = {}
const knownIds = ['frontdoor', 'backyard', 'garage']
for (const id of knownIds) {
  streams[id] = useStream('cameras:' + id, { displayWidth: 160, displayHeight: 90 })
}

const camList = computed(() => {
  const cams = cameras.value || []
  return cams.map(c => ({
    id: c.id,
    name: c.name || c.id,
    motion: c.motion || false,
    frame: streams[c.id]?.frame?.value || null,
  }))
})
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

.cam-canvas {
  width: 100%;
  height: 100%;
  object-fit: cover;
  filter: saturate(.4) brightness(.7) contrast(1.1);
}

.cam-placeholder {
  width: 100%;
  height: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--dim);
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
