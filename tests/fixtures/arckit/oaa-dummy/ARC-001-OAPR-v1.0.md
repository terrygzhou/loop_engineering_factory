# Agile Product Architecture

| Document ID | ARC-001-OAPR-v1.0 |
|-------------|-------------------|
| **Document Type** | Agile Product Architecture (O-AA) |
| **Project** | test-oaa-dummy (Project 001) |
| **Classification** | OFFICIAL |
| **Status** | DRAFT |
| **Version** | 1.0 |
| **Created Date** | 2026-02-24 |
| **Last Modified** | 2026-02-24 |
| **Review Date** | 2026-03-24 |
| **Owner** | [PENDING] |
| **Reviewed By** | [PENDING] |
| **Approved By** | [PENDING] |
| **Distribution** | Product Team, Architecture Team, Engineering Team, Compliance |

## Revision History

| Version | Date       | Author      | Changes                                      | Approved By | Approval Date |
|---------|------------|-------------|----------------------------------------------|-------------|---------------|
| 1.0     | 2026-02-24 | ArcKit AI   | Initial creation from `$arckit-product-architecture` command | [PENDING]   | [PENDING]     |

---

## 1. Product Mission and Outcome

### 1.1 Product Mission Statement

```text
Core Platform: Cloud-native, scalable platform that replaces legacy monolithic components to enable 40% transaction growth with 30% cost reduction while delivering 99.95% availability and WCAG 2.1 AA compliant user experience.
```

**O-AA Axiom 15 — Project to Product Shift**: teams deliver products, not projects — the Core Platform is the organizing principle for the team, backlog, and architecture. Not projects, not capabilities, not services.

### 1.2 Product Outcome

| Dimension | Target | Measurement |
|---|---|---|
| **Value** | 30% reduction in infrastructure and licensing costs | Financial audit: $10M → $7M annual IT spend |
| **Outcome** | 40% increase in concurrent transaction capacity | Load testing: 10,000 → 14,000 concurrent sessions |
| **Experience** | 15-point improvement in customer satisfaction | CSAT survey: 65 → 80 score within 6 months |
| **Adoption** | 100% of target users migrated within 12 months | Migration tracker: zero data loss, full lineage |

### 1.3 Product Principles

1. **Principle 1: Product-Centric Architecture** — The Core Platform is the organizing principle for all team decisions, backlog items, and architecture evolution. Every technical decision traces to platform outcomes.

2. **Principle 2: Outcome-Driven Design** — Architecture decisions are measured by business outcomes (cost, capacity, experience, adoption), not document production or compliance checkboxes.

3. **Principle 3: Embedded Compliance** — Security, privacy, and regulatory requirements are first-class backlog items, not bolted-on afterthoughts. Compliance is validated per sprint.

4. **Principle 4: Permanent Cross-Functional Teams** — The Core Platform team is permanent, not temporary. Team owns the product end-to-end across its lifecycle.

5. **Principle 5: Backlog-Driven Architecture** — Architecture evolves through the product backlog, not separate architecture workstreams. Architecture items carry compliance metadata.

---

## 2. Cross-Functional Team Composition

### 2.1 Team Structure

O-AA mandates permanent, cross-functional teams (not temporary project teams). The Core Platform team owns the product end-to-end.

```yaml
# team.yaml — Core Platform team composition
product:
  name: "Core Platform"
  owner: "Product Director (SH-05)"
  mission: "Cloud-native platform enabling 40% transaction growth with 30% cost reduction"

team:
  roles:

    - role: "Product Owner"
      name: "Product Director"
      responsibility: "Value prioritization, backlog ownership, stakeholder alignment"

    - role: "Architect"
      name: "Lead Architect"
      responsibility: "Architecture guardrails, technical decisions, compliance mapping"

    - role: "Lead Engineer"
      name: "Engineering Manager"
      responsibility: "Implementation, code quality, CI/CD pipeline ownership"

    - role: "AI Safety Engineer"
      name: "Security Lead"
      responsibility: "Zero-trust architecture, data governance, regulatory compliance"

    - role: "DevOps Engineer"
      name: "DevOps Lead"
      responsibility: "Infrastructure as code, deployment automation, observability"

    - role: "QA Engineer"
      name: "QA Lead"
      responsibility: "E2E testing, acceptance criteria validation, performance testing"

  cadence:
    sprint_weeks: 2
    architecture_review: "Each sprint planning + retrospective"
    compliance_review: "Monthly automated scan + quarterly audit"
    demo: "End of each sprint"
    stakeholder_sync: "Bi-weekly with steering committee"

```text

