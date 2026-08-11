"""Command-line entry point for local setup and finite research jobs."""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from uuid import UUID

from quant_raas.config import get_settings
from quant_raas.storage.session import create_schema, create_sql_engine


def _aware_datetime(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise argparse.ArgumentTypeError("timestamp must include a timezone or Z suffix")
    return parsed


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="quant-raas")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("init-db", help="Create local development tables.")
    commands.add_parser("seed-demo", help="Load a complete deterministic offline demo.")
    daily = commands.add_parser("daily", help="Run research from already-ingested prices.")
    daily.add_argument("--coverage-id", type=UUID)
    daily.add_argument("--as-of", type=_aware_datetime)
    daily.add_argument("--data-cutoff", type=_aware_datetime)
    daily.add_argument("--source")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    settings = get_settings()
    if args.command == "init-db":
        create_schema(create_sql_engine(settings))
        print(json.dumps({"status": "ok", "database": settings.database_url}))
        return 0
    if args.command == "seed-demo":
        from quant_raas.demo import seed_demo

        seed_result = seed_demo(settings)
        print(
            json.dumps(
                {
                    "status": seed_result.research.run.status.value,
                    "coverage_list_id": str(seed_result.coverage_list_id),
                    "securities": seed_result.securities,
                    "bars_received": seed_result.ingestion.bars_received,
                    "cards": len(seed_result.research.cards),
                    "failures": [failure.message for failure in seed_result.research.failures],
                }
            )
        )
        return 0 if seed_result.research.cards else 1
    if args.command == "daily":
        # Import lazily so schema initialization remains usable without loading
        # pandas-heavy workflow modules.
        from quant_raas.services.close_workflow import run_close_workflow

        daily_result = run_close_workflow(
            settings,
            coverage_list_id=args.coverage_id,
            as_of=args.as_of,
            data_cutoff_at=args.data_cutoff,
            source=args.source,
        )
        print(
            json.dumps(
                {
                    "status": daily_result.run.status.value,
                    "run_id": str(daily_result.run.research_run_id),
                    "cards": len(daily_result.cards),
                    "failures": [failure.message for failure in daily_result.failures],
                }
            )
        )
        return 0 if daily_result.cards else 1
    return 2


if __name__ == "__main__":  # Support `python -m quant_raas.cli` as well as the console script.
    raise SystemExit(main())
