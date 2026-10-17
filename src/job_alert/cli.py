"""Run locally: python -m job_alert.cli run [--dry-run]"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

from job_alert.config import load_config
from job_alert.notifier import render_html, subject
from job_alert.runner import run
from job_alert.scrapers.base import make_client
from job_alert.store import LocalJsonStore


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="job_alert")
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("run", help="scrape, diff, and write the digest to an HTML file")
    p.add_argument("--config", default="config/companies.yaml")
    p.add_argument("--store", default=".data/store.json", help="local JSON store path")
    p.add_argument("--out", default="out/digest.html")
    p.add_argument("--dry-run", action="store_true", help="don't save the store afterwards")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    store = LocalJsonStore(args.store)
    with make_client() as client:
        report = run(load_config(args.config), store, client)
    if not args.dry_run:
        store.save()

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render_html(report))
    print(subject(report))
    print(f"Digest written to {out.resolve()}")


if __name__ == "__main__":
    main()
