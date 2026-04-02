# Circuit Branching & Data Transforms

Real workflows need conditional routing and data transformation
between nodes.

## Branching

An IF/Switch node that routes data down different paths:

```
[Email arrives] → [IF subject contains "urgent"]
                      ├── yes → [Notify Telegram immediately]
                      └── no  → [Add to summary queue]
```

### Node types needed

- **IF** — boolean condition, two outputs (yes/no)
- **Switch** — match a value against multiple cases
- **Filter** — pass/block signals based on conditions
- **Merge** — combine multiple inputs into one path

We already have TriggerCondition (field/operator/value) which
covers simple cases. Need to promote this to a general-purpose
routing concept within Circuits.

## Data transformation

Connections between nodes should be able to transform data.
Currently ConnectionDef is just source_id → target_id.

Need:
- Field mapping: `email.subject → notification.title`
- Expressions: `"Urgent: " + email.subject`
- Templates: `"New email from {sender}: {subject}"`

The existing Reaction.config and Notifier.message_template
already have a basic template system (`{field}`). Generalize
this to all connections.

## Priority

Important — without branching, Circuits can only do linear
A → B → C flows. Real automation needs conditions.
Data transforms are needed to make nodes composable (the output
format of one node rarely matches the input of another exactly).
