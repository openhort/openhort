/**
 * Holepunch extension panel — P2P status + Azure VM management.
 */
class HolepunchPanel extends LlmingClient {
  static get pluginId() { return 'peer2peer'; }

  renderThumbnail(canvas, data) {
    const ctx = canvas.getContext('2d');
    const w = canvas.width, h = canvas.height;
    ctx.clearRect(0, 0, w, h);

    ctx.fillStyle = '#1a1a2e';
    ctx.fillRect(0, 0, w, h);

    const stun = data?.stun;
    const vm = data?.vm;
    const punch = data?.punch;

    // Title
    ctx.fillStyle = '#e0e0e0';
    ctx.font = 'bold 14px monospace';
    ctx.fillText('Hole Punch', 10, 24);

    // STUN info
    ctx.font = '11px monospace';
    ctx.fillStyle = '#90caf9';
    const natType = stun?.nat_type || 'unknown';
    const punchable = stun?.nat_type && stun.nat_type !== 'symmetric' && stun.nat_type !== 'unknown';
    ctx.fillText(`NAT: ${natType}`, 10, 46);
    ctx.fillStyle = punchable ? '#66bb6a' : '#ef5350';
    ctx.fillText(punchable ? 'punchable' : 'not tested', 10, 62);

    // VM status
    ctx.fillStyle = '#ce93d8';
    const vmState = vm?.exists ? vm.power_state : 'none';
    ctx.fillText(`VM: ${vmState}`, 10, 84);
    if (vm?.public_ip) {
      ctx.fillStyle = '#80cbc4';
      ctx.font = '10px monospace';
      ctx.fillText(vm.public_ip, 10, 98);
    }

    // Punch result
    if (punch?.success !== null && punch?.success !== undefined) {
      ctx.fillStyle = punch.success ? '#66bb6a' : '#ef5350';
      ctx.font = '11px monospace';
      const label = punch.success ? `punched ${punch.rtt_ms?.toFixed(0)}ms` : 'punch failed';
      ctx.fillText(label, 10, 118);
    }
  }

  renderPanel(container, data) {
    const stun = data?.stun || {};
    const vm = data?.vm || {};
    const punch = data?.punch || {};

    container.innerHTML = `
      <div class="connector-panel" style="padding: 16px;">
        <h6 class="text-subtitle1 q-mb-sm">STUN Discovery</h6>
        <div class="q-mb-md" style="font-family: monospace; font-size: 13px;">
          <div>Public: ${stun.public_ip || '—'}:${stun.public_port || '—'}</div>
          <div>NAT type: <b>${stun.nat_type || 'not tested'}</b></div>
        </div>
        <button class="q-btn q-btn--flat" onclick="this.dispatchEvent(new CustomEvent('hort-action', {bubbles:true, detail:{action:'stun'}}))">
          Run STUN Discovery
        </button>

        <q-separator class="q-my-md"></q-separator>

        <h6 class="text-subtitle1 q-mb-sm">Azure Test VM</h6>
        <div class="q-mb-md" style="font-family: monospace; font-size: 13px;">
          <div>State: <b>${vm.exists ? vm.power_state : 'none'}</b></div>
          ${vm.public_ip ? `<div>IP: ${vm.public_ip}</div>` : ''}
        </div>
        <div class="q-gutter-sm">
          ${!vm.exists ? '<button class="q-btn q-btn--flat" onclick="this.dispatchEvent(new CustomEvent(\'hort-action\', {bubbles:true, detail:{action:\'vm-create\'}}))">Create VM</button>' : ''}
          ${vm.exists && vm.power_state === 'deallocated' ? '<button class="q-btn q-btn--flat" onclick="this.dispatchEvent(new CustomEvent(\'hort-action\', {bubbles:true, detail:{action:\'vm-start\'}}))">Start</button>' : ''}
          ${vm.exists && vm.power_state === 'running' ? '<button class="q-btn q-btn--flat" onclick="this.dispatchEvent(new CustomEvent(\'hort-action\', {bubbles:true, detail:{action:\'vm-stop\'}}))">Stop</button>' : ''}
          ${vm.exists ? '<button class="q-btn q-btn--flat text-negative" onclick="this.dispatchEvent(new CustomEvent(\'hort-action\', {bubbles:true, detail:{action:\'vm-destroy\'}}))">Destroy</button>' : ''}
        </div>

        ${punch.success !== null && punch.success !== undefined ? `
          <q-separator class="q-my-md"></q-separator>
          <h6 class="text-subtitle1 q-mb-sm">Punch Result</h6>
          <div style="font-family: monospace; font-size: 13px;">
            <div>Status: <b style="color: ${punch.success ? '#66bb6a' : '#ef5350'}">${punch.success ? 'SUCCESS' : 'FAILED'}</b></div>
            ${punch.remote_addr ? `<div>Remote: ${punch.remote_addr}</div>` : ''}
            ${punch.rtt_ms ? `<div>RTT: ${punch.rtt_ms.toFixed(1)}ms</div>` : ''}
          </div>
        ` : ''}
      </div>
    `;
  }
}

if (window.LlmingClientRegistry) {
  window.LlmingClientRegistry.register(HolepunchPanel);
}
