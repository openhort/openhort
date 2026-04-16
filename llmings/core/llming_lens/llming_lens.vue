<template>
  <div class="lens-card">
    <div class="lens-mini">
      <!-- IDE window -->
      <div class="lens-win lens-ide">
        <div class="lens-ide-sidebar">
          <span style="background:#e06c75"></span>
          <span style="background:#98c379"></span>
          <span style="background:#61afef"></span>
          <span style="background:#c678dd"></span>
          <span style="background:#56b6c2"></span>
        </div>
        <div class="lens-ide-code">
          <span style="width:55%;background:#c678dd"></span>
          <span style="width:80%;background:#61afef"></span>
          <span style="width:40%;background:#98c379"></span>
          <span style="width:70%;background:#e5c07b"></span>
          <span style="width:50%;background:#e06c75"></span>
          <span style="width:65%;background:#61afef"></span>
          <span style="width:35%;background:#98c379"></span>
          <span style="width:75%;background:#c678dd"></span>
          <span style="width:45%;background:#56b6c2"></span>
          <span style="width:60%;background:#e06c75"></span>
        </div>
      </div>

      <!-- Browser window -->
      <div class="lens-win lens-browser">
        <div class="lens-browser-tab">
          <span></span>
          <span></span>
        </div>
        <div class="lens-browser-bar"></div>
        <div class="lens-browser-content">
          <span style="width:90%"></span>
          <span style="width:60%"></span>
          <span style="width:75%"></span>
          <div class="img-placeholder"></div>
          <span style="width:85%"></span>
          <span style="width:45%"></span>
          <span style="width:70%"></span>
          <span style="width:55%"></span>
        </div>
      </div>

      <!-- Terminal window -->
      <div class="lens-win lens-term">
        <div class="lens-term-lines">
          <span style="width:70%;background:rgba(74,222,128,.4)"></span>
          <span style="width:50%;background:rgba(74,222,128,.25)"></span>
          <span style="width:85%;background:rgba(74,222,128,.3)"></span>
          <span style="width:40%;background:rgba(74,222,128,.2)"></span>
          <span style="width:65%;background:rgba(74,222,128,.35)"></span>
          <span style="width:55%;background:rgba(74,222,128,.25)"></span>
          <span style="width:75%;background:rgba(74,222,128,.15)"></span>
          <span style="width:60%;background:rgba(74,222,128,.3)"></span>
          <span style="width:80%;background:rgba(74,222,128,.2)"></span>
          <span style="width:45%;background:rgba(74,222,128,.35)"></span>
        </div>
      </div>
    </div>

    <div class="lens-live-badge">LIVE</div>
  </div>
</template>

<script setup>
</script>

<style scoped>
.lens-card {
  width: 100%;
  height: 100%;
  position: relative;
  background: linear-gradient(135deg, #1a1a2e, #16213e, #0f3460);
  overflow: hidden;
}

.lens-mini {
  width: 100%;
  height: 100%;
  display: grid;
  grid-template-columns: 1fr 1fr 1fr;
  gap: 2%;
  padding: 6%;
  align-items: center;
  justify-items: center;
}

.lens-win {
  width: 100%;
  max-width: 100%;
  aspect-ratio: 16 / 10;
  border-radius: 4px;
  overflow: hidden;
  position: relative;
  border: 1px solid rgba(255, 255, 255, 0.1);
}

/* IDE */
.lens-ide {
  display: flex;
  background: #1e1e2e;
}

.lens-ide-sidebar {
  width: 20%;
  display: flex;
  flex-direction: column;
  gap: 3px;
  padding: 3px 2px;
  background: rgba(0, 0, 0, 0.3);
}

.lens-ide-sidebar span {
  height: 2px;
  border-radius: 1px;
  opacity: 0.6;
}

.lens-ide-code {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding: 3px 4px;
}

.lens-ide-code span {
  height: 2px;
  border-radius: 1px;
  opacity: 0.5;
}

/* Browser */
.lens-browser {
  background: #1a1a2e;
  display: flex;
  flex-direction: column;
}

.lens-browser-tab {
  display: flex;
  gap: 2px;
  padding: 2px 3px;
  background: rgba(255, 255, 255, 0.05);
}

.lens-browser-tab span {
  width: 12px;
  height: 3px;
  border-radius: 1px;
  background: rgba(255, 255, 255, 0.15);
}

.lens-browser-bar {
  height: 3px;
  margin: 1px 3px;
  background: rgba(255, 255, 255, 0.08);
  border-radius: 1px;
}

.lens-browser-content {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding: 3px 4px;
}

.lens-browser-content span {
  height: 2px;
  border-radius: 1px;
  background: rgba(255, 255, 255, 0.12);
}

.lens-browser-content .img-placeholder {
  width: 80%;
  height: 8px;
  border-radius: 2px;
  background: rgba(96, 165, 250, 0.12);
  margin: 1px 0;
}

/* Terminal */
.lens-term {
  background: #0d1117;
  display: flex;
  flex-direction: column;
}

.lens-term-lines {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding: 3px 4px;
}

.lens-term-lines span {
  height: 2px;
  border-radius: 1px;
}

.lens-live-badge {
  position: absolute;
  bottom: 8px;
  right: 8px;
  background: rgba(34, 197, 94, 0.2);
  color: var(--success);
  font-size: 9px;
  font-weight: 700;
  letter-spacing: 1px;
  padding: 2px 6px;
  border-radius: 3px;
  border: 1px solid rgba(34, 197, 94, 0.3);
}
</style>
