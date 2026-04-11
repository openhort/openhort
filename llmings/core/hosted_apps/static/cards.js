/* Hosted Apps — Docker container manager */
/* global LlmingClient */

(function () {
  'use strict';

  class HostedAppsPanel extends LlmingClient {
    static id = 'hosted-apps';
    static name = 'Hosted Apps';

    renderThumbnail(canvas, data) {
      const ctx = canvas.getContext('2d');
      const w = canvas.width, h = canvas.height;
      ctx.clearRect(0, 0, w, h);
      ctx.fillStyle = '#0a0e1a';
      ctx.fillRect(0, 0, w, h);

      ctx.fillStyle = '#f0f4ff';
      ctx.font = 'bold 14px monospace';
      ctx.fillText('Hosted Apps', 10, 24);

      const instances = data?.instances || [];
      const running = instances.filter(i => i.status === 'running').length;

      ctx.fillStyle = '#94a3b8';
      ctx.font = '12px monospace';
      ctx.fillText(running + '/' + instances.length + ' running', 10, 44);

      instances.slice(0, 4).forEach(function (inst, i) {
        ctx.fillStyle = inst.status === 'running' ? '#22c55e' : '#666';
        ctx.beginPath();
        ctx.arc(18, 64 + i * 20, 4, 0, Math.PI * 2);
        ctx.fill();
        ctx.fillStyle = '#f0f4ff';
        ctx.font = '11px monospace';
        ctx.fillText(inst.label || inst.name, 28, 68 + i * 20);
      });
    }

    renderPanel(container, data) {
      var instances = data?.instances || [];
      var bp = LlmingClient.basePath;

      container.innerHTML =
        '<div class="connector-panel" style="padding:16px">' +
        '<h6 class="text-subtitle1 q-mb-sm">Hosted Apps</h6>' +
        (instances.length === 0
          ? '<div style="color:var(--el-text-dim);font-size:13px;margin:12px 0">No instances running.</div>'
          : instances.map(function (inst) {
              return '<div style="display:flex;align-items:center;gap:10px;padding:8px 0;border-bottom:1px solid var(--el-border)">' +
                '<span style="width:8px;height:8px;border-radius:50%;background:' + (inst.status === 'running' ? '#22c55e' : '#666') + '"></span>' +
                '<div style="flex:1">' +
                '<div style="font-size:13px;color:var(--el-text)">' + (inst.label || inst.name) + '</div>' +
                '<div style="font-size:11px;color:var(--el-text-dim)">' + inst.type + ' — ' + inst.status + '</div>' +
                '</div>' +
                (inst.status === 'running'
                  ? '<a href="' + bp + '/app/' + inst.name + '/" target="_blank" style="color:var(--el-primary);font-size:12px;text-decoration:none">Open</a>'
                  : '') +
                '</div>';
            }).join('')) +
        '</div>';
    }
  }

  LlmingClient.register(HostedAppsPanel);
})();
