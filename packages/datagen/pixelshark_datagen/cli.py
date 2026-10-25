"""Command line for the screenshot generator."""

from __future__ import annotations

import argparse
from pathlib import Path

from pixelshark_datagen.generate import generate_dataset


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="pixelshark-datagen",
        description="Save screenshots of the Pixel Shark table with ground-truth JSON.",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    generate = sub.add_parser("generate", help="Write N labeled frames.")
    generate.add_argument("-n", "--count", type=int, default=4, help="How many samples to write.")
    generate.add_argument(
        "-o",
        "--out",
        type=Path,
        default=Path("examples/sample"),
        help="Output directory.",
    )
    generate.add_argument("--seed", type=int, default=7, help="Seed for the dealt cards.")
    generate.add_argument(
        "--base-url",
        default=None,
        help="Use a table server that is already running. The default is to start one.",
    )
    generate.add_argument("--seats", type=int, default=6)
    args = parser.parse_args(argv)
    if args.command == "generate":
        path = generate_dataset(
            count=args.count,
            out=args.out,
            seed=args.seed,
            base_url=args.base_url,
            seats=args.seats,
        )
        print(f"wrote {args.count} samples to {path}")


if __name__ == "__main__":
    main()