### 2.2 Architect Role in the Team

The architect is **embedded in the delivery team**, not a centralized governance function.

| Responsibility | Mode | Artifact |
|---|---|---|
| Define architecture guardrails | Upfront + continuous | Architecture decision records (ADRs) |
| Review technical decisions | Sprint-by-sprint | Sprint architecture checklist |
| Maintain compliance mapping | Automated + manual review | Compliance matrix per feature |
| Architecture evolution | Release planning | Release architecture roadmap |
| Cross-product alignment | Architecture forum | Quarterly cross-product sync |

### 2.3 Stakeholder Alignment

| Stakeholder | Role | Engagement | Key Outcome |
|---|---|---|---|
| SH-01 (CFO) | Executive Sponsor | Monthly ROI reviews | O-1: 30% cost reduction |
| SH-02 (COO) | Operations Owner | Weekly metrics sync | O-2: 40% capacity increase |
| SH-03 (CTO) | Technology Sponsor | Bi-weekly tech syncs | O-3: 2-week deployment cycle |
| SH-04 (CISO) | Security Owner | Sprint security reviews | O-6: Zero critical vulnerabilities |
| SH-05 (Product) | Product Owner | Sprint planning | O-7: 15-point CSAT improvement |
| SH-06 (Ops) | Operations Lead | Daily stand-ups | O-4: 99.95% availability |
| SH-07 (CXO) | Experience Owner | UX review sessions | O-5: WCAG 2.1 AA compliance |
| SH-12 (Comp) | Compliance Officer | Quarterly audits | O-10: 100% data migration |

---

## 3. Product Backlog with Architecture Items

### 3.1 Backlog Structure

Architecture items are first-class backlog items, not afterthoughts. Each backlog item carries architecture metadata and compliance requirements.

