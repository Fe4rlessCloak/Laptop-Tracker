"""Command-line entry point for the OLX scraper.

Usage examples:
    python -m scraper --hours 24
    python -m scraper --cities islamabad rawalpindi --hours 12 --export csv json
    python -m scraper --db data/olx.db --export json --delay 3
"""

from __future__ import annotations

import argparse
import sys

from scraper import config
from scraper.runner import run


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="olx-scraper",
        description="Scrape recent OLX Pakistan laptop listings (Islamabad/Rawalpindi).",
    )
    parser.add_argument(
        "--cities",
        nargs="+",
        default=list(config.DEFAULT_CITIES.keys()),
        help="City names to scrape (default: %(default)s). "
        "Must be keys in scraper/config.py DEFAULT_CITIES.",
    )
    parser.add_argument(
        "--hours",
        type=int,
        default=config.DEFAULT_HOURS,
        help="Look back window in hours (default: %(default)s).",
    )
    parser.add_argument(
        "--export",
        nargs="+",
        choices=["csv", "json"],
        default=[],
        help="Export formats to write after scraping (default: none).",
    )
    parser.add_argument(
        "--db",
        default=config.DEFAULT_DB_PATH,
        help=f"Path to the SQLite database (default: {config.DEFAULT_DB_PATH}).",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=config.DEFAULT_DELAY,
        help=f"Delay in seconds between requests (default: {config.DEFAULT_DELAY}).",
    )
    parser.add_argument(
        "--category",
        default="laptops",
        choices=list(config.CATEGORIES.keys()),
        help="OLX category to scrape (default: %(default)s). "
        "Keys of scraper/config.py CATEGORIES.",
    )
    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)

    # Resolve city names to their OLX slugs.
    cities = {}
    for name in args.cities:
        slug = config.DEFAULT_CITIES.get(name)
        if slug is None:
            print(
                f"Unknown city '{name}'. Available: {', '.join(config.DEFAULT_CITIES)}",
                file=sys.stderr,
            )
            return 2
        cities[name] = slug

    summary = run(
        cities=cities,
        hours=args.hours,
        db_path=args.db,
        export=args.export,
        delay=args.delay,
        category=args.category,
    )
    print(summary)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
