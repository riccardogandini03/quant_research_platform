"""Event-ingestion boundary reserved for timestamped Phase-2 sources.

The concrete SEC, news, earnings, and macro repositories are intentionally not
faked in Phase 1.  Event studies can already consume canonical `CompanyEvent`
objects, while this adapter remains disabled until a source can preserve exact
publication timestamps and vintages.
"""
