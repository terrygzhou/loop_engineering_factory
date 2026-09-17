# Technology Architecture — TOGAF ADM Phase D

## Document Control

| Field | Value |
|-------|-------|
| **Document ID** | ARC-000-TECH-v1.0 |
| **Document Type** | Technology Architecture |
| **Project** | Meridian P&C Insurance Group (Project MPC, MPC-insurance) |
| **Classification** | OFFICIAL |
| **Status** | DRAFT |
| **Version** | 1.0 |
| **Created Date** | 2026-09-15 |
| **Last Modified** | 2026-09-15 |
| **Review Cycle** | Monthly during active ADM cycle |
| **Next Review Date** | 2026-10-15 |
| **Owner** | K. Whitfield, CIO / Enterprise Architecture Lead |
| **Reviewed By** | PENDING |
| **Approved By** | PENDING |
| **Distribution** | Architecture Board, IT Platform & Operations, SRE, Security & Privacy |

### Revision History

| Version | Date | Author | Changes | Approved By | Approval Date |
|---------|------|--------|---------|-------------|---------------|
| 1.0 | 2026-09-15 | ArcKit AI | Initial creation from `/arckit:technology-architecture` (case-study prefill) | PENDING | PENDING |

---

## 1. Technology Architecture Vision

The target technology state is a **single, API-first, event-driven insurance platform** on a
group cloud landing zone, replacing the fragmented on-prem + per-country-cloud estate. A
group event backbone (Kafka) and group API gateway become the integration substrate; the
unified P&C core, event-driven claims engine, unified decisioning platform, decoupled cloud
pricing engine, governed AI claims-triage (model registry + MLOps), group CDP/MDM, shared
fraud platform and regulatory data mart all run on it. The on-prem AU data centre is
retired post-migration. Security is a design property: group zero-trust, group secrets
management, and a security-reviewed API catalogue from Wave 1.

## 2. Infrastructure Architecture

### 2.1 Compute

| Layer | Technology | Capacity | Scaling | Hosting |
|-------|-----------|----------|---------|---------|
| Application Tier | Containerised services (K8s) | Scaled per SLO | Autoscale | Group landing zone |
| Data Processing | Managed compute (lakehouse, ML) | Elastic | Autoscale | Group cloud |
| AI / MLOps | Managed GPU/inference for LLM + triage | On-demand | Autoscale | Group cloud |

### 2.2 Storage

| Storage Type | Technology | Tiering | Backup |
|-------------|-----------|---------|--------|
| Object | Cloud object store | Hot→Cold | Continuous + WORM for audit |
| Database | Group CDP (identity) + claims store | Hot | PITR |
| Model store | Versioned model registry (Restricted) | Warm | Retention per model-risk policy |

### 2.3 Networking

| Component | Technology | Security |
|-----------|-----------|----------|
| Core network | Group VPC peering across 4 country regions | mTLS, private endpoints |
| Edge | Group API gateway (public) | WAF, throttling, authn |
| Inter-country | Private backbone + transit | Data-residency controls (PDPA/GDPR/NZ) |

### 2.4 Hosting Model

| Aspect | Current State | Target State | Rationale |
|--------|-------------|-------------|-----------|
| Cloud model | Per-country accounts, on-prem AU DC | 1 group landing zone (4 regions) | Convergence + residency |
| Provider | Mixed country vendors | Multi-cloud with group abstraction | Reduce lock-in |
| On-prem | AU DC (2 DCs, ~40% idle) | Decommissioned by M30 | EOL + cost |

## 3. Platform Architecture

### 3.1 Middleware

| Component | Technology | Role |
|-----------|-----------|------|
| API Gateway | Group gateway (Wave 1) | Single integration + governance point |
| Message Broker | Kafka event backbone | Event-driven claims + CDP propagation |
| Decisioning bus | Unified decisioning platform | Underwriting + claims decisions |

### 3.2 Containers & Orchestration

| Component | Technology | Management |
|-----------|-----------|-----------|
| Container Runtime | Container runtime (group) | Group-managed |
| Orchestrator | Kubernetes / managed K8s | SRE run/change/manage model |
| Service Discovery | In-cluster + gateway | Group |

### 3.3 CI/CD Pipeline

