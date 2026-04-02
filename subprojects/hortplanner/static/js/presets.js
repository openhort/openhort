// ═══════════════════════════════════════════════════════════════
//  HortPlanner — 30 Infrastructure Presets (grid-aligned)
//
//  Machine horts: x,z = top-left grid cell (must have 1-cell gap)
//    Mac Mini/Cloud VM: 4×4, so next hort at x+6 minimum
//    MacBook: 5×3, RPi: 3×3
//  Children: parent index only (auto-placed in parent's internal grid)
//  Connections: [fromIdx, outputPort, toIdx, inputPort]
// ═══════════════════════════════════════════════════════════════

export const PRESETS = [

// ─── 1. Home Lab Cluster ────────────────────────────────────
{
  name: 'Home Lab Cluster',
  desc: 'NAS, compute nodes, Pi-hole, cloud backup',
  components: [
    { type: 'mac-mini', name: 'NAS Server', x: 0, z: 0 },
    { type: 'docker', name: 'MinIO S3', parent: 0 },
    { type: 'docker', name: 'PostgreSQL', parent: 0 },
    { type: 'mac-mini', name: 'Compute Node', x: 6, z: 0 },
    { type: 'docker', name: 'Jupyter Lab', parent: 3 },
    { type: 'llming', name: 'AI Assistant', parent: 3 },
    { type: 'rpi', name: 'Pi-hole DNS', x: 3, z: 6 },
    { type: 'mcp-server', name: 'DNS MCP', parent: 6 },
    { type: 'cloud-vm', name: 'Cloud Backup', x: 12, z: 0 },
    { type: 'docker', name: 'Restic Backup', parent: 8 },
    { type: 'program', name: 'Cron Sync', parent: 8 },
  ],
  connections: [[0,0,3,0],[0,1,8,0],[3,0,8,1],[6,0,0,0],[6,0,3,1],[3,1,0,1]],
},

// ─── 2. Smart Home Hub ──────────────────────────────────────
{
  name: 'Smart Home Hub',
  desc: 'RPi coordinator, sensors, appliance control, Telegram alerts',
  components: [
    { type: 'rpi', name: 'Home Hub', x: 6, z: 0 },
    { type: 'docker', name: 'Home Assistant', parent: 0 },
    { type: 'mcp-server', name: 'Washing Machine MCP', x: 0, z: 0 },
    { type: 'mcp-server', name: 'Thermostat MCP', x: 0, z: 5 },
    { type: 'mcp-server', name: 'Lights MCP', x: 0, z: 10 },
    { type: 'mcp-server', name: 'Door Lock MCP', x: 0, z: 15 },
    { type: 'llming', name: 'Home Agent', parent: 0 },
    { type: 'rpi', name: 'Garage Pi', x: 12, z: 0 },
    { type: 'mcp-server', name: 'Garage Door MCP', parent: 7 },
    { type: 'cloud-vm', name: 'Telegram Bridge', x: 12, z: 5 },
    { type: 'program', name: 'Alert Pipeline', parent: 9 },
  ],
  connections: [[2,0,0,0],[3,0,0,0],[4,0,0,0],[5,0,0,0],[0,0,9,0],[7,0,0,0],[0,0,7,0]],
},

// ─── 3. Personal Media Empire ───────────────────────────────
{
  name: 'Personal Media Empire',
  desc: 'Plex, Sonarr, Radarr, transcoding farm, CDN cache',
  components: [
    { type: 'mac-mini', name: 'Media Server', x: 0, z: 0 },
    { type: 'docker', name: 'Plex', parent: 0 },
    { type: 'docker', name: 'Sonarr', parent: 0 },
    { type: 'mac-mini', name: 'Transcoder', x: 6, z: 0 },
    { type: 'docker', name: 'FFmpeg Worker', parent: 3 },
    { type: 'program', name: 'Transcode Pipeline', parent: 3 },
    { type: 'cloud-vm', name: 'CDN Edge', x: 12, z: 0 },
    { type: 'docker', name: 'Nginx Cache', parent: 6 },
    { type: 'rpi', name: 'Download Box', x: 3, z: 6 },
    { type: 'docker', name: 'qBittorrent', parent: 8 },
  ],
  connections: [[8,0,0,0],[0,0,3,0],[3,0,6,0],[0,1,6,1]],
},

// ─── 4. Home Security Network ───────────────────────────────
{
  name: 'Home Security Network',
  desc: 'Camera nodes, NVR, motion AI, mobile alerts',
  components: [
    { type: 'mac-mini', name: 'NVR Server', x: 6, z: 0 },
    { type: 'docker', name: 'Frigate NVR', parent: 0 },
    { type: 'llming', name: 'Motion AI', parent: 0 },
    { type: 'rpi', name: 'Front Camera', x: 0, z: 0 },
    { type: 'mcp-server', name: 'Camera MCP', parent: 3 },
    { type: 'rpi', name: 'Back Camera', x: 0, z: 5 },
    { type: 'mcp-server', name: 'Camera MCP', parent: 5 },
    { type: 'rpi', name: 'Garage Camera', x: 0, z: 10 },
    { type: 'mcp-server', name: 'Camera MCP', parent: 7 },
    { type: 'cloud-vm', name: 'Alert Gateway', x: 12, z: 0 },
    { type: 'program', name: 'Push Notifier', parent: 9 },
    { type: 'docker', name: 'Cloud Archive', parent: 9 },
  ],
  connections: [[3,0,0,0],[5,0,0,0],[7,0,0,0],[0,0,9,0],[0,1,9,1]],
},

// ─── 5. Developer Workstation ───────────────────────────────
{
  name: 'Developer Workstation',
  desc: 'MacBook, cloud dev VMs, CI/CD, container registry',
  components: [
    { type: 'macbook', name: 'Dev MacBook', x: 0, z: 0 },
    { type: 'docker', name: 'Local Dev', parent: 0 },
    { type: 'llming', name: 'Claude Code', parent: 0 },
    { type: 'cloud-vm', name: 'Build Server', x: 7, z: 0 },
    { type: 'docker', name: 'GitHub Runner', parent: 3 },
    { type: 'docker', name: 'Docker Registry', parent: 3 },
    { type: 'cloud-vm', name: 'Staging', x: 7, z: 6 },
    { type: 'docker', name: 'App Container', parent: 6 },
    { type: 'docker', name: 'Redis', parent: 6 },
    { type: 'cloud-vm', name: 'Production', x: 13, z: 0 },
    { type: 'docker', name: 'App Container', parent: 9 },
    { type: 'docker', name: 'PostgreSQL', parent: 9 },
    { type: 'mcp-server', name: 'Monitoring MCP', x: 13, z: 6 },
  ],
  connections: [[0,0,3,0],[3,0,6,0],[6,0,9,0],[3,1,6,1],[9,0,12,0],[0,1,6,1]],
},

// ─── 6. Microservices Platform ──────────────────────────────
{
  name: 'Microservices Platform',
  desc: 'API gateway, service mesh, observability, distributed tracing',
  components: [
    { type: 'cloud-vm', name: 'API Gateway', x: 0, z: 3 },
    { type: 'docker', name: 'Kong', parent: 0 },
    { type: 'cloud-vm', name: 'Auth Service', x: 6, z: 0 },
    { type: 'docker', name: 'Keycloak', parent: 2 },
    { type: 'cloud-vm', name: 'User Service', x: 6, z: 6 },
    { type: 'docker', name: 'Node.js App', parent: 4 },
    { type: 'docker', name: 'MongoDB', parent: 4 },
    { type: 'cloud-vm', name: 'Order Service', x: 6, z: 12 },
    { type: 'docker', name: 'Go App', parent: 7 },
    { type: 'docker', name: 'PostgreSQL', parent: 7 },
    { type: 'cloud-vm', name: 'Observability', x: 12, z: 3 },
    { type: 'docker', name: 'Prometheus', parent: 10 },
    { type: 'docker', name: 'Grafana', parent: 10 },
    { type: 'mcp-server', name: 'Metrics MCP', x: 18, z: 3 },
  ],
  connections: [[0,0,2,0],[0,1,4,0],[0,0,7,0],[2,0,4,1],[4,0,10,0],[7,0,10,1],[10,0,13,0]],
},

// ─── 7. CI/CD Pipeline ──────────────────────────────────────
{
  name: 'CI/CD Pipeline',
  desc: 'Source control, build farm, test matrix, deploy stages',
  components: [
    { type: 'cloud-vm', name: 'Git Server', x: 0, z: 2 },
    { type: 'docker', name: 'Gitea', parent: 0 },
    { type: 'mac-mini', name: 'Build Farm A', x: 6, z: 0 },
    { type: 'docker', name: 'Jenkins Agent', parent: 2 },
    { type: 'program', name: 'Build Pipeline', parent: 2 },
    { type: 'mac-mini', name: 'Build Farm B', x: 6, z: 6 },
    { type: 'docker', name: 'Jenkins Agent', parent: 5 },
    { type: 'cloud-vm', name: 'Artifact Store', x: 12, z: 2 },
    { type: 'docker', name: 'Nexus', parent: 7 },
    { type: 'cloud-vm', name: 'Test Cluster', x: 18, z: 0 },
    { type: 'docker', name: 'Test Runner', parent: 9 },
    { type: 'cloud-vm', name: 'Staging Deploy', x: 18, z: 6 },
    { type: 'docker', name: 'K8s Staging', parent: 11 },
    { type: 'llming', name: 'Review Agent', x: 24, z: 2 },
  ],
  connections: [[0,0,2,0],[0,0,5,0],[2,0,7,0],[5,0,7,0],[7,0,9,0],[7,1,11,0],[9,0,13,0]],
},

// ─── 8. Data Lake Pipeline ──────────────────────────────────
{
  name: 'Data Lake Pipeline',
  desc: 'Ingest, transform, warehouse, analytics, ML feature store',
  components: [
    { type: 'cloud-vm', name: 'Ingest Gateway', x: 0, z: 0 },
    { type: 'docker', name: 'Kafka', parent: 0 },
    { type: 'docker', name: 'Debezium CDC', parent: 0 },
    { type: 'cloud-vm', name: 'Transform Layer', x: 6, z: 0 },
    { type: 'docker', name: 'Apache Spark', parent: 3 },
    { type: 'docker', name: 'dbt', parent: 3 },
    { type: 'cloud-vm', name: 'Data Warehouse', x: 12, z: 0 },
    { type: 'docker', name: 'ClickHouse', parent: 6 },
    { type: 'cloud-vm', name: 'Feature Store', x: 12, z: 6 },
    { type: 'docker', name: 'Feast', parent: 8 },
    { type: 'cloud-vm', name: 'Analytics', x: 18, z: 0 },
    { type: 'docker', name: 'Superset', parent: 10 },
    { type: 'llming', name: 'Data Analyst AI', parent: 10 },
    { type: 'mcp-server', name: 'Query MCP', x: 18, z: 6 },
  ],
  connections: [[0,0,3,0],[0,1,3,1],[3,0,6,0],[3,1,8,0],[6,0,10,0],[8,0,10,1],[10,0,13,0]],
},

// ─── 9. Multi-Cloud Bridge ──────────────────────────────────
{
  name: 'Multi-Cloud Bridge',
  desc: 'AWS, Azure, GCP bridged via central controller',
  components: [
    { type: 'mac-mini', name: 'Control Plane', x: 6, z: 3 },
    { type: 'llming', name: 'Cloud Orchestrator', parent: 0 },
    { type: 'mcp-server', name: 'Terraform MCP', parent: 0 },
    { type: 'cloud-vm', name: 'AWS Region', x: 0, z: 0 },
    { type: 'docker', name: 'EKS Cluster', parent: 3 },
    { type: 'docker', name: 'RDS PostgreSQL', parent: 3 },
    { type: 'cloud-vm', name: 'Azure Region', x: 0, z: 9 },
    { type: 'docker', name: 'AKS Cluster', parent: 6 },
    { type: 'docker', name: 'Cosmos DB', parent: 6 },
    { type: 'cloud-vm', name: 'GCP Region', x: 12, z: 3 },
    { type: 'docker', name: 'GKE Cluster', parent: 9 },
    { type: 'docker', name: 'Cloud SQL', parent: 9 },
  ],
  connections: [[0,0,3,0],[0,0,6,0],[0,1,9,0],[3,0,6,0],[6,0,9,0],[3,1,9,1]],
},

// ─── 10. Security Operations Center ─────────────────────────
{
  name: 'Security Operations Center',
  desc: 'SIEM, threat intel, incident response, honeypot network',
  components: [
    { type: 'mac-mini', name: 'SIEM Core', x: 6, z: 3 },
    { type: 'docker', name: 'Elasticsearch', parent: 0 },
    { type: 'docker', name: 'Kibana', parent: 0 },
    { type: 'llming', name: 'Threat Analyst AI', parent: 0 },
    { type: 'cloud-vm', name: 'Threat Intel', x: 0, z: 0 },
    { type: 'docker', name: 'MISP', parent: 4 },
    { type: 'mcp-server', name: 'IOC Feed MCP', parent: 4 },
    { type: 'cloud-vm', name: 'Honeypot Net', x: 0, z: 9 },
    { type: 'docker', name: 'Cowrie SSH', parent: 7 },
    { type: 'docker', name: 'Dionaea', parent: 7 },
    { type: 'cloud-vm', name: 'Response Node', x: 12, z: 3 },
    { type: 'docker', name: 'TheHive', parent: 10 },
    { type: 'docker', name: 'Cortex', parent: 10 },
    { type: 'program', name: 'Auto-Response', parent: 10 },
  ],
  connections: [[4,0,0,0],[7,0,0,1],[0,0,10,0],[0,1,10,1],[4,0,10,1],[10,0,7,0]],
},

// ─── 11. ML Training Pipeline ───────────────────────────────
{
  name: 'ML Training Pipeline',
  desc: 'Data prep, distributed training, model registry, serving',
  components: [
    { type: 'cloud-vm', name: 'Data Prep', x: 0, z: 0 },
    { type: 'docker', name: 'Label Studio', parent: 0 },
    { type: 'program', name: 'Augmentation', parent: 0 },
    { type: 'cloud-vm', name: 'GPU Trainer A', x: 6, z: 0 },
    { type: 'docker', name: 'PyTorch Worker', parent: 3 },
    { type: 'cloud-vm', name: 'GPU Trainer B', x: 6, z: 6 },
    { type: 'docker', name: 'PyTorch Worker', parent: 5 },
    { type: 'cloud-vm', name: 'Model Registry', x: 12, z: 0 },
    { type: 'docker', name: 'MLflow', parent: 7 },
    { type: 'docker', name: 'MinIO Artifacts', parent: 7 },
    { type: 'cloud-vm', name: 'Serving Cluster', x: 18, z: 0 },
    { type: 'docker', name: 'TorchServe', parent: 10 },
    { type: 'mcp-server', name: 'Inference MCP', x: 18, z: 6 },
  ],
  connections: [[0,0,3,0],[0,0,5,0],[3,0,7,0],[5,0,7,0],[7,0,10,0],[10,0,12,0]],
},

// ─── 12. LLM Agent Orchestra ────────────────────────────────
{
  name: 'LLM Agent Orchestra',
  desc: 'Multi-agent system with tool servers, memory, coordinator',
  components: [
    { type: 'mac-mini', name: 'Orchestrator', x: 6, z: 3 },
    { type: 'llming', name: 'Coordinator Agent', parent: 0 },
    { type: 'mcp-server', name: 'Memory MCP', parent: 0 },
    { type: 'cloud-vm', name: 'Research Pod', x: 0, z: 0 },
    { type: 'llming', name: 'Researcher', parent: 3 },
    { type: 'mcp-server', name: 'Web Search MCP', parent: 3 },
    { type: 'cloud-vm', name: 'Coder Pod', x: 0, z: 9 },
    { type: 'llming', name: 'Coder Agent', parent: 6 },
    { type: 'mcp-server', name: 'Filesystem MCP', parent: 6 },
    { type: 'cloud-vm', name: 'Reviewer Pod', x: 12, z: 0 },
    { type: 'llming', name: 'Review Agent', parent: 9 },
    { type: 'cloud-vm', name: 'Deploy Pod', x: 12, z: 9 },
    { type: 'llming', name: 'Deploy Agent', parent: 11 },
    { type: 'mcp-server', name: 'K8s MCP', parent: 11 },
  ],
  connections: [[0,0,3,0],[0,0,6,0],[0,1,9,0],[0,1,11,0],[3,0,9,1],[6,0,11,1],[9,0,0,0],[11,0,0,1]],
},

// ─── 13. RAG Knowledge Platform ─────────────────────────────
{
  name: 'RAG Knowledge Platform',
  desc: 'Document ingest, embedding, vector DB, retrieval agents',
  components: [
    { type: 'cloud-vm', name: 'Ingest Pipeline', x: 0, z: 0 },
    { type: 'docker', name: 'Document Parser', parent: 0 },
    { type: 'docker', name: 'Chunker', parent: 0 },
    { type: 'cloud-vm', name: 'Embedding Service', x: 6, z: 0 },
    { type: 'docker', name: 'Sentence-BERT', parent: 3 },
    { type: 'cloud-vm', name: 'Vector Store', x: 12, z: 0 },
    { type: 'docker', name: 'Qdrant', parent: 5 },
    { type: 'mac-mini', name: 'RAG Server', x: 18, z: 0 },
    { type: 'llming', name: 'Retrieval Agent', parent: 7 },
    { type: 'mcp-server', name: 'Knowledge MCP', parent: 7 },
  ],
  connections: [[0,0,3,0],[3,0,5,0],[5,0,7,0],[7,0,3,1]],
},

// ─── 14. Computer Vision Pipeline ───────────────────────────
{
  name: 'Computer Vision Pipeline',
  desc: 'Camera ingest, real-time inference, tracking, dashboard',
  components: [
    { type: 'rpi', name: 'Camera Node A', x: 0, z: 0 },
    { type: 'mcp-server', name: 'RTSP MCP', parent: 0 },
    { type: 'rpi', name: 'Camera Node B', x: 0, z: 5 },
    { type: 'mcp-server', name: 'RTSP MCP', parent: 2 },
    { type: 'rpi', name: 'Camera Node C', x: 0, z: 10 },
    { type: 'mcp-server', name: 'RTSP MCP', parent: 4 },
    { type: 'cloud-vm', name: 'Inference Server', x: 5, z: 3 },
    { type: 'docker', name: 'YOLO v8', parent: 6 },
    { type: 'docker', name: 'DeepSORT', parent: 6 },
    { type: 'mac-mini', name: 'Dashboard', x: 11, z: 3 },
    { type: 'docker', name: 'Grafana', parent: 9 },
    { type: 'llming', name: 'Scene Analyzer', parent: 9 },
  ],
  connections: [[0,0,6,0],[2,0,6,0],[4,0,6,0],[6,0,9,0],[6,1,9,1]],
},

// ─── 15. Federated Learning Network ─────────────────────────
{
  name: 'Federated Learning Network',
  desc: 'Edge training nodes, central aggregator, privacy-preserving ML',
  components: [
    { type: 'cloud-vm', name: 'Aggregator', x: 6, z: 3 },
    { type: 'docker', name: 'Flower Server', parent: 0 },
    { type: 'llming', name: 'Coordinator AI', parent: 0 },
    { type: 'mac-mini', name: 'Hospital Node', x: 0, z: 0 },
    { type: 'docker', name: 'FL Client', parent: 3 },
    { type: 'mac-mini', name: 'Bank Node', x: 0, z: 6 },
    { type: 'docker', name: 'FL Client', parent: 5 },
    { type: 'mac-mini', name: 'Retail Node', x: 0, z: 12 },
    { type: 'docker', name: 'FL Client', parent: 7 },
    { type: 'cloud-vm', name: 'Model Registry', x: 12, z: 3 },
    { type: 'docker', name: 'MLflow', parent: 9 },
  ],
  connections: [[3,0,0,0],[5,0,0,0],[7,0,0,1],[0,0,9,0],[0,1,9,1]],
},

// ─── 16. IoT Sensor Network ─────────────────────────────────
{
  name: 'IoT Sensor Network',
  desc: 'Mesh of sensors, edge gateways, time-series DB, alerting',
  components: [
    { type: 'rpi', name: 'Gateway North', x: 0, z: 0 },
    { type: 'mcp-server', name: 'MQTT Broker', parent: 0 },
    { type: 'rpi', name: 'Gateway South', x: 0, z: 5 },
    { type: 'mcp-server', name: 'MQTT Broker', parent: 2 },
    { type: 'rpi', name: 'Gateway East', x: 0, z: 10 },
    { type: 'mcp-server', name: 'MQTT Broker', parent: 4 },
    { type: 'cloud-vm', name: 'Time Series DB', x: 5, z: 3 },
    { type: 'docker', name: 'InfluxDB', parent: 6 },
    { type: 'docker', name: 'Telegraf', parent: 6 },
    { type: 'mac-mini', name: 'Analytics Hub', x: 11, z: 3 },
    { type: 'docker', name: 'Grafana', parent: 9 },
    { type: 'llming', name: 'Anomaly Agent', parent: 9 },
    { type: 'program', name: 'Alert Pipeline', parent: 9 },
  ],
  connections: [[0,0,6,0],[2,0,6,0],[4,0,6,0],[6,0,9,0],[6,1,9,1]],
},

// ─── 17. Industrial Control System ──────────────────────────
{
  name: 'Industrial Control System',
  desc: 'PLCs, SCADA, historian, safety interlock, HMI',
  components: [
    { type: 'rpi', name: 'PLC Zone A', x: 0, z: 0 },
    { type: 'mcp-server', name: 'Modbus MCP', parent: 0 },
    { type: 'rpi', name: 'PLC Zone B', x: 0, z: 5 },
    { type: 'mcp-server', name: 'Modbus MCP', parent: 2 },
    { type: 'mac-mini', name: 'SCADA Server', x: 5, z: 0 },
    { type: 'docker', name: 'Ignition', parent: 4 },
    { type: 'docker', name: 'Historian DB', parent: 4 },
    { type: 'mac-mini', name: 'Safety Controller', x: 5, z: 6 },
    { type: 'program', name: 'Interlock Logic', parent: 7 },
    { type: 'macbook', name: 'Engineer HMI', x: 11, z: 0 },
    { type: 'llming', name: 'Process AI', parent: 9 },
  ],
  connections: [[0,0,4,0],[2,0,4,0],[4,0,9,0],[4,1,9,1],[7,0,0,0],[7,0,2,0]],
},

// ─── 18. Autonomous Fleet Management ────────────────────────
{
  name: 'Autonomous Fleet Management',
  desc: 'Vehicle edge AI, fleet controller, telemetry',
  components: [
    { type: 'cloud-vm', name: 'Fleet Controller', x: 6, z: 3 },
    { type: 'docker', name: 'Route Optimizer', parent: 0 },
    { type: 'llming', name: 'Fleet AI', parent: 0 },
    { type: 'rpi', name: 'Vehicle Alpha', x: 0, z: 0 },
    { type: 'program', name: 'Edge AI', parent: 3 },
    { type: 'rpi', name: 'Vehicle Beta', x: 0, z: 5 },
    { type: 'program', name: 'Edge AI', parent: 5 },
    { type: 'rpi', name: 'Vehicle Gamma', x: 0, z: 10 },
    { type: 'program', name: 'Edge AI', parent: 7 },
    { type: 'cloud-vm', name: 'Telemetry Lake', x: 12, z: 3 },
    { type: 'docker', name: 'TimescaleDB', parent: 9 },
    { type: 'docker', name: 'Grafana', parent: 9 },
  ],
  connections: [[3,0,0,0],[5,0,0,0],[7,0,0,1],[0,0,9,0],[0,1,9,1]],
},

// ─── 19. Smart Agriculture ──────────────────────────────────
{
  name: 'Smart Agriculture',
  desc: 'Soil sensors, drone controller, irrigation, weather',
  components: [
    { type: 'rpi', name: 'Soil Sensor Array', x: 0, z: 0 },
    { type: 'mcp-server', name: 'Moisture MCP', parent: 0 },
    { type: 'rpi', name: 'Weather Station', x: 0, z: 5 },
    { type: 'mcp-server', name: 'Weather MCP', parent: 2 },
    { type: 'mac-mini', name: 'Farm Controller', x: 5, z: 0 },
    { type: 'docker', name: 'Irrigation Logic', parent: 4 },
    { type: 'llming', name: 'Crop Advisor AI', parent: 4 },
    { type: 'rpi', name: 'Drone Base', x: 5, z: 6 },
    { type: 'program', name: 'Flight Planner', parent: 7 },
    { type: 'cloud-vm', name: 'Analytics', x: 11, z: 0 },
    { type: 'docker', name: 'Yield Predictor', parent: 9 },
  ],
  connections: [[0,0,4,0],[2,0,4,0],[4,0,7,0],[4,0,9,0],[4,1,9,1]],
},

// ─── 20. Retail Analytics Platform ──────────────────────────
{
  name: 'Retail Analytics Platform',
  desc: 'In-store sensors, POS integration, real-time analytics',
  components: [
    { type: 'rpi', name: 'Store Alpha', x: 0, z: 0 },
    { type: 'mcp-server', name: 'POS MCP', parent: 0 },
    { type: 'rpi', name: 'Store Beta', x: 0, z: 5 },
    { type: 'mcp-server', name: 'POS MCP', parent: 2 },
    { type: 'rpi', name: 'Store Gamma', x: 0, z: 10 },
    { type: 'mcp-server', name: 'POS MCP', parent: 4 },
    { type: 'cloud-vm', name: 'Analytics Engine', x: 5, z: 3 },
    { type: 'docker', name: 'Apache Flink', parent: 6 },
    { type: 'docker', name: 'Redis Cache', parent: 6 },
    { type: 'cloud-vm', name: 'Pricing Service', x: 11, z: 0 },
    { type: 'llming', name: 'Pricing AI', parent: 9 },
    { type: 'cloud-vm', name: 'Inventory Hub', x: 11, z: 6 },
    { type: 'docker', name: 'Inventory DB', parent: 11 },
  ],
  connections: [[0,0,6,0],[2,0,6,0],[4,0,6,0],[6,0,9,0],[6,1,11,0],[9,0,0,0]],
},

// ─── 21. Genomics Pipeline ──────────────────────────────────
{
  name: 'Genomics Pipeline',
  desc: 'Sequencer ingest, alignment, variant calling, annotation',
  components: [
    { type: 'mac-mini', name: 'Sequencer Interface', x: 0, z: 0 },
    { type: 'docker', name: 'BaseSpace Agent', parent: 0 },
    { type: 'cloud-vm', name: 'Alignment Cluster', x: 6, z: 0 },
    { type: 'docker', name: 'BWA-MEM2', parent: 2 },
    { type: 'docker', name: 'SAMtools', parent: 2 },
    { type: 'cloud-vm', name: 'Variant Caller', x: 6, z: 6 },
    { type: 'docker', name: 'GATK', parent: 5 },
    { type: 'docker', name: 'DeepVariant', parent: 5 },
    { type: 'cloud-vm', name: 'Annotation', x: 12, z: 0 },
    { type: 'docker', name: 'VEP', parent: 8 },
    { type: 'docker', name: 'ClinVar DB', parent: 8 },
    { type: 'llming', name: 'Report Generator', x: 18, z: 0 },
  ],
  connections: [[0,0,2,0],[0,0,5,0],[2,0,5,0],[5,0,8,0],[8,0,11,0]],
},

// ─── 22. Financial Trading Platform ─────────────────────────
{
  name: 'Financial Trading Platform',
  desc: 'Market data, strategy engine, execution, risk, audit',
  components: [
    { type: 'cloud-vm', name: 'Market Data', x: 0, z: 2 },
    { type: 'docker', name: 'FIX Gateway', parent: 0 },
    { type: 'docker', name: 'Tick Store', parent: 0 },
    { type: 'mac-mini', name: 'Strategy Engine', x: 6, z: 0 },
    { type: 'docker', name: 'Alpha Model', parent: 3 },
    { type: 'llming', name: 'Signal AI', parent: 3 },
    { type: 'mac-mini', name: 'Execution', x: 6, z: 6 },
    { type: 'docker', name: 'Order Router', parent: 6 },
    { type: 'docker', name: 'Smart Executor', parent: 6 },
    { type: 'cloud-vm', name: 'Risk Engine', x: 12, z: 0 },
    { type: 'docker', name: 'VaR Calculator', parent: 9 },
    { type: 'program', name: 'Position Limits', parent: 9 },
    { type: 'cloud-vm', name: 'Audit & Compliance', x: 12, z: 6 },
    { type: 'docker', name: 'Trade Ledger', parent: 12 },
  ],
  connections: [[0,0,3,0],[0,1,6,0],[3,0,6,0],[3,1,9,0],[6,0,9,0],[6,1,12,0],[9,0,3,1]],
},

// ─── 23. Content Delivery Network ───────────────────────────
{
  name: 'Content Delivery Network',
  desc: 'Origin servers, edge caches, DNS routing, purge',
  components: [
    { type: 'cloud-vm', name: 'Origin Cluster', x: 6, z: 3 },
    { type: 'docker', name: 'Nginx Origin', parent: 0 },
    { type: 'docker', name: 'Object Store', parent: 0 },
    { type: 'cloud-vm', name: 'Edge US-East', x: 0, z: 0 },
    { type: 'docker', name: 'Varnish Cache', parent: 3 },
    { type: 'cloud-vm', name: 'Edge US-West', x: 0, z: 6 },
    { type: 'docker', name: 'Varnish Cache', parent: 5 },
    { type: 'cloud-vm', name: 'Edge EU', x: 0, z: 12 },
    { type: 'docker', name: 'Varnish Cache', parent: 7 },
    { type: 'cloud-vm', name: 'Edge Asia', x: 12, z: 0 },
    { type: 'docker', name: 'Varnish Cache', parent: 9 },
    { type: 'mac-mini', name: 'DNS Controller', x: 12, z: 6 },
    { type: 'docker', name: 'PowerDNS', parent: 11 },
    { type: 'program', name: 'Purge Controller', parent: 11 },
  ],
  connections: [[0,0,3,0],[0,0,5,0],[0,1,7,0],[0,1,9,0],[11,0,3,0],[11,0,5,0],[11,0,7,0],[11,0,9,0]],
},

// ─── 24. Digital Twin Platform ──────────────────────────────
{
  name: 'Digital Twin Platform',
  desc: 'Physical asset sensors, simulation engine, real-time sync',
  components: [
    { type: 'rpi', name: 'Sensor Gateway A', x: 0, z: 0 },
    { type: 'mcp-server', name: 'OPC-UA MCP', parent: 0 },
    { type: 'rpi', name: 'Sensor Gateway B', x: 0, z: 5 },
    { type: 'mcp-server', name: 'MQTT MCP', parent: 2 },
    { type: 'cloud-vm', name: 'Simulation Engine', x: 5, z: 0 },
    { type: 'docker', name: 'FMU Runtime', parent: 4 },
    { type: 'docker', name: 'State Sync', parent: 4 },
    { type: 'cloud-vm', name: '3D Visualization', x: 11, z: 0 },
    { type: 'docker', name: 'Three.js Server', parent: 7 },
    { type: 'cloud-vm', name: 'Predictive Engine', x: 11, z: 6 },
    { type: 'llming', name: 'Prediction AI', parent: 9 },
    { type: 'docker', name: 'TF Serving', parent: 9 },
  ],
  connections: [[0,0,4,0],[2,0,4,0],[4,0,7,0],[4,1,9,0],[7,0,9,1],[9,0,4,1]],
},

// ─── 25. Satellite Ground Station ───────────────────────────
{
  name: 'Satellite Ground Station',
  desc: 'Antenna control, signal processing, orbit prediction',
  components: [
    { type: 'rpi', name: 'Antenna Controller', x: 0, z: 0 },
    { type: 'mcp-server', name: 'Rotator MCP', parent: 0 },
    { type: 'mac-mini', name: 'Signal Processor', x: 5, z: 0 },
    { type: 'docker', name: 'GNU Radio', parent: 2 },
    { type: 'docker', name: 'gr-satellites', parent: 2 },
    { type: 'mac-mini', name: 'Orbit Predictor', x: 5, z: 6 },
    { type: 'docker', name: 'SatNOGS', parent: 5 },
    { type: 'program', name: 'TLE Updater', parent: 5 },
    { type: 'cloud-vm', name: 'Data Archive', x: 11, z: 0 },
    { type: 'docker', name: 'MinIO', parent: 8 },
    { type: 'docker', name: 'Metadata DB', parent: 8 },
    { type: 'llming', name: 'Pass Scheduler AI', x: 11, z: 6 },
  ],
  connections: [[0,0,2,0],[5,0,0,0],[2,0,8,0],[2,1,8,1],[5,0,2,1],[11,0,5,0]],
},

// ─── 26. Kubernetes Cluster ─────────────────────────────────
{
  name: 'Kubernetes Cluster',
  desc: 'Control plane, worker nodes, ingress, monitoring',
  components: [
    { type: 'cloud-vm', name: 'Control Plane', x: 6, z: 0 },
    { type: 'docker', name: 'kube-apiserver', parent: 0 },
    { type: 'docker', name: 'etcd', parent: 0 },
    { type: 'cloud-vm', name: 'Worker Node 1', x: 0, z: 6 },
    { type: 'docker', name: 'Pod: Frontend', parent: 3 },
    { type: 'docker', name: 'Pod: API', parent: 3 },
    { type: 'cloud-vm', name: 'Worker Node 2', x: 6, z: 6 },
    { type: 'docker', name: 'Pod: API', parent: 6 },
    { type: 'docker', name: 'Pod: Worker', parent: 6 },
    { type: 'cloud-vm', name: 'Worker Node 3', x: 12, z: 6 },
    { type: 'docker', name: 'Pod: DB', parent: 9 },
    { type: 'docker', name: 'Pod: Cache', parent: 9 },
    { type: 'cloud-vm', name: 'Monitoring', x: 6, z: 12 },
    { type: 'docker', name: 'Prometheus', parent: 12 },
    { type: 'docker', name: 'Grafana', parent: 12 },
  ],
  connections: [[0,0,3,0],[0,0,6,0],[0,1,9,0],[3,0,9,0],[6,0,9,0],[0,0,12,0]],
},

// ─── 27. Blockchain Network ─────────────────────────────────
{
  name: 'Blockchain Network',
  desc: 'Validator nodes, RPC endpoints, explorer, indexer',
  components: [
    { type: 'cloud-vm', name: 'Validator 1', x: 0, z: 0 },
    { type: 'docker', name: 'Geth Node', parent: 0 },
    { type: 'cloud-vm', name: 'Validator 2', x: 0, z: 6 },
    { type: 'docker', name: 'Geth Node', parent: 2 },
    { type: 'cloud-vm', name: 'Validator 3', x: 0, z: 12 },
    { type: 'docker', name: 'Geth Node', parent: 4 },
    { type: 'cloud-vm', name: 'RPC Gateway', x: 6, z: 3 },
    { type: 'docker', name: 'JSON-RPC Proxy', parent: 6 },
    { type: 'cloud-vm', name: 'Block Explorer', x: 6, z: 9 },
    { type: 'docker', name: 'Blockscout', parent: 8 },
    { type: 'docker', name: 'PostgreSQL', parent: 8 },
    { type: 'cloud-vm', name: 'Indexer', x: 12, z: 3 },
    { type: 'docker', name: 'The Graph', parent: 11 },
    { type: 'mcp-server', name: 'Chain MCP', x: 12, z: 9 },
  ],
  connections: [[0,0,2,0],[2,0,4,0],[0,0,4,0],[0,0,6,0],[2,0,6,0],[6,0,8,0],[6,0,11,0],[6,1,13,0]],
},

// ─── 28. Quantum Computing Bridge ───────────────────────────
{
  name: 'Quantum Computing Bridge',
  desc: 'Classical prep, quantum interface, error correction',
  components: [
    { type: 'mac-mini', name: 'Classical Prep', x: 0, z: 0 },
    { type: 'docker', name: 'Qiskit Compiler', parent: 0 },
    { type: 'program', name: 'Circuit Optimizer', parent: 0 },
    { type: 'cloud-vm', name: 'Quantum Interface', x: 6, z: 0 },
    { type: 'docker', name: 'IBM Q Connector', parent: 3 },
    { type: 'docker', name: 'IonQ Connector', parent: 3 },
    { type: 'cloud-vm', name: 'Error Correction', x: 12, z: 0 },
    { type: 'docker', name: 'QEC Decoder', parent: 6 },
    { type: 'program', name: 'Syndrome Extract', parent: 6 },
    { type: 'mac-mini', name: 'Post-Processing', x: 18, z: 0 },
    { type: 'docker', name: 'Result Analyzer', parent: 9 },
    { type: 'llming', name: 'Quantum AI', parent: 9 },
  ],
  connections: [[0,0,3,0],[0,1,3,1],[3,0,6,0],[3,1,6,1],[6,0,9,0],[6,1,9,1]],
},

// ─── 29. Space Station Control ──────────────────────────────
{
  name: 'Space Station Control',
  desc: 'Life support, comms, experiments, crew AI',
  components: [
    { type: 'mac-mini', name: 'Life Support', x: 0, z: 0 },
    { type: 'mcp-server', name: 'O2 System MCP', parent: 0 },
    { type: 'mcp-server', name: 'CO2 Scrubber MCP', parent: 0 },
    { type: 'program', name: 'Atmo Monitor', parent: 0 },
    { type: 'mac-mini', name: 'Comms Array', x: 0, z: 6 },
    { type: 'docker', name: 'TDRS Link', parent: 4 },
    { type: 'docker', name: 'Protocol Stack', parent: 4 },
    { type: 'mac-mini', name: 'Experiment Ctrl', x: 6, z: 0 },
    { type: 'docker', name: 'Fluid Physics', parent: 7 },
    { type: 'docker', name: 'Plant Growth', parent: 7 },
    { type: 'llming', name: 'Experiment AI', parent: 7 },
    { type: 'mac-mini', name: 'Navigation', x: 6, z: 6 },
    { type: 'program', name: 'Orbit Maint', parent: 11 },
    { type: 'mcp-server', name: 'Thruster MCP', parent: 11 },
    { type: 'macbook', name: 'Crew Interface', x: 13, z: 0 },
    { type: 'llming', name: 'Crew Assistant AI', parent: 14 },
  ],
  connections: [[0,0,4,0],[4,0,14,0],[7,0,4,0],[11,0,4,0],[0,0,14,1],[7,0,14,0]],
},

// ─── 30. Neural Architecture Search ─────────────────────────
{
  name: 'Neural Architecture Search',
  desc: 'Search controller, evaluation cluster, model zoo',
  components: [
    { type: 'cloud-vm', name: 'NAS Controller', x: 6, z: 0 },
    { type: 'docker', name: 'Search Algorithm', parent: 0 },
    { type: 'llming', name: 'Architecture AI', parent: 0 },
    { type: 'cloud-vm', name: 'GPU Eval A', x: 0, z: 6 },
    { type: 'docker', name: 'Train & Eval', parent: 3 },
    { type: 'cloud-vm', name: 'GPU Eval B', x: 6, z: 6 },
    { type: 'docker', name: 'Train & Eval', parent: 5 },
    { type: 'cloud-vm', name: 'GPU Eval C', x: 12, z: 6 },
    { type: 'docker', name: 'Train & Eval', parent: 7 },
    { type: 'cloud-vm', name: 'Model Zoo', x: 6, z: 12 },
    { type: 'docker', name: 'Model Registry', parent: 9 },
    { type: 'docker', name: 'Benchmark Suite', parent: 9 },
    { type: 'mcp-server', name: 'AutoML MCP', x: 12, z: 12 },
  ],
  connections: [[0,0,3,0],[0,0,5,0],[0,1,7,0],[3,0,9,0],[5,0,9,0],[7,0,9,1],[9,0,12,0]],
},

];
