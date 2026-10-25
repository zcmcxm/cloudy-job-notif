"""One-off: copy the local store (.data/store.json) into the deployed DynamoDB table.

Without this, the first cloud run treats every company as a baseline and "open since"
dates restart. Run it once, right after the first deploy:

    python scripts/seed_dynamo.py --table <TableName output of cdk deploy>

Refuses to touch a table that already has items, so it can't overwrite cloud state later.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import boto3

from job_alert.store import LocalJsonStore, _pk, _to_item


def seed(store: LocalJsonStore, table) -> tuple[int, int]:
    """Write a META item per company and every job (open and closed). Returns (companies, jobs)."""
    companies = jobs = 0
    with table.batch_writer() as batch:
        for company_id, stored_jobs in store._data.items():
            batch.put_item(Item={"PK": _pk(company_id), "SK": "META"})
            companies += 1
            for job in stored_jobs.values():
                batch.put_item(Item=_to_item(job))
                jobs += 1
    return companies, jobs


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--table", required=True, help="DynamoDB table name (cdk deploy output TableName)")
    parser.add_argument("--store", default=".data/store.json", help="local JSON store to copy")
    args = parser.parse_args()

    if not Path(args.store).exists():
        print(f"No local store at {args.store}", file=sys.stderr)
        return 1
    table = boto3.resource("dynamodb").Table(args.table)
    if table.scan(Limit=1, Select="COUNT")["Count"]:
        print(f"{args.table} already has items; refusing to overwrite cloud state.", file=sys.stderr)
        return 1

    companies, jobs = seed(LocalJsonStore(args.store), table)
    print(f"Seeded {companies} companies and {jobs} jobs into {args.table}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