| Stage | Tool | Automation Level |
|-------|------|-----------------|
| Source Control | Git, group pipeline (replaces per-team + manual JCL) | Automated |
| Build / Test | Group CI with compliance + security scans | Automated |
| Deploy / Release | Group release train, feature-flag cutover | Automated |

### 3.4 Observability

| Capability | Tool | Metric |
|-----------|------|--------|
| Logging / Monitoring | Group SLO dashboards (replaces per-team) | SLO burn |
| APM / Tracing | Distributed tracing over event backbone | p95 latency < 200ms |

## 4. Integration Architecture

### 4.1 API Standards

| Standard | Protocol | Versioning | Governance |
|----------|----------|-----------|------------|
| REST | HTTPS | URL/version | Group API catalogue + security review |
| Event | Kafka topics, data contracts | Schema registry | CDP data contracts |

### 4.2 Messaging Patterns

| Pattern | Use Case | Technology |
|---------|----------|-----------|
| Publish/Subscribe | CDP identity resolution, claims events | Kafka |
| Event Streaming | Real-time policyholder updates | Kafka |

### 4.3 Integration Security

| Control | Mechanism |
|---------|----------|
| Authentication | Group IdP, MFA (removes legacy no-MFA on-prem apps) |
| Authorization | Zero-trust, role + data-residency |
| Secrets | Group secrets management |

## 5. Deployment Architecture

### 5.1 Environments

| Environment | Isolation | Promotion |
|-------------|-----------|-----------|
| Dev / Test / Staging / Prod | Data-residency partitioned | Group release train |

### 5.2 High Availability

| Metric | Target | Strategy |
|--------|--------|----------|
| Availability | > 99.9% claims path | Multi-AZ, failover |
| RTO / RPO | 4h / 15min | Multi-region replication |

## 6. Technology Standards

### 6.1 Approved Technology Stack

| Category | Technology | Status |
|----------|-----------|--------|
| Language | Java / Python / Go | Approved |
| Container | Kubernetes / managed K8s | Approved |
| Event | Kafka + schema registry | Approved |
| Cloud | Group landing zone (multi-cloud) | Approved |
| AI | Governed MLOps + model registry | Approved |

### 6.2 Prohibited Technologies

| Technology | Rationale | Alternative |
|-----------|-----------|-------------|
| Manual JCL batch edits | Legacy, no audit | Event-driven services |
| Spreadsheet pricing | Drift, weeks-to-change | Decoupled pricing engine |
| Per-country private clouds | No shared governance | Group landing zone |

## 7. Technology Landscape

```mermaid
C4Context
    title Technology Landscape — Meridian Target

    Person(dev, "Developer", "Group engineering")
    Person(sre, "SRE", "Run/change/manage")

    System_Boundary(lz, "Group Cloud Landing Zone (4 regions)")
        System(k8s, "Kubernetes", "Container orchestrator")
        System(kafka, "Event Backbone", "Kafka + schema registry")
        System(gw, "Group API Gateway", "Integration + governance")
        System(mreg, "Model Registry + MLOps", "Governed AI")
        System(zts, "Zero-Trust / Secrets", "Security substrate")

    System_Boundary(apps, "Application Layer")
        System(core, "Unified P&C Core", "Target")
        System(claims, "Event-Driven Claims Engine", "Target")
        System(cdp, "Group CDP / MDM", "Target")
        System(fraud, "Shared Fraud Platform", "Target")
        System(regmart, "Regulatory Data Mart", "Target")

    Rel(dev, core, "Deploys to")
    Rel(sre, k8s, "Manages")
    Rel(core, kafka, "Emits claims events")
    Rel(claims, kafka, "Consumes/emits")
    Rel(cdp, kafka, "Propagates identity")
    Rel(fraud, cdp, "Consumes signals")
    Rel(regmart, cdp, "Consumes data")
    Rel(apps, gw, "Routes via gateway")
    Rel(apps, zts, "Authenticates / secrets")
    Rel(k8s, kafka, "Hosts")
```

## 8. Traceability

| Technology Element | Source Artifact | Link | Note |
|--------------------|----------------|------|------|
| Unified core / claims | APPR: §2 | `ARC-000-APPR-v1.0.md` | Replace decision |
| Data platform | DATA: §4 | `ARC-000-DATA-v1.0.md` | CDP/lakehouse |
| Standards | PRIN: §6 | `ARC-000-PRIN-v1.0.md` | API-first / zero-trust |
| Deployment | TRANS: §3 | `ARC-000-TRANS-v1.0.md` | Wave sequencing |