```yaml
# backlog.yaml — Core Platform product backlog
product: "Core Platform"
sprint: "Sprint 1 (Foundation)"

architecture_items:

  - id: "ARCH-001"
    title: "Cloud-native infrastructure deployment"
    type: "infrastructure"
    priority: "critical"
    sprint: 1
    description: "Deploy multi-AZ cloud infrastructure with auto-scaling policies"
    acceptance_criteria:

      - "Supports 10,000+ concurrent sessions with horizontal scaling"

      - "Auto-scaling policies add/remove instances based on CPU/memory metrics"

      - "Multi-AZ deployment with automated failover within 15 minutes"
    compliance:

      - regulation: "NFR-A-001"
        control: "availability_99.95"
        status: "required"

      - regulation: "NFR-SC-001"
        control: "horizontal_scaling"
        status: "required"
    estimation:
      story_points: 13
      risk: "high"
    decisions:

      - adr: "ADR-001"
        choice: "Multi-AZ active-passive DR"
        rationale: "Balances cost (BR-001) and resilience (NFR-A-002) per RC-002"

  - id: "ARCH-002"
    title: "Zero-trust security architecture"
    type: "security"
    priority: "critical"
    sprint: 1
    description: "Implement identity-centric controls with OIDC integration and RBAC"
    acceptance_criteria:

      - "Enterprise IdP integration via OIDC with token exchange"

      - "RBAC dashboard with role assignment and visibility rules"

      - "TLS 1.2+ encryption for all data in transit"

      - "AES-256 encryption for all data at rest"
    compliance:

      - regulation: "NFR-S-001"
        control: "tls_1.2_plus"
        status: "required"

      - regulation: "NFR-S-002"
        control: "aes_256_encryption"
        status: "required"

      - regulation: "FR-001"
        control: "sso_mfa"
        status: "required"
    estimation:
      story_points: 13
      risk: "high"
    decisions: []

  - id: "ARCH-003"
    title: "Event-driven integration backbone"
    type: "integration"
    priority: "high"
    sprint: 2
    description: "Deploy Kafka/Pulsar event bus for asynchronous processing"
    acceptance_criteria:

      - "Consumer group offsets tracked with schema registry validation"

      - "Dead-letter queues configured for failed messages"

      - "Message ordering and deduplication handled where required"
    compliance:

      - regulation: "FR-004"
        control: "async_event_processing"
        status: "required"

      - regulation: "INT-003"
        control: "event_bus_integration"
        status: "required"
    estimation:
      story_points: 8
      risk: "medium"
    decisions: []

  - id: "ARCH-004"
    title: "Observability and audit logging pipeline"
    type: "cross_cutting"
    priority: "high"
    sprint: 2
    description: "Implement Prometheus + Grafana monitoring with immutable audit logs"
    acceptance_criteria:

      - "All service health endpoints instrumented with correlation IDs"

      - "Alerting rules for latency, error rate, and availability metrics"

      - "Immutable audit logs capturing user, timestamp, action, before/after values"
    compliance:

      - regulation: "FR-005"
        control: "automated_audit_logs"
        status: "required"

      - regulation: "NFR-C-001"
        control: "data_retention"
        status: "required"
    estimation:
      story_points: 8
      risk: "medium"
    decisions: []

  - id: "ARCH-005"
    title: "API gateway with versioning and contract testing"
    type: "integration"
    priority: "high"
    sprint: 3
    description: "Deploy API gateway with OpenAPI 3.0 specs and contract testing"
    acceptance_criteria:

      - "API gateway publishes OpenAPI 3.0 documentation"

      - "Contract tests pass against spec on every PR"

      - "Versioned routes (/v1/, /v2/) function independently"
    compliance:

      - regulation: "FR-006"
        control: "api_versioning"
        status: "required"

      - regulation: "INT-002"
        control: "openapi_3.0"
        status: "required"
    estimation:
      story_points: 5
      risk: "low"
    decisions: []

functional_items:

  - id: "FEAT-001"
    title: "User authentication and RBAC dashboard"
    type: "feature"
    priority: "critical"
    sprint: 1
    architecture_dependency: ["ARCH-002"]
    compliance:

      - regulation: "FR-001"
        control: "sso_mfa"
        status: "required"

      - regulation: "FR-002"
        control: "rbac_dashboard"
        status: "required"

  - id: "FEAT-002"
    title: "Data search, filter, and export capability"
    type: "feature"
    priority: "high"
    sprint: 3
    architecture_dependency: ["ARCH-001", "ARCH-003"]
    compliance:

      - regulation: "FR-003"
        control: "search_export"
        status: "required"

  - id: "FEAT-003"
    title: "Real-time notifications for status changes"
    type: "feature"
    priority: "medium"
    sprint: 4
    architecture_dependency: ["ARCH-003", "ARCH-004"]
    compliance:

      - regulation: "FR-008"
        control: "real_time_notifications"
        status: "required"

  - id: "FEAT-004"
    title: "Responsive accessible UI (WCAG 2.0 AA baseline)"
    type: "feature"
    priority: "high"
    sprint: 2
    architecture_dependency: ["ARCH-005"]
    compliance:

      - regulation: "FR-007"
        control: "wcag_2.0_aa"
        status: "required"
        notes: "WCAG 2.1 AA enhancements in Sprint 4 per RC-003"

```text

### 3.2 Architecture Item Types

| Type | Description | Example |
|---|---|---|
| **infrastructure** | Foundation infrastructure decisions | Multi-AZ deployment, auto-scaling |
| **security** | Security architecture and controls | Zero-trust, encryption, RBAC |
| **integration** | Integration patterns and protocols | Event bus, API gateway, ERP sync |
| **cross_cutting** | Concerns spanning multiple features | Observability, audit logging |
| **compliance** | Regulatory compliance implementation | Data retention, SBOM review |

---

## 4. Release Architecture Roadmap

### 4.1 Release Planning

