# O-AA ADM Lite Architecture Document
| Document ID | ARC-001-OAAL-v1.0 |
|-------------|-------------------|
| **Document Type** | O-AA ADM Lite (Sprint-Driven Architecture) |
| **Project** | Australian Post Digital Transformation (Project 001) |
| **Classification** | PUBLIC |
| **Status** | DRAFT |
| **Version** | 1.0 |
| **Created Date** | 2026-09-01 |
| **Last Modified** | 2026-09-01 |
| **Review Cycle** | Per sprint cycle |
| **Next Review Date** | 2026-10-01 |
| **Owner** | Enterprise Architecture Lead |
| **Reviewed By** | CISO, Australian Post |
| **Approved By** | Postmaster General |
| **Distribution** | Australian Post Digital Team, Enterprise Architecture, CISO Office, Product Team |

## Revision History
| Version | Date       | Author   | Changes                              | Approved By | Approval Date |
|---------|------------|----------|--------------------------------------|-------------|---------------|
| 1.0     | 2026-09-01 | ArcKit AI| Initial O-AA ADM Lite creation       | [PENDING]   | [PENDING]     |

---

## 1. Introduction

This document defines the **O-AA ADM Lite** architecture engagement for the
**Australian Post Digital Transformation** project. It maps the TOGAF ADM
cycle to agile sprints, compressing the traditional architecture development
method into a sprint-driven engagement suitable for rapid delivery windows.

### 1.1 Purpose

The O-AA ADM Lite approach enables rapid architecture delivery across 2-4 week
engagement windows while maintaining TOGAF ADM alignment. This document:

- Maps TOGAF ADM phases to agile sprints
- Defines sprint deliverables with schema validation
- Establishes a lightweight governance cadence for the programme
- Aligns with O-AA axioms and Australian data-sovereignty constraints

### 1.2 Scope

This engagement covers the full architecture lifecycle from vision through
governance, compressed into sprint cycles for a customer-facing AI digital
transformation (tracking Q&A, document analysis, route/logistics advisory).

### 1.3 O-AA Axioms Applied

- **Axiom 1** — The purpose of architecture is to improve the organisation:
  every sprint decision traces to a business outcome for Australian Post.
- **Axiom 3** — Architecture must be product-centric: the organising principle
  is the customer-service product, not technical layers.
- **Axiom 4** — Architecture must be fit for purpose: scope is constrained to
  the 12-week delivery horizon, no gold-plating.
- **Axiom 6** — Architecture is a shared asset: compliance and data controls
  are embedded in every sprint artefact.

---

## 2. Sprint Map

| Sprint | TOGAF Phases | Focus | Duration | Key Output |
|--------|-------------|-------|----------|------------|
| Sprint 0 | ADM-P + A | Vision + Stakeholders | 1 week | `vision.yaml` |
| Sprint 1 | ADM-B + C (part) | Business + Data Architecture | 2 weeks | `business-architecture.yaml`, `data-architecture.yaml` |
| Sprint 2 | ADM-C (part) + D | Technology Architecture | 2 weeks | `technology-architecture.yaml` |
| Sprint 3 | ADM-E + F | Implementation Wave | 2 weeks | `implementation-strategy.yaml` |
| Sprint 4+ | ADM-G + H | Governance + Change | Ongoing | `governance-report.yaml`, `change-request.yaml` |

**Engagement window:** 4-8 weeks (Sprints 0-3) with continuous governance from
Sprint 4. Sprint length: 2 weeks.

---

## 3. Sprint 0: Vision + Stakeholders (ADM-P + A)

**Duration:** 1 week
**Goal:** Agreement on scope, constraints, and success criteria. Stakeholder
map finalised.

### 3.1 Architecture Vision (vision.yaml)

```yaml
vision:
  scope:
    ai_workload_type: "RAG pipeline + agent orchestration"
    use_cases: ["customer_tracking_qa", "document_analysis", "route_logistics_advisory"]
    data_classification: "regulated"
    user_count: 5000
    latency_requirement_ms: 2000
  constraints:
    budget_aud: 1500000
    timeline_weeks: 12
    infrastructure: "hybrid"
    jurisdiction: "AU"
  stakeholders:
    - role: "CIO"
      concern: "data sovereignty"
      success_metric: "zero PII exfiltration"
    - role: "CISO"
      concern: "network isolation"
      success_metric: "no external API calls from GPU cluster"
    - role: "CDO"
      concern: "customer PII handling"
      success_metric: "100% APP-compliant data flows"
    - role: "Postmaster General"
      concern: "service continuity"
      success_metric: "zero holiday-period outage"
  success_criteria:
    - metric: "inference_latency_p95"
      target_ms: 1500
    - metric: "model_accuracy"
      target_percent: 92.5
    - metric: "system_availability"
      target_percent: 99.9
  regulatory_controls: ["Privacy Act 1988 (Cth) APPs", "APP-11 data security", "ASD Essential Eight", "AU data sovereignty"]
  risk_profile:
    - risk: "Legacy postal IT integration"
      mitigation: "Pre-build integration test harness in Sprint 1"
    - risk: "Customer PII data sovereignty"
      mitigation: "Hybrid, AU-resident GPU cluster"
    - risk: "GPU procurement delay"
      mitigation: "Pre-order hardware at sprint 0"
  deployment:
    topology: "network-isolated"
```

### 3.2 Stakeholder Map