## 9. Assumptions

1. A group landing zone can host all four country data-residency partitions.
2. The unified P&C core vendor/platform is selected before Phase E.
3. SRE run/change/manage model is adopted in Wave 1.

## 10. Risks

| # | Risk | Impact | Mitigation |
|---|------|--------|------------|
| 1 | Parallel-run cost during core migration | High | Feature-flag cutover; SRE run/change |
| 2 | Vendor SaaS API limits block integration | Medium | Data egress contracts |
| 3 | On-prem EOL (2028) forces rushed decom | High | M19–M30 decom track |
| 4 | Group zero-trust rollout scope creep | Medium | Wave 1 security-reviewed API catalogue |

---

**Generated by**: ArcKit `/arckit:technology-architecture` command
**Generated on**: 2026-09-15
**ArcKit Version**: 6.9.0
**Project**: Meridian P&C Insurance Group — API-First Insurance Modernisation (Project MPC, MPC-insurance)
**AI Model**: Codex via the ArcKit Codex extension v6.9.0
**Generation Context**: Synthesised from case-study/01-insurance.md §2 (as-is platforms, D6) + §3.2 target portfolio (D6). No external documents.

## PlantUML ArchiMate View

**Layer focus**: Technology

> Notation: PlantUML ArchiMate standard library — pinned `!include <archimate/Archimate>` (PlantUML 1.2026.8).
> This view is additive; the Mermaid diagram(s) above are unchanged.

```plantuml
@startuml
!include <archimate/Archimate>

title Meridian Target Technology Architecture

LAYOUT_TOP_DOWN()

' Elements
Technology_Node(LZ, "Group Cloud Landing Zone (4 regions)")
Technology_Service(GW, "Group API Gateway")
Technology_CommunicationNetwork(KAFKA, "Kafka event backbone")
Technology_Node(MREG, "Model Registry + MLOps")
Technology_Node(ZTS, "Zero-Trust / Secrets substrate")

' Relationships (realization concrete->abstract; serving/flow)
Rel_Serving(GW, LZ)
Rel_Serving(KAFKA, LZ)
Rel_Serving(MREG, LZ)
Rel_Serving(ZTS, LZ)

@enduml
```

![Meridian Target Technology Architecture (rendered SVG)](./diagrams/ARC-000-TECH.svg)

*Rendered offline from `./diagrams/ARC-000-TECH.puml` (local ArchiMate stdlib at `./diagrams/stdlib/`). The block above is the canonical `!include <archimate/Archimate>` and renders in any PlantUML server. Re-render: `java -jar plantuml.jar -tsvg ./diagrams/ARC-000-TECH.puml`.*

### PlantUML ArchiMate Companion View (Physical)

**Layer focus**: Physical

> Notation: PlantUML ArchiMate standard library — pinned `!include <archimate/Archimate>` (PlantUML 1.2026.8).
> Companion view: a separate sequenced `ARCH` document — additive to the base view above, never merged into it.

```plantuml
@startuml
!include <archimate/Archimate>

title Meridian Physical Footprint (as-is to target)

LAYOUT_TOP_DOWN()

' Companion layer elements
Physical_Facility(AUDC, "On-prem AU Data Centre (2 DCs, EOL 2028)")
Physical_Facility(COUNTRYCLOUD, "Country cloud regions (AU/NZ/UK/SG)")
Physical_DistributionNetwork(WAN, "Cross-country private backbone")
Technology_Node(LZ, "Group landing zone (target)")

' Realization/relationship edges (concrete->abstract)
Rel_Flow(AUDC, LZ)
Rel_Flow(COUNTRYCLOUD, LZ)
Rel_Flow(WAN, LZ)

@enduml
```

![Meridian Physical Footprint — companion (rendered SVG)](./diagrams/ARC-000-TECH-PHYSICAL.svg)

*Rendered offline from `./diagrams/ARC-000-TECH-PHYSICAL.puml` (local ArchiMate stdlib at `./diagrams/stdlib/`). Re-render: `java -jar plantuml.jar -tsvg ./diagrams/ARC-000-TECH-PHYSICAL.puml`.*
