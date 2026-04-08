"""CLI for one-off Hermes session S3 backfills."""

from __future__ import annotations

import argparse
import logging
import sys

from .mirror import SessionS3MirrorService


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="hermes-session-s3")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("sync-once", help="Upload changed Hermes session files once")

    return parser


def configure_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


def cmd_sync_once() -> int:
    service = SessionS3MirrorService()
    if not service.enabled:
        logging.error("Missing required env vars for Hermes session S3 mirror.")
        return 1

    uploaded = service.scan_once(force=True)
    logging.info("Uploaded %s file(s)", uploaded)
    return 0


def main(argv: list[str] | None = None) -> int:
    configure_logging()
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "sync-once":
        return cmd_sync_once()

    parser.error(f"Unsupported command: {args.command}")
    return 2


if __name__ == "__main__":
    sys.exit(main())
