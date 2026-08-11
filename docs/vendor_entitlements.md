# Vendor entitlement inventory

This document is an inventory template, not a statement that any feed is
licensed. All rows start as **unverified** until the data owner confirms the
contract, fields, history, storage rights, and intended execution environment.

## Inventory

| Provider | Intended use | Development mode | Production mode | Initial status |
|---|---|---|---|---|
| Bloomberg | Prices, fundamentals, estimates, news, ownership, macro | Entitled Terminal session | B-PIPE/server product if contracted | Unverified |
| LSEG | Prices, fundamentals, estimates, news, macro | Workspace desktop session | Platform/cloud session if contracted | Unverified |
| SEC EDGAR | Filing metadata, filing text, Company Facts | HTTPS with declared user agent | Same, subject to fair-access guidance | Not configured |
| Official macro agencies | Releases and time series | Agency-specific API/download | Same | Not configured |
| Yahoo via `yfinance` | Prototype fallback only | Opt-in local connector | Not an authoritative production feed | Disabled |

## Fields to confirm before enabling a provider

Record the following in the organization's approved entitlement system:

- legal entity, contract owner, and technical owner;
- entitled users, applications, environments, and service accounts;
- datasets, field groups, exchanges, regions, and historical depth;
- real-time versus delayed status and expected refresh cadence;
- snapshot, bulk-download, derived-data, and caching permissions;
- retention, backup, display, redistribution, and model-training restrictions;
- request quotas, concurrency limits, and fair-use requirements;
- identifier symbology and corporate-action coverage;
- desktop, server, disaster-recovery, and cloud deployment rights; and
- termination/deletion obligations and audit contacts.

## Connector rules

- A connector must return normalized records through a provider protocol; quant
  modules must not import vendor SDKs.
- Every record stores provider, source identifier, source timestamp,
  `available_at`, and ingestion time.
- Entitlement or quota failures are explicit errors. They are never converted to
  a zero, stale observation, or silent fallback.
- Cross-provider reconciliation preserves both observations and the rule used to
  select one; conflicting values remain auditable.
- Raw vendor payloads are stored only where the relevant contract permits it.
- Secrets stay in environment/secret stores. They do not belong in YAML, logs,
  research cards, fixtures, or committed `.env` files.

## Optional SDK installation

The default package does not install licensed SDKs. `.[lseg]` provides the LSEG
Python library, but access still requires a valid approved session. Bloomberg
installation depends on the client's approved Bloomberg distribution channel;
the named `bloomberg` extra deliberately installs no unapproved package.

Public fallback data is suitable for demonstrations and connector development,
not vendor reconciliation or investment-production assertions. External smoke
tests must carry the `external` pytest marker and are excluded from CI.

