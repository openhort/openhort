# Circuit Execution Visibility

When a Circuit runs, users need to see what happened — which nodes
fired, what data flowed, what failed.

## Current state

Circuits can be configured visually but there's no
runtime visibility. A Circuit runs silently. If something fails,
the user has no idea what went wrong.

## What we need

### Node status overlay

Each node in the Circuit editor shows its last execution state:
- Green = success, with timestamp
- Red = error, with error message on hover
- Yellow = running (currently executing)
- Gray = not triggered yet

### Data inspector

Click a connection between two nodes to see what data flowed:
- Signal data (JSON)
- Timestamps
- Processing pipeline output

### Execution log

Chronological list of all Circuit executions:
- Which trigger fired
- Which nodes executed (in order)
- Input/output data per node
- Duration per node
- Errors with stack traces

### Live mode

Watch a Circuit execute in real time:
- Animated data flow along connections
- Node status updates live
- Useful for debugging and demos

## Storage

Execution history in memory (last N runs per Circuit).
Optional persistence to plugin store for audit trails.

## Priority

Essential — without this, Circuits are a black box. Users can't
debug, can't trust, can't improve.
