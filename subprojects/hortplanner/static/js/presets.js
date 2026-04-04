// ═══════════════════════════════════════════════════════════════
//  HortPlanner — Infrastructure Presets (security-aware)
//
//  Machine horts: x,z = top-left grid cell (must have 1-cell gap)
//    Mac Mini/Cloud VM: 6×6, next hort at x+9 minimum
//    MacBook: 7×5, RPi: 5×5
//  Children: parent index only (auto-placed in parent's internal grid)
//  Connections: [fromIdx, 0, toIdx, 0, securityLevel]
//    securityLevel: 'read' | 'write' | 'send' | 'destroy' | 'none'
//  All components have 1 in + 1 out port (index 0).
// ═══════════════════════════════════════════════════════════════

export const PRESETS = [

// ─── 1. Personal Workstation ───────────────────────────────
{
  name: 'Personal Workstation',
  desc: 'Single machine, one agent, basic tool access',
  components: [
    { type: 'mac-mini', name: 'My Mac', x: 0, z: 0 },
    { type: 'agent', name: 'Claude', parent: 0 },
    { type: 'llming', name: 'Filesystem', parent: 0 },
    { type: 'mcp-server', name: 'Git MCP', parent: 0 },
    { type: 'program', name: 'Shell', parent: 0 },
  ],
  connections: [
    [1, 0, 2, 0, 'write'],
    [1, 0, 3, 0, 'read'],
    [1, 0, 4, 0, 'write'],
  ],
},

// ─── 2. Read-Only Dashboard ────────────────────────────────
{
  name: 'Read-Only Dashboard',
  desc: 'Agent monitors multiple sources without write access',
  components: [
    { type: 'mac-mini', name: 'Dashboard Server', x: 0, z: 0 },
    { type: 'agent', name: 'Monitor Agent', parent: 0 },
    { type: 'mcp-server', name: 'Metrics MCP', parent: 0 },
    { type: 'mcp-server', name: 'Logs MCP', parent: 0 },
    { type: 'llming', name: 'Alerting', parent: 0 },
    { type: 'cloud-vm', name: 'Production DB', x: 9, z: 0 },
    { type: 'mcp-server', name: 'PostgreSQL MCP', parent: 5 },
  ],
  connections: [
    [1, 0, 2, 0, 'read'],
    [1, 0, 3, 0, 'read'],
    [1, 0, 4, 0, 'read'],
    [0, 0, 5, 0, 'read'],
  ],
},

// ─── 3. Developer Sandbox ──────────────────────────────────
{
  name: 'Developer Sandbox',
  desc: 'Workstation with sandboxed cloud compute for untrusted code',
  components: [
    { type: 'macbook', name: 'Dev Laptop', x: 0, z: 0 },
    { type: 'agent', name: 'Claude Code', parent: 0 },
    { type: 'llming', name: 'Local FS', parent: 0 },
    { type: 'mcp-server', name: 'Git MCP', parent: 0 },
    { type: 'cloud-vm', name: 'Sandbox VM', x: 9, z: 0 },
    { type: 'docker', name: 'Build Container', parent: 4 },
    { type: 'program', name: 'Test Runner', parent: 4 },
    { type: 'fence', name: 'Untrusted Code', parent: 4 },
  ],
  connections: [
    [1, 0, 2, 0, 'write'],
    [1, 0, 3, 0, 'write'],
    [0, 0, 4, 0, 'send'],
  ],
},

// ─── 4. Enterprise SAP Integration ─────────────────────────
{
  name: 'Enterprise SAP Integration',
  desc: 'Sandboxed SAP with PII fence, read-only cross-hort access',
  components: [
    { type: 'mac-mini', name: 'Workstation', x: 0, z: 0 },
    { type: 'agent', name: 'Enterprise Agent', parent: 0 },
    { type: 'llming', name: 'Office 365', parent: 0 },
    { type: 'llming', name: 'GitHub', parent: 0 },
    { type: 'fence', name: 'Internal Fence', parent: 0 },
    { type: 'cloud-vm', name: 'SAP Hort', x: 9, z: 0 },
    { type: 'mcp-server', name: 'SAP MCP', parent: 5 },
    { type: 'llming', name: 'SAP Analytics', parent: 5 },
    { type: 'fence', name: 'PII Fence', parent: 5 },
    { type: 'cloud-vm', name: 'Public API', x: 18, z: 0 },
    { type: 'mcp-server', name: 'REST Gateway', parent: 9 },
    { type: 'program', name: 'Webhook Handler', parent: 9 },
  ],
  connections: [
    [1, 0, 2, 0, 'read'],
    [1, 0, 3, 0, 'write'],
    [0, 0, 5, 0, 'read'],
    [0, 0, 9, 0, 'send'],
    [2, 0, 3, 0, 'read'],
  ],
},

// ─── 5. Smart Home Hub ─────────────────────────────────────
{
  name: 'Smart Home Hub',
  desc: 'Trusted hub orchestrates untrusted IoT devices and cloud alerts',
  components: [
    { type: 'rpi', name: 'Home Hub', x: 8, z: 0 },
    { type: 'agent', name: 'Home Agent', parent: 0 },
    { type: 'docker', name: 'Home Assistant', parent: 0 },
    { type: 'rpi', name: 'Kitchen Sensors', x: 0, z: 0 },
    { type: 'mcp-server', name: 'Temp & Humidity', parent: 3 },
    { type: 'rpi', name: 'Door Locks', x: 0, z: 8 },
    { type: 'mcp-server', name: 'Lock Control', parent: 5 },
    { type: 'cloud-vm', name: 'Telegram Bridge', x: 14, z: 0 },
    { type: 'llming', name: 'Alert Bot', parent: 7 },
  ],
  connections: [
    [1, 0, 2, 0, 'write'],
    [3, 0, 0, 0, 'read'],
    [5, 0, 0, 0, 'read'],
    [0, 0, 7, 0, 'send'],
  ],
},

// ─── 6. Home Lab Cluster ───────────────────────────────────
{
  name: 'Home Lab Cluster',
  desc: 'NAS, compute node, DNS — with trust boundaries between machines',
  components: [
    { type: 'mac-mini', name: 'NAS Server', x: 0, z: 0 },
    { type: 'docker', name: 'MinIO S3', parent: 0 },
    { type: 'mcp-server', name: 'Storage MCP', parent: 0 },
    { type: 'mac-mini', name: 'Compute Node', x: 9, z: 0 },
    { type: 'agent', name: 'Lab Agent', parent: 3 },
    { type: 'docker', name: 'Jupyter Lab', parent: 3 },
    { type: 'llming', name: 'AI Assistant', parent: 3 },
    { type: 'rpi', name: 'Pi-hole DNS', x: 3, z: 9 },
    { type: 'program', name: 'DNS Filter', parent: 7 },
    { type: 'cloud-vm', name: 'Cloud Backup', x: 16, z: 0 },
    { type: 'docker', name: 'Restic', parent: 9 },
  ],
  connections: [
    [4, 0, 5, 0, 'write'],
    [4, 0, 6, 0, 'write'],
    [3, 0, 0, 0, 'read'],
    [0, 0, 9, 0, 'send'],
    [7, 0, 0, 0, 'read'],
    [7, 0, 3, 0, 'read'],
  ],
},

// ─── 7. CI/CD Pipeline ─────────────────────────────────────
{
  name: 'CI/CD Pipeline',
  desc: 'Progressive trust: build (write) → test (read) → deploy (send)',
  components: [
    { type: 'cloud-vm', name: 'Build Server', x: 0, z: 0 },
    { type: 'agent', name: 'CI Agent', parent: 0 },
    { type: 'docker', name: 'Build Container', parent: 0 },
    { type: 'program', name: 'Compiler', parent: 0 },
    { type: 'cloud-vm', name: 'Test Server', x: 9, z: 0 },
    { type: 'docker', name: 'Test Runner', parent: 4 },
    { type: 'mcp-server', name: 'Test DB', parent: 4 },
    { type: 'cloud-vm', name: 'Production', x: 18, z: 0 },
    { type: 'docker', name: 'App Container', parent: 7 },
    { type: 'mcp-server', name: 'Health Check', parent: 7 },
    { type: 'fence', name: 'Prod Fence', parent: 7 },
  ],
  connections: [
    [1, 0, 2, 0, 'write'],
    [1, 0, 3, 0, 'write'],
    [0, 0, 4, 0, 'write'],
    [4, 0, 7, 0, 'send'],
  ],
},

// ─── 8. Multi-Agent System ─────────────────────────────────
{
  name: 'Multi-Agent System',
  desc: 'Three horts with agents, coordinated via read-only cross-hort wires',
  components: [
    { type: 'mac-mini', name: 'Orchestrator', x: 5, z: 0 },
    { type: 'agent', name: 'Coord Agent', parent: 0 },
    { type: 'mcp-server', name: 'Task Queue', parent: 0 },
    { type: 'cloud-vm', name: 'Research Hort', x: 0, z: 9 },
    { type: 'agent', name: 'Research Agent', parent: 3 },
    { type: 'llming', name: 'Web Search', parent: 3 },
    { type: 'llming', name: 'Doc Reader', parent: 3 },
    { type: 'cloud-vm', name: 'Code Hort', x: 12, z: 9 },
    { type: 'agent', name: 'Code Agent', parent: 7 },
    { type: 'llming', name: 'Filesystem', parent: 7 },
    { type: 'program', name: 'Shell', parent: 7 },
    { type: 'fence', name: 'Sandbox', parent: 7 },
  ],
  connections: [
    [1, 0, 2, 0, 'write'],
    [4, 0, 5, 0, 'read'],
    [4, 0, 6, 0, 'read'],
    [8, 0, 9, 0, 'write'],
    [8, 0, 10, 0, 'write'],
    [0, 0, 3, 0, 'read'],
    [0, 0, 7, 0, 'read'],
    [3, 0, 7, 0, 'read'],
  ],
},

// ─── 9. Home Security ──────────────────────────────────────
{
  name: 'Home Security',
  desc: 'Untrusted cameras feed trusted NVR, AI motion detection, cloud alerts',
  components: [
    { type: 'mac-mini', name: 'NVR Server', x: 9, z: 0 },
    { type: 'agent', name: 'Security Agent', parent: 0 },
    { type: 'docker', name: 'Frigate NVR', parent: 0 },
    { type: 'llming', name: 'Motion AI', parent: 0 },
    { type: 'rpi', name: 'Front Camera', x: 0, z: 0 },
    { type: 'program', name: 'RTSP Stream', parent: 4 },
    { type: 'rpi', name: 'Back Camera', x: 0, z: 8 },
    { type: 'program', name: 'RTSP Stream', parent: 6 },
    { type: 'cloud-vm', name: 'Alert Hub', x: 16, z: 0 },
    { type: 'llming', name: 'Push Notify', parent: 8 },
    { type: 'mcp-server', name: 'Clip Archive', parent: 8 },
  ],
  connections: [
    [1, 0, 2, 0, 'write'],
    [1, 0, 3, 0, 'read'],
    [4, 0, 0, 0, 'read'],
    [6, 0, 0, 0, 'read'],
    [0, 0, 8, 0, 'send'],
  ],
},

// ─── 10. Data Pipeline with PII Fence ──────────────────────
{
  name: 'Data Pipeline',
  desc: 'ETL with PII fences — sensitive data cannot reach the public API',
  components: [
    { type: 'cloud-vm', name: 'Ingestion Hort', x: 0, z: 0 },
    { type: 'agent', name: 'ETL Agent', parent: 0 },
    { type: 'mcp-server', name: 'Kafka MCP', parent: 0 },
    { type: 'program', name: 'Transform', parent: 0 },
    { type: 'fence', name: 'Raw Data Fence', parent: 0 },
    { type: 'cloud-vm', name: 'Data Warehouse', x: 9, z: 0 },
    { type: 'mcp-server', name: 'BigQuery MCP', parent: 5 },
    { type: 'llming', name: 'Analytics', parent: 5 },
    { type: 'fence', name: 'PII Fence', parent: 5 },
    { type: 'cloud-vm', name: 'Public Dashboard', x: 18, z: 0 },
    { type: 'mcp-server', name: 'Dashboard API', parent: 9 },
    { type: 'program', name: 'Chart Renderer', parent: 9 },
  ],
  connections: [
    [1, 0, 2, 0, 'read'],
    [1, 0, 3, 0, 'write'],
    [0, 0, 5, 0, 'write'],
    [5, 0, 9, 0, 'read'],
  ],
},

// ─── 11. AI Research Lab ───────────────────────────────────
{
  name: 'AI Research Lab',
  desc: 'GPU cluster, model registry, experiment tracker — sandboxed compute',
  components: [
    { type: 'mac-mini', name: 'Lab Controller', x: 0, z: 0 },
    { type: 'agent', name: 'Lab Agent', parent: 0 },
    { type: 'mcp-server', name: 'Experiment MCP', parent: 0 },
    { type: 'llming', name: 'Code Generator', parent: 0 },
    { type: 'cloud-vm', name: 'GPU Node A', x: 0, z: 9 },
    { type: 'docker', name: 'Training', parent: 4 },
    { type: 'fence', name: 'Compute Fence', parent: 4 },
    { type: 'cloud-vm', name: 'GPU Node B', x: 9, z: 9 },
    { type: 'docker', name: 'Training', parent: 7 },
    { type: 'fence', name: 'Compute Fence', parent: 7 },
    { type: 'cloud-vm', name: 'Model Registry', x: 9, z: 0 },
    { type: 'mcp-server', name: 'Model Store', parent: 10 },
    { type: 'program', name: 'Benchmark', parent: 10 },
  ],
  connections: [
    [1, 0, 2, 0, 'write'],
    [1, 0, 3, 0, 'write'],
    [0, 0, 4, 0, 'send'],
    [0, 0, 7, 0, 'send'],
    [4, 0, 10, 0, 'write'],
    [7, 0, 10, 0, 'write'],
  ],
},

// ─── 12. Microservices ─────────────────────────────────────
{
  name: 'Microservices Architecture',
  desc: 'API gateway, service mesh with fenced domains, shared database',
  components: [
    { type: 'cloud-vm', name: 'API Gateway', x: 9, z: 0 },
    { type: 'mcp-server', name: 'Auth MCP', parent: 0 },
    { type: 'program', name: 'Rate Limiter', parent: 0 },
    { type: 'cloud-vm', name: 'User Service', x: 0, z: 9 },
    { type: 'docker', name: 'User API', parent: 3 },
    { type: 'mcp-server', name: 'User DB', parent: 3 },
    { type: 'fence', name: 'User Domain', parent: 3 },
    { type: 'cloud-vm', name: 'Order Service', x: 9, z: 9 },
    { type: 'docker', name: 'Order API', parent: 7 },
    { type: 'mcp-server', name: 'Order DB', parent: 7 },
    { type: 'fence', name: 'Order Domain', parent: 7 },
    { type: 'cloud-vm', name: 'Payment Service', x: 18, z: 9 },
    { type: 'docker', name: 'Payment API', parent: 11 },
    { type: 'mcp-server', name: 'Stripe MCP', parent: 11 },
    { type: 'fence', name: 'PCI Fence', parent: 11 },
  ],
  connections: [
    [0, 0, 3, 0, 'read'],
    [0, 0, 7, 0, 'read'],
    [0, 0, 11, 0, 'read'],
    [7, 0, 11, 0, 'send'],
    [3, 0, 7, 0, 'read'],
  ],
},

// ─── 13. Office Agent ──────────────────────────────────────
{
  name: 'Office Agent',
  desc: 'Agent with read access to email, write to docs, send to Slack',
  components: [
    { type: 'mac-mini', name: 'Office Hub', x: 0, z: 0 },
    { type: 'agent', name: 'Office Agent', parent: 0 },
    { type: 'llming', name: 'Email (O365)', parent: 0 },
    { type: 'llming', name: 'Google Docs', parent: 0 },
    { type: 'mcp-server', name: 'Slack MCP', parent: 0 },
    { type: 'mcp-server', name: 'Calendar MCP', parent: 0 },
    { type: 'cloud-vm', name: 'GitHub Hort', x: 9, z: 0 },
    { type: 'mcp-server', name: 'GitHub MCP', parent: 6 },
    { type: 'llming', name: 'PR Reviewer', parent: 6 },
  ],
  connections: [
    [1, 0, 2, 0, 'read'],
    [1, 0, 3, 0, 'write'],
    [1, 0, 4, 0, 'send'],
    [1, 0, 5, 0, 'read'],
    [0, 0, 6, 0, 'write'],
  ],
},

// ─── 14. IoT Sensor Grid ──────────────────────────────────
{
  name: 'IoT Sensor Grid',
  desc: 'Edge RPis feeding a central hub — read-only ingest, send to cloud',
  components: [
    { type: 'mac-mini', name: 'Central Hub', x: 9, z: 3 },
    { type: 'agent', name: 'IoT Agent', parent: 0 },
    { type: 'docker', name: 'InfluxDB', parent: 0 },
    { type: 'mcp-server', name: 'Grafana MCP', parent: 0 },
    { type: 'rpi', name: 'Greenhouse', x: 0, z: 0 },
    { type: 'mcp-server', name: 'Soil Sensors', parent: 4 },
    { type: 'rpi', name: 'Weather Station', x: 0, z: 8 },
    { type: 'mcp-server', name: 'Wind & Rain', parent: 6 },
    { type: 'rpi', name: 'Irrigation', x: 0, z: 16 },
    { type: 'program', name: 'Valve Controller', parent: 8 },
    { type: 'cloud-vm', name: 'Dashboard', x: 16, z: 3 },
    { type: 'program', name: 'Chart Renderer', parent: 10 },
    { type: 'llming', name: 'Trend Analysis', parent: 10 },
  ],
  connections: [
    [1, 0, 2, 0, 'write'],
    [1, 0, 3, 0, 'read'],
    [4, 0, 0, 0, 'read'],
    [6, 0, 0, 0, 'read'],
    [0, 0, 8, 0, 'send'],
    [0, 0, 10, 0, 'send'],
  ],
},

// ─── 15. Secure Chat Pipeline ──────────────────────────────
{
  name: 'Secure Chat Pipeline',
  desc: 'Chat backend with sandboxed LLM, fenced tool access, audit trail',
  components: [
    { type: 'mac-mini', name: 'Chat Server', x: 0, z: 0 },
    { type: 'agent', name: 'Chat Agent', parent: 0 },
    { type: 'mcp-server', name: 'Chat Backend', parent: 0 },
    { type: 'program', name: 'Audit Logger', parent: 0 },
    { type: 'cloud-vm', name: 'LLM Provider', x: 9, z: 0 },
    { type: 'llming', name: 'Claude API', parent: 4 },
    { type: 'fence', name: 'Model Fence', parent: 4 },
    { type: 'cloud-vm', name: 'Tool Sandbox', x: 0, z: 9 },
    { type: 'docker', name: 'Code Exec', parent: 7 },
    { type: 'mcp-server', name: 'Web Search', parent: 7 },
    { type: 'fence', name: 'Sandbox Fence', parent: 7 },
  ],
  connections: [
    [1, 0, 2, 0, 'write'],
    [1, 0, 3, 0, 'send'],
    [0, 0, 4, 0, 'send'],
    [0, 0, 7, 0, 'write'],
  ],
},

];