| Role | Concern | Success Metric |
|------|---------|----------------|
| CIO | Data sovereignty | Zero PII exfiltration |
| CISO | Network isolation | No external API calls from GPU cluster |
| CDO | Customer PII handling | 100% APP-compliant data flows |
| Postmaster General | Service continuity | Zero holiday-period outage |

### 3.3 Regulatory Baseline

Jurisdiction **AU** maps to: Privacy Act 1988 (Cth) Australian Privacy
Principles, APP-11 data security, ASD Essential Eight, and Australian data
sovereignty requirements.

### 3.4 Sprint 0 Gate (Go/No-Go)

- [ ] `vision.yaml` passes schema validation (`schemas/vision.json`)
- [ ] All stakeholders have signed off on scope
- [ ] Budget (AUD 1,500,000) and timeline (12 weeks) confirmed
- [ ] Regulatory baseline identified (AU -> controls mapping)
- [ ] Handoff criteria to Sprint 1 documented

---

## 4. Sprint 1: Business + Data Architecture (ADM-B + C partial)

**Duration:** 2 weeks
**Goal:** Capabilities mapped, data flows defined, compliance requirements
embedded in every data asset.

- Capability definition: current vs target gap for customer-service AI.
- Data asset inventory: classification (regulated), volume, retention, AES-256
  encryption for all customer PII assets.
- Data flows: source -> destination with transformation and APP compliance
  controls on every flow.
- Application component mapping: RAG pipeline / agent workflow components with
  SLAs.

**Deliverables:** `business-architecture.yaml`, `data-architecture.yaml`,
`capability-gap-analysis.md`.

**Sprint 1 Gate:** All data assets classified and encrypted; every data flow
has compliance controls; capability gaps quantified; AI Safety Architect
sign-off on data architecture.

---

## 5. Sprint 2: Technology Architecture (ADM-C + D)

**Duration:** 2 weeks
**Goal:** Technology standards locked, infrastructure topology defined,
monitoring stack specified.

- Technology standards: model serving (SGLang primary, vLLM fallback), vector
  store (Qdrant), database (PostgreSQL 16 + pgvector).
- Infrastructure: AU-resident hybrid GPU cluster, network-isolated topology,
  whitelist-only egress to satisfy CISO.
- Monitoring stack: Prometheus + Grafana + DCGM, 90-day retention.
- Architecture freeze: lock selections; change via change request.

**Deliverables:** `technology-architecture.yaml`, `data-flow-diagram.mmd`,
`tech-stack-compliance.md`.

**Sprint 2 Gate:** Stack validates against AU compliance; sizing supports
Sprint 0 success criteria; monitoring covers all SLA metrics; network topology
satisfies isolation; freeze documented.

---

## 6. Sprint 3: Implementation Wave (ADM-E + F)

**Duration:** 2 weeks
**Goal:** Work packages defined, migration strategy selected, risk register
populated. Ready for Founding Engineer to execute.

- Work packages: infrastructure (GPU cluster, model serving), data pipeline
  (document ingestion), application (RAG + agent orchestration).
- Migration strategy: incremental with parallel run for customer-facing
  services; rollback trigger `p95_latency > 5s for 10 minutes`.
- Risk register: all Sprint 0 risks have owners and mitigations.

**Deliverables:** `implementation-strategy.yaml`, `migration-plan.md`,
`risk-register.md`.

**Sprint 3 Gate:** All work packages have owners and effort estimates; wave
dependencies resolved; migration strategy selected with rollback criteria;
risk register complete; blueprint package delivered.

---

## 7. Sprint 4+: Continuous Governance (ADM-G + H)

**Duration:** Ongoing (bi-weekly during implementation, monthly post-deploy).

**Governance cadence:**

| Frequency | Activity | Owner |
|-----------|----------|-------|
| Bi-weekly | Compliance checklist review | Enterprise Architecture Lead |
| Weekly | Performance metrics review | Founding Engineer |
| Monthly | Architecture fitness assessment | EA Lead + AI Safety Architect |
| Quarterly | Stakeholder architecture review | Postmaster General + stakeholders |
| Ad-hoc | Change request processing | Enterprise Architecture Lead |

**Deliverables:** `governance-report.yaml`, `change-request.yaml`,
`performance-baseline.csv`, `architecture-health.md`.

---

## 8. Sprint-to-Schema Traceability

| Sprint | Phase | Primary Schema |
|--------|-------|----------------|
| 0 | ADM-P + A | `schemas/vision.json` |
| 1 | ADM-B + C (data) | `schemas/business-architecture.json`, `schemas/data-architecture.json` |
| 2 | ADM-C (tech) + D | `schemas/technology-architecture.json` |
| 3 | ADM-E + F | `schemas/implementation-strategy.json` |
| 4+ | ADM-G + H | `schemas/compliance-mapping.json` |

---

## 9. Quality Gate

All **Common Checks** from `references/quality-checklist.md` verified before
write: Document Control complete (14 fields), Document ID follows
`ARC-001-OAAL-v1.0`, classification PUBLIC set, status DRAFT set, revision
history present, generation footer present, clean markdown, consistent tables,
proper heading hierarchy. No MANDATORY inputs were skipped, so no TBD markers
are present.

---

> **Generated by**: ArcKit `/arckit:oaa-adm-lite` command
> **Generated on**: 2026-09-01 16:10 AEST
> **ArcKit Version**: 6.7.5
> **Project**: Australian Post Digital Transformation (Project 001)
> **AI Model**: Claude Sonnet 5 (session default)
> **Generation Context**: O-AA ADM Lite template + template-driven intake answers (.arckit/intake/oaa-adm-lite.json)
