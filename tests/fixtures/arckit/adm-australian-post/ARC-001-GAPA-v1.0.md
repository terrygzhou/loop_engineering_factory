---
title: "Gap Analysis"
docType: GAPA
templateVersion: "1.0"
---

# Gap Analysis

## Document Control

| Field | Value |
|-------|-------|
| Document ID | `ARC-001-GAPA-v1.0` |
| Document Type | Gap Analysis (BPCM → TOGAF ADM Phase B/C bridge) |
| Project | Australian Post Digital Transformation |
| Owner | Terry Nguyen, Enterprise Architect |
| Classification | OFFICIAL |
| Status | DRAFT |
| Severity Weighting | BALANCED |
| Created | 2026-09-02 |
| Review Date | 2026-10-02 |

### Revision History

| Version | Date | Author | Description | Reviewer | Approver |
|---------|------|--------|-------------|----------|----------|
| 1.0 | 2026-09-02 | ArcKit AI | Initial creation from `/arckit:gap-analysis` command | CISO | Postmaster General |

---

## 1. Capability Gap Matrix

| Capability | Current | Target | Gap Size | Urgency | Severity (Size×Urgency) | Workstream |
|------------|---------|--------|----------|---------|--------------------------|------------|
| C1.0: Customer Digital Experience | L2 | L4 | Medium | High | High | WS-001 |
| C2.0: Logistics Data & Insights | L1 | L4 | Large | High | Critical | WS-002 |
| C3.0: Data Governance & Sovereignty | L2 | L4 | Medium | High | High | WS-002 |
| C4.0: Service Operations & Resilience | L2 | L4 | Medium | Medium | Medium | WS-001 |
| C5.0: Enterprise Architecture Governance | L3 | L4 | Small | Low | Low | — |

## 4. Gap-to-Risk Mapping

| Gap | Capability | Associated Risk | Risk Category | Impact | Mitigation |
|-----|-----------|-----------------|---------------|--------|------------|
| G-001 | C2.0 | Cost-per-event reporting stays manual during cut-over | Operational | High | Dual-write validation and reconciliation scripts (SC-2) |
| G-002 | C3.0 | PII remains in legacy stores past the AU-residency deadline | Compliance | High | APP-11 data-residency controls enforced before cutover |
| G-003 | C1.0 | Tracking accuracy misses the 98% target, eroding customer trust | Strategic | Medium | Event-driven status pipeline with regression KPIs |

## 5. Assumptions & Constraints

### Assumptions

1. L1 maturity estimates from BPCM are valid as planning inputs.
2. The 12-month cut-over window holds, including the holiday outage freeze.

### Constraints

1. **Budget**: FY 2025/26 engagement capped at $12M AUD.
2. **Timeline**: No-incident cutover inside the 12-month window.
3. **Compliance**: PII processed AU-resident only (Privacy Act 1988 APPs, APP-11).
