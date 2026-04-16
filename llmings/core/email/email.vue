<template>
  <div class="email-card">
    <div v-if="unreadCount > 0" class="email-unread-badge">{{ unreadCount }}</div>
    <div
      v-for="mail in emails"
      :key="mail.id"
      class="email-row"
      :class="{ unread: mail.unread }"
    >
      <img
        v-if="mail.avatar"
        :src="mail.avatar"
        class="email-avatar"
      />
      <div
        v-else
        class="email-avatar email-avatar-icon"
        :style="{ backgroundColor: mail.bg || '#22c55e' }"
      >
        <i :class="mail.icon || 'ph ph-robot'"></i>
      </div>
      <div class="email-content">
        <div class="email-from">{{ mail.from }}</div>
        <div class="email-subject">{{ mail.subject }}</div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed } from 'vue'
import { vaultRef } from 'llming'

const emails = vaultRef('email', 'state.emails', [
  { id: 1, from: 'Alex Chen', subject: 'PR Review: Session refactor', unread: true, avatar: '/static/vendor/demo/face-alex.jpg' },
  { id: 2, from: 'Lisa Park', subject: 'Q2 roadmap draft attached', unread: true, avatar: '/static/vendor/demo/face-lisa.jpg' },
  { id: 3, from: 'Sarah Kim', subject: 'Q2 OKR draft for review', unread: false, avatar: '/static/vendor/demo/face-sarah.jpg' }
])
const unreadCount = vaultRef('email', 'state.unreadCount', 2)
</script>

<style scoped>
.email-card {
  width: 100%;
  height: 100%;
  padding: 8px;
  display: flex;
  flex-direction: column;
  gap: 4px;
  position: relative;
}

.email-unread-badge {
  position: absolute;
  top: 6px;
  right: 8px;
  background: #ef4444;
  color: #fff;
  font-size: 10px;
  font-weight: 700;
  min-width: 18px;
  height: 18px;
  border-radius: 9px;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 0 5px;
  z-index: 1;
}

.email-row {
  display: flex;
  gap: 10px;
  padding: 8px 6px;
  border-radius: 6px;
  border-left: 3px solid transparent;
  transition: border-color 0.2s;
}

.email-row.unread {
  border-left-color: #3b82f6;
}

.email-avatar {
  width: 32px;
  height: 32px;
  border-radius: 50%;
  flex-shrink: 0;
  object-fit: cover;
}

.email-avatar-icon {
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 14px;
  color: #fff;
}

.email-content {
  flex: 1;
  min-width: 0;
}

.email-from {
  font-size: 12px;
  color: #94a3b8;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.email-row.unread .email-from {
  font-weight: 700;
  color: #e2e8f0;
}

.email-subject {
  font-size: 11px;
  color: #64748b;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  margin-top: 1px;
}
</style>
