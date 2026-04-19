"""vla2cli CLI — command-line entry point for VLA dataset conversion.

Stub implementation. See README.md for the full pipeline design.
"""
from __future__ import annotations

import argparse
import sys


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="vla2cli",
        description="Extract Snakes-usable datasets from VLA training corpora.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_ingest = sub.add_parser("ingest", help="Ingest a VLA dataset")
    p_ingest.add_argument("--source", required=True, choices=["lerobot", "rlds", "oxe", "droid"])
    p_ingest.add_argument("--path", help="Path to source dataset")
    p_ingest.add_argument("--task", help="Task filter")
    p_ingest.add_argument("--limit", type=int, default=100)
    p_ingest.add_argument("--output-mode", required=True, choices=["skill", "eventlog", "finetune"])
    p_ingest.add_argument("--out", required=True, help="Output directory")

    sub.add_parser("sources", help="List supported VLA data sources")
    p_validate = sub.add_parser("validate", help="Validate extracted data")
    p_validate.add_argument("--path", required=True)

    args = parser.parse_args(argv)

    if args.command == "sources":
        print("Supported sources:")
        print("  lerobot  — HuggingFace LeRobot datasets")
        print("  rlds     — Google RLDS / TFDS robotics datasets")
        print("  oxe      — Open X-Embodiment")
        print("  droid    — Stanford DROID dataset")
        return 0

    if args.command == "ingest":
        print(f"vla2cli ingest: not yet implemented (source={args.source}, mode={args.output_mode})")
        print("See vla2cli/README.md for the implementation plan.")
        return 0

    if args.command == "validate":
        print(f"vla2cli validate: not yet implemented (path={args.path})")
        return 0

    return 0


if __name__ == "__main__":
    sys.exit(main())
