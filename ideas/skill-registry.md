# Llming Registry

A community registry where users can share and discover Souls,
Powers, and complete Llmings.

## What it would look like

- GitHub repo with categorized Souls and Llming packages
- CLI: `hort install soul german-assistant`
- CLI: `hort install llming office365`
- Version pinning, update notifications
- Rating / download counts

## Categories

- Language & personality (Souls)
- Domain expertise — medical, legal, finance (Souls)
- Service integrations — email, calendar, CRM (Llmings with Powers)
- Platform tools — screen, input, system monitoring (Llmings with Powers)
- Automation workflows (Circuits)

## Distribution format

A Soul is just a `.md` — can be distributed as a single file.
An Llming is a directory with `extension.json` + Python code.

For Llmings with Python dependencies, need a sandboxed install
process (pip install into Llming-local venv).

## Priority

Low — need more Llmings and users first. But the architecture
should anticipate this (unique names, version fields in manifests,
no hardcoded paths).
