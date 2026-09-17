---
title: "Transition Architecture"
docType: TRANS
templateVersion: "1.0"
---

# Transition Architecture

## Document Control

| Field | Value |
|-------|-------|
| Document ID | `ARC-001-TRANS-v1.0` |
| Document Type | Transition Architecture |
| Project | Australian Post Digital Transformation |
| Classification | OFFICIAL |
| Status | DRAFT |
| Version | 1.0 |
| Created | 2026-09-02 |
| Owner | Terry Nguyen, Enterprise Architect |

---

## 1. Transition Overview

| Architecture | Scope | Duration | Investment |
|--------------|-------|----------|------------|
| Architecture 1 (Baseline) | Current state — fragmented legacy IT, batch tracking, manual cost reconciliation | — | — |
| Architecture 2 | Wave 1 — AU-resident data platform, event-driven tracking MVP, hardening | 6 months | $5.5M |
| Architecture 3 | Wave 2 — data products, AI Q&A, measured 99.9% availability | 6 months | $6.5M |
| Target Architecture | Final state — cloud-native digital platform with governed data spine | — | — |

### Transition Waves

**Wave 1 — Foundation & Hardening** (Architecture 2)

- **Objective**: Establish the AU-resident data platform and a trustworthy event-driven tracking MVP.
- **Duration**: 2026-10-01 to 2027-03-31 (6 months)
- **Key Deliverables**:
  - AU-resident data platform live with APP-11 controls
  - Event-driven delivery status pipeline at > 98% accuracy
  - API gateway with versioning and rate limiting in production
- **Governance Gate**: Wave 1 Complete — ARB review

**Wave 2 — Data Products & Scale** (Architecture 3)

- **Objective**: Deliver cost-optimised data products and measured 99.9% availability.
- **Duration**: 2027-04-01 to 2027-09-30 (6 months)
- **Key Deliverables**:
  - Cost-per-delivery-event data product (SC-2 target: -15%)
  - AI-assisted customer Q&A within service level
  - Measured 99.9% availability with < 5 min MTTR
- **Governance Gate**: Wave 2 Complete — Steering Committee review

---

## 2. Work Packages

### WP-001: AU-resident Data Platform

- **Wave**: Wave 1 / Architecture 2
- **Scope**: Migration and reconciliation of logistics data into the AU-resident platform.
- **Deliverables**:
  - Migrated logistics event store
  - Reconciliation dashboards
- **Dependencies**: ADR-001 (data residency decision)
- **GAPA Gaps addressed**: G-001, G-002
