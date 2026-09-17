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
| Project | test-oaa-dummy |
| Classification | OFFICIAL |
| Status | DRAFT |
| Version | 1.0 |
| Created | 2026-02-24 |
| Owner | Chief Enterprise Architect |

---

## 1. Transition Overview

| Architecture | Scope | Duration | Investment |
|--------------|-------|----------|------------|
| Architecture 1 (Baseline) | Current state — legacy auth, manual logging, on-prem SQL | — | — |
| Architecture 2 | Wave 1 — hardened security baseline, self-service portal MVP | 3 months | $2M |
| Target Architecture | Final state — cloud-native, event-driven, outcome-measured | — | — |

### Transition Waves

**Wave 1 — Legacy Secure Baseline** (Architecture 2)

- **Objective**: Secure baseline plus visible user value.
- **Duration**: 2026-03-01 to 2026-05-31 (3 months)
- **Key Deliverables**:
  - OAuth2/OIDC with MFA in production
  - Self-service portal MVP behind feature flags
- **Governance Gate**: Wave 1 Complete — Steering review
