<template>
  <div class="cal-card">
    <div
      v-for="(evt, idx) in events"
      :key="evt.id"
      class="cal-event"
    >
      <div class="cal-bar" :style="{ backgroundColor: evt.color }"></div>
      <div class="cal-content">
        <div class="cal-title-row">
          <span class="cal-title">{{ evt.title }}</span>
          <i v-if="evt.hasVideo" class="ph ph-video-camera cal-video-icon"></i>
          <span v-if="idx === 0" class="cal-pill">in {{ minutesToNext }}m</span>
        </div>
        <div class="cal-meta">
          {{ evt.time }} &middot; {{ evt.location }}
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed } from 'vue'
import { vaultRef } from 'llming'

const events = vaultRef('calendar', 'state.events', [])
const minutesToNext = vaultRef('calendar', 'state.minutesToNext', 0)
</script>

<style scoped>
.cal-card {
  width: 100%;
  height: 100%;
  padding: 12px;
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.cal-event {
  display: flex;
  gap: 10px;
  padding: 8px 0;
  border-bottom: 1px solid rgba(255, 255, 255, 0.06);
}
.cal-event:last-child {
  border-bottom: none;
}
.cal-bar {
  width: 4px;
  border-radius: 2px;
  flex-shrink: 0;
  align-self: stretch;
}
.cal-content {
  flex: 1;
  min-width: 0;
}
.cal-title-row {
  display: flex;
  align-items: center;
  gap: 6px;
}
.cal-title {
  font-size: 14px;
  font-weight: 600;
  color: #e2e8f0;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.cal-video-icon {
  font-size: 13px;
  color: #64748b;
  flex-shrink: 0;
}
.cal-pill {
  font-size: 10px;
  font-weight: 600;
  color: #3b82f6;
  background: rgba(59, 130, 246, 0.15);
  padding: 2px 8px;
  border-radius: 10px;
  white-space: nowrap;
  flex-shrink: 0;
  margin-left: auto;
}
.cal-meta {
  font-size: 12px;
  color: #64748b;
  margin-top: 2px;
}
</style>