```yaml
# roadmap.yaml — Core Platform release architecture roadmap
product: "Core Platform"
versioning: "semantic"  # semver

releases:

  - version: "0.1.0"
    name: "Foundation"
    target_date: "2026-08-24"
    outcome: "Core platform operational with compliance baseline and 2-week deployment cycles"
    architecture_scope:

      - "Multi-AZ cloud infrastructure with auto-scaling"

      - "Zero-trust security with OIDC integration and RBAC"

      - "Event-driven integration backbone (Kafka/Pulsar)"

      - "Observability and audit logging pipeline"

      - "API gateway with versioning and contract testing"
    features:

      - "User authentication and RBAC dashboard"

      - "Data search, filter, and export capability"

      - "Responsive accessible UI (WCAG 2.0 AA baseline)"
    compliance_milestones:

      - milestone: "encryption_at_rest"
        regulation: "NFR-S-002"
        status: "implemented"

      - milestone: "encryption_in_transit"
        regulation: "NFR-S-001"
        status: "implemented"

      - milestone: "audit_logging"
        regulation: "FR-005"
        status: "implemented"

      - milestone: "sso_mfa"
        regulation: "FR-001"
        status: "implemented"

  - version: "0.2.0"
    name: "Scale & Accessibility"
    target_date: "2027-02-24"
    outcome: "40% transaction capacity with WCAG 2.1 AA compliance and data migration complete"
    architecture_scope:

      - "Database read replicas for analytics workloads"

      - "Data archival and tiered storage"

      - "WCAG 2.1 AA enhancements"

      - "Legacy ERP master data synchronization"
    features:

      - "Real-time notifications for status changes"

      - "WCAG 2.1 AA accessibility enhancements"

      - "Data archival and retrieval capability"
    compliance_milestones:

      - milestone: "wcag_2.1_aa"
        regulation: "FR-007"
        status: "implemented"

      - milestone: "data_lineage"
        regulation: "DR-004"
        status: "implemented"

      - milestone: "erp_sync"
        regulation: "INT-004"
        status: "implemented"

  - version: "1.0.0"
    name: "Production Readiness"
    target_date: "2027-08-24"
    outcome: "GA release with 99.95% availability, positive ROI, and full compliance coverage"
    architecture_scope:

      - "Production-grade resilience with chaos engineering"

      - "Disaster recovery with RTO ≤15 mins, RPO ≤5 mins"

      - "Performance baseline validation under peak load"

      - "Full compliance audit and SBOM verification"
    compliance_milestones:

      - milestone: "full_compliance_audit"
        regulation: "All applicable"
        status: "implemented"

      - milestone: "sbom_review"
        regulation: "NFR-C-002"
        status: "implemented"

architecture_evolution:

  - phase: "Foundation"
    focus: "Infrastructure, security, and core capabilities"
    principle: "Right-sized, not over-engineered"

  - phase: "Scale"
    focus: "Capacity scaling, accessibility, and data migration"
    principle: "Automate before you scale"

  - phase: "Mature"
    focus: "Production resilience, performance optimization, and compliance"
    principle: "Observability drives architecture"

```text

### 4.2 Release Gate Criteria

| Gate | Criteria | Validator |
|---|---|---|
| **Sprint Review** | Architecture items completed, compliance items green | Sprint architecture checklist |
| **Release Candidate** | All critical architecture items done, no P1 compliance gaps | Release compliance scan |
| **GA Release** | Full compliance audit, performance baseline met, 99.95% availability | Governance report |

---

## 5. Value Stream Mapping

### 5.1 Value Stream Definition

```yaml
# value_streams.yaml — Core Platform value stream mapping
product: "Core Platform"

value_streams:

  - id: "VS-001"
    name: "Requirement to deployment"
    description: "End-to-end flow from backlog item to production deployment"
    steps:

      - name: "Backlog item created"
        owner: "Product Owner"
        duration_hours: 0
        type: "event"

      - name: "Architecture review"
        owner: "Architect"
        duration_hours: 4
        type: "analysis"
        output: "Architecture decision or guardrail confirmation"

      - name: "Implementation"
        owner: "Engineering team"
        duration_hours: 40
        type: "work"
        output: "Code, tests, documentation"

      - name: "Architecture validation"
        owner: "Architect + QA"
        duration_hours: 2
        type: "verification"
        output: "Architecture sign-off"

      - name: "Compliance scan"
        owner: "Automated pipeline"
        duration_hours: 0.5
        type: "verification"
        output: "Compliance report"

      - name: "Deployment"
        owner: "DevOps"
        duration_hours: 1
        type: "execution"
        output: "Production deployment"
    total_touch_time_hours: 13.5
    total_wait_time_hours: 12
    total_lead_time_hours: 25.5
    efficiency_percent: 52.9

  - id: "VS-002"
    name: "User request to response"
    description: "Runtime value stream — user request through platform response delivery"
    steps:

      - name: "Request received"
        duration_ms: 0
        system: "API Gateway"

      - name: "Authentication"
        duration_ms: 50
        system: "Auth service (OIDC)"

      - name: "Request processing"
        duration_ms: 100
        system: "Core platform services"

      - name: "Data retrieval"
        duration_ms: 150
        system: "Database (with read replicas)"

      - name: "Response formatting"
        duration_ms: 50
        system: "API services"

      - name: "Response delivery"
        duration_ms: 50
        system: "API Gateway"
    target_latency_ms: 200
    measured_latency_ms: 400
    compliance_controls:

      - control: "input_validation"
        step: "Request processing"
        regulation: "NFR-S-001"

      - control: "audit_logging"
        step: "Data retrieval"
        regulation: "FR-005"

```text

