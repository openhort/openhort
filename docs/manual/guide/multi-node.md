# Running Across Machines

Deploy agents across multiple machines — a Mac orchestrating
Raspberry Pis, cloud VMs, or other hosts. Control flows
downward: a controller can manage workers, but workers cannot
control the controller.

## Node Roles

| Role | Can do | Cannot do |
|------|--------|-----------|
| **controller** | Start/stop agents on workers, send tasks, read audit logs | — |
| **worker** | Execute agents locally, report status to controller | Start agents on other nodes, control the controller |
| **standalone** | Everything locally (single-machine, default) | Control other nodes |

Roles are set locally on each machine — a controller cannot
force a machine to become a worker.

## Setup

### On the Controller (Mac)

Create `~/.hort/cluster.yaml`:

```yaml
cluster:
  name: home-lab
  controller:
    node_id: mac-studio
    host: 192.168.1.100
    port: 8940

  nodes:
    - node_id: pi-workshop
      host: 192.168.1.201
      port: 8940
      connection_key: "k_abc123..."
      role: worker
      capabilities:
        cpus: 4
        memory_gb: 8
      trust_level: sandboxed

    - node_id: pi-garage
      host: 192.168.1.202
      port: 8940
      connection_key: "k_def456..."
      role: worker
      capabilities:
        cpus: 4
        memory_gb: 4
      trust_level: sandboxed
```

### On Each Worker (Pi)

Create `~/.hort/node.yaml`:

```yaml
node:
  node_id: pi-workshop
  role: worker
  controller:
    host: 192.168.1.100
    port: 8940
    connection_key: "k_abc123..."
  accept_from: [mac-studio]
  max_concurrent_agents: 2
  max_budget_usd_per_session: 5.00
```

## Deploying Agents to Workers

Specify the target node in the agent YAML:

```yaml
name: data-collector
node: pi-workshop
model:
  provider: claude-code
  name: haiku
  api_key_source: controller    # key sent from controller
runtime:
  memory: 512m
  cpus: 2
budget:
  max_cost_usd: 2.00
```

Deploy from the Mac:

```bash
poetry run hort agent deploy agents/data-collector.yaml
```

The framework connects to `pi-workshop` via WebSocket tunnel,
sends the agent config with the API key, and starts it.

## Agent Placement

```yaml
node: pi-workshop        # specific node
node: any-worker          # any available worker
node: local               # controller itself (default)
node:
  require:
    arch: x86_64          # architecture filter
    memory_gb: 16         # minimum memory
  prefer: gpu             # prefer GPU nodes
```

## Cross-Node Messaging

Use `agent@node` syntax for cross-node references:

```yaml
messaging:
  can_send_to: [analyzer@pi-garage]
  can_receive_from: [coordinator@mac-studio]
```

Messages route through the controller's message bus — both sides
check permissions independently.

## Trust Levels

| Level | What's allowed |
|-------|---------------|
| `trusted` | All permissions, file mounts from controller |
| `sandboxed` | Container-only, no host file mounts, restricted network |
| `untrusted` | Container-only, no network beyond API endpoint, no file mounts |

The effective permission is the intersection of what the controller
requests and what the worker allows.

## Cluster Status

```bash
poetry run hort agent cluster status
```

```
CLUSTER: home-lab

NODE             STATUS    AGENTS  CPU    MEM     BUDGET
mac-studio       online    2/8     45%    4.2G    $2.45
pi-workshop      online    1/2     78%    1.1G    $0.82
pi-garage        online    0/2     12%    0.3G    $0.00
```

## NAT Traversal

For workers behind NAT, use the openhort access server as a relay
or set up a WireGuard VPN.

For details on the tunnel protocol, connection security, and
preventing upward control, see the
[Security](../developer/security/threat-model.md) and
[Architecture](../developer/internals/architecture.md) pages.
