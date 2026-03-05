# ADR 002: Metadata Storage using SQLite

**Date**: 2026-03-01
**Status**: Accepted

## Context
The project needs to store run records, experiment metadata, and UI configuration. Historically, similar projects lean heavily into MySQL or MongoDB, requiring users to install database services.

## Decision
We will use **SQLite** as the exclusive storage for all non-timeseries metadata. Time-series and market data will be stored as optimized Parquet/CSV files.

## Consequences
- **Positive**: True zero-configuration setup for end users. Total portability via `data/local_market.db`.
- **Positive**: Reduces RAM and CPU footprint of the local environment.
- **Negative**: Not suitable for high-concurrency multi-writer workloads (which is fine since this is a local-first single-tenant system).
