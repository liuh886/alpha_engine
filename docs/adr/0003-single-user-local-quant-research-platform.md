# ADR-0003: Single User Local Quant Research Platform

## Status

Accepted

## Date

2026-06-19

## Context

Alpha Engine is designed as a local quantitative research platform for a single
operator. Existing project constraints emphasize local data, local artifacts,
Qlib-based research flows, model training, factor evaluation, risk checks, and a
dashboard/API surface for operating the system.

The platform needs auditability and reproducibility, but it does not currently
need multi-tenant account isolation, organization-level RBAC, shared workspace
permissions, billing boundaries, or tenant-specific data partitioning.

Adding a multi-tenant permission system too early would increase schema,
testing, UI, API, and operational complexity while distracting from the Phase 1
architecture goal: make domain truth, evidence, workflow, and execution
boundaries clear.

## Decision

Alpha Engine MUST remain scoped as a single-user local quant research platform
unless a future ADR changes this constraint.

The system SHOULD provide local safety controls appropriate for a single
operator, such as clear configuration, explicit execution plans, evidence-backed
promotion, audit records, and adapter authentication where needed for local
services. It MUST NOT introduce a full multi-tenant permissions model as part of
Phase 1 convergence.

Data ownership, research decisions, and execution controls are assumed to belong
to one operator in one local research environment. Any future multi-user or
hosted deployment work MUST first define new threat models, data isolation
requirements, audit requirements, and operational responsibilities.

## Consequences

- Architecture work can focus on core module boundaries instead of tenant and
  permission infrastructure.
- Local adapters may still require tokens or basic access protection, but that
  is adapter hardening, not a multi-tenant authorization model.
- Database and artifact schemas do not need tenant IDs by default.
- Tests should prioritize reproducibility, evidence integrity, lifecycle
  correctness, and execution safety over tenant isolation.
- If shared or hosted usage becomes a requirement, a future ADR must revisit
  identity, authorization, data partitioning, audit trails, and deployment
  boundaries before implementation.

## Alternatives Considered

### Add multi-tenant RBAC now

Rejected because it solves a different product problem than the current local
research platform and would slow the more urgent architecture convergence work.

### Ignore access control completely

Rejected because local adapters may still need basic authentication or token
checks to prevent accidental exposure. The decision is against multi-tenancy,
not against reasonable local hardening.

### Design all schemas for future tenancy

Rejected for Phase 1 because speculative tenant fields can leak into domain
models and create unclear invariants. Future hosted work should be designed when
the requirement is real.

