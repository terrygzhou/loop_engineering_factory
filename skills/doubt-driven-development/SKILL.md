---
name: doubt-driven-development
description: >
  Structured critical review of architectural decisions through the
  CLAIM → DOUBT → RECONCILE cycle. Before committing to any design
  decision, spawn a mental "devil's advocate" subagent to challenge
  assumptions. Prevents blind spots and groupthink in software
  architecture. Framework-agnostic.
version: 1.0.0
author: hermes
triggers:
  - "architectural decision"
  - "design decision"
  - "should we"
  - "architecture review"
  - "doubt driven"
  - "critical review"
  - "challenge this"
  - "second opinion"
  - "design review"
tools:
  - read_file
  - write_file
  - search_files
  - patch
---

# doubt-driven-development

## Purpose

Every significant architectural decision should pass through a structured
challenge process: state the claim, subject it to doubt from a fresh
perspective, then reconcile into a stronger decision. This prevents
the most common cause of rework — decisions that looked good on paper
but fail under real-world conditions.

## Process

### 1. CLAIM — State the proposed decision

Articulate the decision clearly and concisely:

```
CLAIM: We should use an event-driven architecture with a message broker
for inter-service communication instead of synchronous REST calls.

REASONING: Decoupling services via events improves resilience — services
can process messages independently, scale horizontally, and survive
temporary network partitions without cascading failures.
```

The claim must include:
- What you propose
- Why you propose it (the positive case)
- The alternatives considered

### 2. DOUBT — Challenge from a fresh perspective

Adopt the role of a skeptical reviewer who has **no investment** in the
proposed decision. Ask hard questions:

**Attack categories for the doubt phase:**

| Category | Questions to ask |
|---|---|
| **Complexity** | Does this add more complexity than it solves? What's the cognitive load? |
| **Performance** | Does this introduce N+1 queries, serialization overhead, or memory pressure? |
| **Flexibility** | Does this lock us into a technology? What if we need raw SQL later? |
| **Security** | Does this introduce injection risks, data leaks, or privilege escalation? |
| **Operational** | Does this complicate Docker deployments, monitoring, or debugging? |
| **Alternative** | Is there a simpler approach that covers 90% of use cases? |
| **Team** | Does the team have experience with this? What's the learning curve? |
| **Edge cases** | What happens with large datasets, concurrent access, or partial failures? |

Example doubt:

```
DOUBT: Event-driven architectures add significant operational complexity.
You now need a message broker to deploy, monitor, and maintain. Debugging
becomes harder — trace IDs must flow across async boundaries, and
reproducing issues requires replaying message sequences. For a system
where most operations are straightforward request-response patterns,
the added indirection may not be justified. Synchronous calls are
simpler to understand, easier to test, and avoid the "event storm"
problem where messages cascade uncontrollably.
```

### 3. RECONCILE — Resolve and commit

Synthesize the claim and doubt into a final decision:

```
RECONCILE: We'll use a hybrid approach — synchronous REST calls for
real-time user-facing operations, and a lightweight event bus (not a
full message broker) for background tasks and audit logging. This
keeps the core flow simple while still decoupling non-critical work.

MITIGATION: We'll implement structured correlation IDs across both sync
and async paths, add comprehensive integration tests for the event bus,
and document clear boundaries for which operations are synchronous
versus asynchronous.
```

The reconciliation must include:
- The final decision
- Any modifications to the original claim
- Specific mitigations for the doubts raised
- Explicit acceptance of any remaining risks

## Common Decision Points

Common decision points that benefit from doubt-driven development:

- **Data storage** — Relational DB vs. document store vs. in-memory cache
- **Communication pattern** — Synchronous REST vs. message queue vs. GraphQL
- **Service topology** — Monolith vs. modular monolith vs. microservices
- **Deployment** — Single container vs. multi-stage build vs. service mesh
- **Caching strategy** — In-memory vs. distributed cache (Redis/Memcached) vs. HTTP caching
- **Background processing** — In-process workers vs. task queue vs. scheduled jobs
- **Configuration management** — Environment variables vs. config files vs. remote config

## Pitfalls

- **Don't doubt for doubt's sake.** The doubt phase must be constructive
  — every challenge should propose a counter-argument or alternative,
  not just say "this is bad."
- **Don't get stuck in analysis paralysis.** Limit the cycle to
  1–2 iterations. If you can't resolve a doubt after two rounds,
  accept the risk and move forward with a note.
- **Don't skip small decisions.** The process is lightweight enough for
  any decision — the key is discipline, not formality.
- **Don't let doubt become dogma.** The doubt phase is a challenge, not
  a veto. The reconciler makes the final call.
- **Don't pretend all alternatives are equal.** Acknowledge trade-offs
  honestly rather than creating false equivalences.

## Verification

- The claim was stated clearly with reasoning.
- At least 3 distinct doubt categories were addressed.
- The reconciliation includes specific mitigations.
- Remaining risks are documented and accepted.
- The decision can be reversed later without catastrophic cost.
