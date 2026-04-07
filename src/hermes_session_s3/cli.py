"""CLI for Hermes session S3 mirroring."""

from __future__ import annotations

import argparse
import logging
import signal
import sys
import time

from .mirror import SessionS3MirrorService


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="hermes-session-s3")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("sync-once", help="Upload changed Hermes session files once")

    watch = subparsers.add_parser("watch", help="Continuously mirror Hermes sessions to S3")
    watch.add_argument("--poll-interval", type=float, default=5.0)
    watch.add_argument("--settle-seconds", type=float, default=2.0)

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


def cmd_watch(poll_interval: float, settle_seconds: float) -> int:
    service = SessionS3MirrorService(
        poll_interval_seconds=poll_interval,
        settle_seconds=settle_seconds,
    )
    if not service.enabled:
        logging.error("Missing required env vars for Hermes session S3 mirror.")
        return 1

    stop_requested = False

    def handle_signal(signum, frame):  # type: ignore[unused-argument]
        nonlocal stop_requested
        stop_requested = True

    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)

    service.start()
    logging.info("Watching %s for S3 mirroring", service.sessions_dir)

    try:
        while not stop_requested:
            time.sleep(0.5)
    finally:
        service.stop(flush=True)

    return 0


def main(argv: list[str] | None = None) -> int:
    configure_logging()
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "sync-once":
        return cmd_sync_once()
    if args.command == "watch":
        return cmd_watch(args.poll_interval, args.settle_seconds)

    parser.error(f"Unsupported command: {args.command}")
    return 2


if __name__ == "__main__":
    sys.exit(main())

