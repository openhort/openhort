<template>
  <div class="openclaw-root">
    <div
      v-for="room in rooms"
      :key="room.id"
      class="room-tile"
      :class="{ on: room.lightOn }"
      @click="room.lightOn = !room.lightOn"
    >
      <div class="room-header">
        <i :class="room.icon" class="room-icon" />
        <div class="room-toggle" :class="{ active: room.lightOn }">
          <div class="toggle-knob" />
        </div>
      </div>
      <div class="room-name">{{ room.name }}</div>
      <div class="room-temp">{{ room.temp }}&deg;C</div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed } from 'vue'
import { vaultRef } from 'llming'

const roomData = vaultRef('openclaw', 'state.rooms', [
  { id: 'living', name: 'Living Room', icon: 'ph-fill ph-lamp', lightOn: true, temp: 22 },
  { id: 'bedroom', name: 'Bedroom', icon: 'ph-fill ph-bed', lightOn: false, temp: 19 },
  { id: 'kitchen', name: 'Kitchen', icon: 'ph-fill ph-cooking-pot', lightOn: true, temp: 21 },
  { id: 'office', name: 'Office', icon: 'ph-fill ph-desk', lightOn: false, temp: 20 },
])

const rooms = computed(() => roomData.value || [])
</script>

<style scoped>
.openclaw-root {
  width: 100%;
  height: 100%;
  padding: 10px;
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  box-sizing: border-box;
}

.room-tile {
  flex: 1 1 calc(50% - 3px);
  min-width: 0;
  padding: 10px;
  border-radius: 10px;
  background: var(--bg, #1a1a2e);
  border: 1px solid var(--border, rgba(255,255,255,.08));
  display: flex;
  flex-direction: column;
  gap: 4px;
  cursor: pointer;
  transition: all .25s ease;
}

.room-tile.on {
  background: rgba(245, 158, 11, .12);
  border-color: rgba(245, 158, 11, .35);
  box-shadow: 0 0 12px rgba(245, 158, 11, .08);
}

.room-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.room-icon {
  font-size: 22px;
  color: rgba(255, 255, 255, .25);
  transition: color .25s ease;
}

.room-tile.on .room-icon {
  color: rgb(245, 158, 11);
}

.room-toggle {
  width: 30px;
  height: 16px;
  border-radius: 8px;
  background: rgba(255, 255, 255, .1);
  position: relative;
  transition: background .25s ease;
}

.room-toggle.active {
  background: rgba(245, 158, 11, .5);
}

.toggle-knob {
  width: 12px;
  height: 12px;
  border-radius: 50%;
  background: rgba(255, 255, 255, .4);
  position: absolute;
  top: 2px;
  left: 2px;
  transition: all .25s ease;
}

.room-toggle.active .toggle-knob {
  left: 16px;
  background: rgb(245, 158, 11);
}

.room-name {
  font-size: 12px;
  font-weight: 600;
  color: rgba(255, 255, 255, .7);
}

.room-temp {
  font-size: 10px;
  color: rgba(255, 255, 255, .35);
}
</style>