### 5.2 Value Stream Metrics

| Metric | Target | Current | Gap |
|---|---|---|---|
| Lead time (requirement → deploy) | < 2 sprints | 3 sprints | -1 sprint |
| Deployment frequency | 2x per sprint | 1x per sprint | +1x |
| Architecture review cycle | < 4 hours | 6 hours | -2 hours |
| Compliance scan time | < 30 minutes | 45 minutes | -15 minutes |
| Value stream efficiency | > 60% | 52.9% | +7.1% |
| API response time (p95) | < 200ms | 400ms | -200ms |

---

## 6. Embedded Compliance Per Feature

### 6.1 Compliance Integration Approach

O-AA principle: Compliance is embedded in every feature, not bolted on at the end. Each backlog item carries its compliance requirements.

```yaml
# compliance.yaml — embedded compliance per feature
product: "Core Platform"
jurisdiction: "AU"  # AU | EU | APAC | US | multi

regulations:

  - id: "NFR-S-001"
    name: "TLS 1.2+ encryption for data in transit"
    scope: "All data transmission features"
    controls:

      - id: "tls_1.2_plus"
        description: "TLS 1.2 or higher for all data in transit"
        features: ["ARCH-002", "ARCH-005"]
        status: "implemented"

  - id: "NFR-S-002"
    name: "AES-256 encryption for data at rest"
    scope: "All data storage features"
    controls:

      - id: "aes_256_encryption"
        description: "AES-256 encryption for stored data with enterprise KMS"
        features: ["ARCH-001", "ARCH-002"]
        status: "implemented"

  - id: "FR-005"
    name: "Automated audit logging for data modifications"
    scope: "All data modification features"
    controls:

      - id: "audit_logging"
        description: "Immutable audit logs capturing user, timestamp, action, before/after"
        features: ["ARCH-004"]
        status: "implemented"

  - id: "FR-007"
    name: "WCAG 2.1 AA accessibility compliance"
    scope: "All user interface features"
    controls:

      - id: "wcag_2.0_aa"
        description: "WCAG 2.0 AA baseline for MVP launch"
        features: ["FEAT-004"]
        status: "implemented"

      - id: "wcag_2.1_aa"
        description: "WCAG 2.1 AA enhancements for Sprint 4"
        features: []
        status: "planned"
        notes: "Per RC-003 compromise with Product Director"

feature_compliance_matrix:

  - feature: "FEAT-001"
    name: "User authentication and RBAC dashboard"
    compliance:

      - regulation: "FR-001"
        control: "sso_mfa"
        status: "implemented"
        evidence: "OIDC integration with MFA challenge for new devices"

      - regulation: "FR-002"
        control: "rbac_dashboard"
        status: "implemented"
        evidence: "Admin role assignment with UI visibility enforcement"

  - feature: "FEAT-002"
    name: "Data search, filter, and export capability"
    compliance:

      - regulation: "FR-003"
        control: "search_export"
        status: "planned"
        evidence: ""
        notes: "Search < 2 seconds, CSV/PDF export without data loss"

  - feature: "FEAT-004"
    name: "Responsive accessible UI"
    compliance:

      - regulation: "FR-007"
        control: "wcag_2.0_aa"
        status: "implemented"
        evidence: "WCAG 2.0 AA compliance verified in staging"

      - regulation: "FR-007"
        control: "wcag_2.1_aa"
        status: "planned"
        evidence: ""
        notes: "WCAG 2.1 AA enhancements scheduled for Sprint 4"

compliance_gaps:

  - gap: "WCAG 2.1 AA not yet implemented"
    impact: "Cannot demonstrate full accessibility compliance"
    remediation: "FEAT-004 Sprint 4 — WCAG 2.1 AA enhancements"
    target_sprint: 4
    risk: "medium"

  - gap: "Legacy ERP synchronization not yet implemented"
    impact: "Data consistency gap during transition period"
    remediation: "ARCH-006 — ERP sync with conflict resolution"
    target_sprint: 6
    risk: "medium"

```text

