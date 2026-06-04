import argparse
import json

from sqlmodel import Session

from app.database import engine
from app.services.application_answer_rotation import reencrypt_application_answer_profiles


def parse_args():
    parser = argparse.ArgumentParser(
        description="Re-encrypt application answer-vault rows with the current APP_DATA_ENCRYPTION_KEY.",
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--apply",
        action="store_true",
        help="Write re-encrypted values. Without this flag the job runs as a dry run.",
    )
    mode.add_argument(
        "--dry-run",
        action="store_true",
        help="Inspect rows without writing changes. This is the default.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Optional maximum number of answer-vault rows to inspect.",
    )
    return parser.parse_args()


def main():
    args = parse_args()
    with Session(engine) as session:
        result = reencrypt_application_answer_profiles(
            session,
            dry_run=not args.apply,
            limit=args.limit,
        )
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
