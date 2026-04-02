# Standalone Skills (User-Defined SOUL Files)

Currently SOUL.md files are Llming-bound. But users should also be
able to define their own agent personality and behavior without writing
an Llming.

## Concept

Standalone SOUL files that load from user directories:

```
~/.hort/souls/                    ← personal, all machines
  german-assistant.md             ← "Always respond in German"
  code-reviewer.md                ← "Review code with focus on security"

/project/.hort/souls/             ← per-project
  domain-expert.md                ← project-specific knowledge
```

## Loading precedence

Project souls > personal souls > Llming souls (lowest priority).
A user soul can override an Llming's default behavior.

## No Feature/Tool linkage

Standalone souls are pure instruction — no Feature: or Tool: lines.
They don't gate Powers, they shape behavior. Llming SOUL.md files
handle Power linkage.

## Composability

Multiple souls can be active simultaneously. The chat backend
concatenates them all into the system prompt. Order matters
(precedence = order in prompt).

## Use cases

- Language preference ("respond in German")
- Personality ("be concise" vs "explain in detail")
- Domain context ("this is a medical device project, be careful")
- Role ("you are a DevOps engineer helping with infrastructure")
- Company policies ("never share internal URLs")
