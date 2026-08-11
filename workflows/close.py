"""Scheduler-facing wrapper for the installable end-of-day workflow."""

from quant_raas.services.close_workflow import run_close_workflow

__all__ = ["run_close_workflow"]