### 6.2 Compliance-as-Code Integration

| Integration Point | Tool | Frequency |
|---|---|---|
| Pre-commit hooks | `pre-commit` + compliance scanner | Every commit |
| CI pipeline | Automated compliance validation | Every PR |
| Sprint review | Compliance matrix review | Every sprint |
| Release gate | Full compliance audit | Every release |
| Quarterly audit | External compliance review | Quarterly |

---

## 7. Architecture Guardrails

### 7.1 Non-Negotiable Constraints

| Constraint | Requirement | Rationale | Validation |
|---|---|---|---|
| **Performance** | API response times < 200ms for 95th percentile | NFR-P-001: Ensures responsive user experience | APM dashboards, load testing |
| **Security** | TLS 1.2+ for transit, AES-256 for rest | NFR-S-001, NFR-S-002: Protects against interception and breaches | SSL Labs scan, storage audit |
| **Availability** | 99.95% monthly availability | NFR-A-001: Business continuity requirement | Uptime monitoring, failover tests |
| **Scalability** | Horizontal scaling for stateless services | NFR-SC-001: Cost-efficient capacity management | Auto-scaling policies, stress testing |
| **Compliance** | Automated vulnerability scanning in CI/CD | NFR-S-003: Shifts security left | SAST/DAST reports, merge gates |

### 7.2 Technology Standards

| Category | Standard | Rationale |
|---|---|---|
| **Authentication** | OAuth 2.0 / OIDC | INT-001: Enterprise IdP integration |
| **APIs** | RESTful with OpenAPI 3.0 | INT-002: Standardized consumption |
| **Event Processing** | Kafka/Pulsar | INT-003: Asynchronous communication |
| **Encryption** | TLS 1.2+, AES-256 | NFR-S-001, NFR-S-002: Security baseline |
| **Monitoring** | Prometheus + Grafana | FR-005: Observability and audit logging |
| **Database** | Read replicas for analytics | NFR-SC-002: Prevents analytical impact |

### 7.3 Anti-Patterns and Forbidden Approaches

| Anti-Pattern | Forbidden Approach | Rationale | Alternative |
|---|---|---|---|
| **Monolithic architecture** | Single deployable unit with tight coupling | Violates PRIN: Loose Coupling (4.1) | Microservices with API gateway |
| **Synchronous blocking calls** | Direct service-to-service synchronous calls | Violates PRIN: Asynchronous Communication (4.3) | Event-driven architecture |
| **Manual deployments** | Click-ops deployment processes | Violates PRIN: Automation (6.1) | CI/CD pipeline with IaC |
| **Shared database schemas** | Services sharing database tables | Violates PRIN: Loose Coupling (4.1) | Service-owned databases |
| **Late security scanning** | Security scanning only before production | Violates PRIN: Security by Design (2.4) | Shift-left security in CI/CD |
| **Undocumented APIs** | Ad-hoc endpoints without specs | Violates PRIN: Standard Interfaces (4.2) | OpenAPI 3.0 with contract testing |

---

## 8. Product Architecture Diagram

### 8.1 C4 Component Diagram

