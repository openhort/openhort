<template>
  <!-- Detail mode: single camera at full resolution (subapp) -->
  <div v-if="camId" class="cameras-detail">
    <img v-if="detailFrame" :src="detailFrame" class="cam-canvas-detail" />
    <div v-else class="cam-placeholder">
      <i class="ph ph-security-camera" style="font-size:48px;opacity:.3"></i>
    </div>
    <div class="cam-detail-bar">
      <span class="rec-dot" /> <span class="rec-label">LIVE</span>
      <span style="margin-left:8px;font-size:13px;color:var(--text)">{{ camName || camId }}</span>
    </div>
  </div>

  <!-- Default: all cameras. Layout decided by container aspect ratio. -->
  <div v-else ref="rootEl" class="cameras-root" :class="{ 'is-grid': useGrid }" :style="gridStyle">
    <div v-for="cam in camList" :key="cam.id" class="cam-feed" @click.stop="openDetail(cam.id, cam.name)">
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
import { computed, defineProps, ref, onMounted, onUnmounted } from 'vue'
import { vaultRef } from 'llming'

// Subapp props: when set, render single-camera detail at full resolution
const props = defineProps({
  camId: { type: String, default: '' },
  camName: { type: String, default: '' },
})

// Track container size — used to pick the optimal cols × rows arrangement
const rootEl = ref(null)
const cw = ref(0)
const ch = ref(0)
let _ro = null
onMounted(() => {
  if (!rootEl.value) return
  _ro = new ResizeObserver(entries => {
    for (const e of entries) {
      cw.value = e.contentRect.width
      ch.value = e.contentRect.height
    }
  })
  _ro.observe(rootEl.value)
})
onUnmounted(() => { if (_ro) _ro.disconnect() })

// Always use the smart grid — even on first paint before ResizeObserver fires
// it gives a sensible 1×N fallback at 16:9 (better than a flex row that
// stretches placeholders to weird aspect ratios).
const useGrid = computed(() => true)

// Pick the cols × rows that maximizes each cam's area at 16:9, then size
// cells exactly at that aspect so we never get black bars on the sides
// (and so empty placeholders also render at 16:9 immediately).
const gridStyle = computed(() => {
  // Defaults assumed 16:9 even before the ResizeObserver fires or cams arrive,
  // so nothing flashes at the wrong aspect.
  const target = 16 / 9
  const w = cw.value || 0
  const h = ch.value || 0
  const n = Math.max(1, (camList.value || []).length || (knownIds?.length ?? 1))
  if (!useGrid.value || !w || !h) {
    return { gridTemplateColumns: `repeat(${n}, minmax(0, 1fr))`, gridAutoRows: 'minmax(0, 1fr)' }
  }
  const gap = 8, pad = 16
  const innerW = Math.max(0, w - pad)
  const innerH = Math.max(0, h - pad)
  let best = { cols: 1, cellW: 0, cellH: 0 }
  for (let c = 1; c <= n; c++) {
    const r = Math.ceil(n / c)
    const availW = (innerW - gap * (c - 1)) / c
    const availH = (innerH - gap * (r - 1)) / r
    if (availW <= 0 || availH <= 0) continue
    const cellW = Math.min(availW, availH * target)
    const cellH = cellW / target
    if (cellW * cellH > best.cellW * best.cellH) best = { cols: c, cellW, cellH }
  }
  const rows = Math.ceil(n / best.cols)
  return {
    gridTemplateColumns: `repeat(${best.cols}, ${best.cellW}px)`,
    gridTemplateRows: `repeat(${rows}, ${best.cellH}px)`,
    justifyContent: 'center',
    alignContent: 'center',
  }
})

const cameras = vaultRef('cameras', 'state.cameras', [])
const streams = {}
const knownIds = ['frontdoor', 'backyard', 'garage']
const isDetail = !!props.camId

// Detail mode: ONE high-res subscription at setup time (useStream registers
// onUnmounted, so it must run during setup, not inside a computed).
const detailStream = isDetail
  ? useStream('cameras:' + props.camId, { displayWidth: 1280, displayHeight: 720 })
  : null

// Multi-cam grid: thumbnail subscriptions (skipped in detail mode to avoid
// burning bandwidth on streams the user doesn't see).
if (!isDetail) {
  for (const id of knownIds) {
    streams[id] = useStream('cameras:' + id, { displayWidth: 160, displayHeight: 90 })
  }
}

const detailFrame = computed(() => detailStream?.frame?.value || null)

const camList = computed(() => {
  const cams = cameras.value || []
  return cams.map(c => ({
    id: c.id,
    name: c.name || c.id,
    motion: c.motion || false,
    frame: streams[c.id]?.frame?.value || null,
  }))
})

function openDetail(camId, camName) {
  if (typeof LlmingClient === 'undefined' || !LlmingClient.openSubapp) return
  // Same component (cameras-card) opened with camId prop = detail mode
  LlmingClient.openSubapp('cameras', 'cameras-card', { camId, camName }, {
    title: camName,
    width_pct: 60,
    height_pct: 75,
    min_width: 480,
    min_height: 360,
  })
}
</script>

<style scoped>
.cameras-root {
  width: 100%;
  height: 100%;
  display: flex;
  gap: 4px;
  /* Default: horizontal row (card thumbnail) */
  flex-direction: row;
  align-items: stretch;
}

.cam-feed {
  flex: 1;
  position: relative;
  overflow: hidden;
  border-radius: 6px;
  background: #0a0a0a;
  min-height: 0;
  cursor: pointer;
  transition: transform 0.15s;
}
.cam-feed:hover { transform: scale(1.01); }

/* Detail view (subapp) */
.cameras-detail {
  width: 100%;
  height: 100%;
  display: flex;
  flex-direction: column;
  background: #000;
  position: relative;
}
.cam-canvas-detail {
  flex: 1;
  width: 100%;
  height: 100%;
  object-fit: contain;
  background: #000;
  filter: saturate(.8) brightness(.95);
}
.cam-detail-bar {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 8px 12px;
  background: rgba(0,0,0,.6);
  border-top: 1px solid rgba(255,255,255,.05);
}

.cam-canvas {
  width: 100%;
  height: 100%;
  object-fit: cover;
  image-rendering: auto;
  filter: saturate(.6) brightness(.85) contrast(1.05);
}

/* Float window / subapp: grid layout — cols × rows picked to maximize cam area.
   Each cell shares the available space, object-fit:contain preserves aspect. */
.cameras-root.is-grid {
  display: grid;
  gap: 8px;
  padding: 8px;
  overflow: hidden;
}
.cameras-root.is-grid .cam-feed {
  flex: none;
  width: 100%;
  height: 100%;
  min-height: 0;
}
.cameras-root.is-grid .cam-canvas {
  object-fit: contain;
  background: #000;
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