```mermaid
C4Context
    title Core Platform - System Context

    Person(user, "End User", "Platform users requiring fast, reliable access")
    Person(admin, "Administrator", "Users managing roles and system configuration")
    Person(ops, "Operations Team", "Team monitoring system health and responding to incidents")

    System_Boundary(core_platform, "Core Platform") {
        System(api_gateway, "API Gateway", "Routes requests, enforces security, versioning")
        System(auth_service, "Auth Service", "OIDC integration, SSO, MFA, RBAC")
        System(core_services, "Core Services", "Business logic, search, filter, export")
        System(event_bus, "Event Bus", "Kafka/Pulsar for asynchronous processing")
        System(database, "Database", "Primary DB with read replicas for analytics")
        System(monitoring, "Observability Stack", "Prometheus + Grafana, audit logging")
    }

    System_Ext(enterprise_idp, "Enterprise IdP", "Centralized authentication provider")
    System_Ext(legacy_erp, "Legacy ERP", "Master data source during transition")
    System_Ext(cloud_infra, "Cloud Infrastructure", "Multi-AZ deployment with auto-scaling")

    Rel(user, api_gateway, "HTTPS requests", "TLS 1.2+")
    Rel(admin, auth_service, "Manage roles", "RBAC dashboard")
    Rel(ops, monitoring, "Monitor health", "Metrics, logs, traces")

    Rel(api_gateway, auth_service, "Validate tokens", "OIDC")
    Rel(api_gateway, core_services, "Route requests", "REST/JSON")
    Rel(core_services, database, "Read/write data", "Encrypted")
    Rel(core_services, event_bus, "Publish/consume events", "Async")
    Rel(event_bus, core_services, "Process background tasks", "Async")

    Rel(auth_service, enterprise_idp, "Token exchange", "OIDC")
    Rel(core_services, legacy_erp, "Master data sync", "Bidirectional")
    Rel(monitoring, database, "Collect metrics", "Read-only")

    Rel_Back(cloud_infra, core_platform, "Hosts and scales", "Multi-AZ")

    UpdateLayoutConfig($c4ShapeInRow="3", $c4BoundaryInRow="1")
```

### 8.2 Integration Points

| Integration | Protocol | Security | Compliance |
|---|---|---|---|
| Enterprise IdP | OIDC | TLS 1.2+, token validation | FR-001, INT-001 |
| Legacy ERP | REST/JSON | TLS 1.2+, API keys | INT-004, DR-001 |
| Event Bus | Kafka/Pulsar | TLS 1.2+, schema registry | FR-004, INT-003 |
| API Consumers | REST/JSON | TLS 1.2+, OAuth 2.0 | FR-006, INT-002 |
| Monitoring | Prometheus | mTLS, RBAC | FR-005, NFR-C-001 |

### 8.3 Data Flow and API Boundaries

```
User Request → API Gateway (TLS 1.2+) → Auth Service (OIDC validation)
    → Core Services (business logic) → Database (AES-256 encrypted)
    → Event Bus (async processing) → Background Workers
    → Audit Logs (immutable storage) → Monitoring Stack
```

---

## 9. Template Usage Guide

### When to Use This Template

- **Product-focused architecture:** The work targets the Core Platform product, not enterprise-wide architecture
- **Agile team delivery:** The team works in 2-week sprints with continuous architecture evolution
- **Embedded compliance:** Regulatory requirements are part of the feature backlog, not a separate process
- **Outcome-driven:** Architecture decisions measured by product outcomes (cost, capacity, experience, adoption)

### When NOT to Use This Template

- **Enterprise-wide transformation:** Use the TOGAF ADM workflow for enterprise scope
- **Regulatory compliance project:** Use the compliance validation pipeline as primary
- **Infrastructure-only work:** Use the technology architecture template from Phase C

### Integration with TOGAF ADM

| Product Architecture Element | TOGAF ADM Phase | Relationship |
|---|---|---|
| Product mission | Phase A (Vision) | Refines enterprise vision for the Core Platform |
| Team composition | Phase B (Business) | Product-centric team vs capability-centric org |
| Backlog architecture items | Phase C (Information Systems) | Incremental architecture evolution |
| Release roadmap | Phase E+F (Opportunities + Migration) | Time-boxed delivery of architecture |
| Value streams | Phase B (Business) | Product value delivery focus |
| Embedded compliance | Phase G (Governance) | Continuous vs phase-gate compliance |

---

## 10. References

- O-AA Standard (C208): The Open Group Agile Architecture — Ch. 14: Product Architecture (certification syllabus domain 7)
- Architecture Principles (ARC-001-PRIN-v1.0): Foundational governance and design constraints
- Business and Technical Requirements (ARC-001-REQ-v1.0): Requirements aligned to product outcomes
- Stakeholder Drivers, Goals & Outcomes (ARC-001-STKE-v1.0): Stakeholder alignment and traceability

---

**Generated by**: ArcKit `$arckit-product-architecture` command
**Generated on**: 2026-02-24
**ArcKit Version**: 1.0.0
**Project**: test-oaa-dummy (Project 001)
**AI Model**: ArcKit AI
**Generation Context**: Generated from enterprise architecture principles, business requirements, and stakeholder analysis. Product-centric, outcome-driven, team-led approach per O-AA Ch. 14 (Product Architecture).
```
