"""Command line for the perception reader, the eval report, and the live watch."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from pixelshark_perception.backends import OracleBackend, backend_from_env
from pixelshark_perception.errors import PerceptionError
from pixelshark_perception.evaluate import evaluate_dataset
from pixelshark_perception.reader import PerceptionResult, VlmReader
from pixelshark_perception.readlog import ReadLog, write_result
from pixelshark_perception.watch import format_state, format_turn, run_table_watch


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="pixelshark-perceive",
        description="Read a poker table from a screenshot. No clicks.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    evaluate = sub.add_parser("eval", help="Score a reader on a datagen directory.")
    evaluate.add_argument("--data", type=Path, required=True, help="Dataset directory.")
    evaluate.add_argument(
        "--out",
        type=Path,
        default=Path("reports/perception"),
        help="Where to write report.json and report.md.",
    )
    evaluate.add_argument(
        "--holdout-skin",
        default="linen",
        help="Skin scored on its own. Default: linen, which the sample set does not use.",
    )
    evaluate.add_argument(
        "--backend",
        choices=("mock", "oracle", "local", "qwen", "hosted"),
        default=None,
        help=(
            "Overrides PIXELSHARK_VLM. oracle repeats the ground truth so you can check the report."
        ),
    )
    evaluate.add_argument("--limit", type=int, default=None, help="Read at most this many frames.")
    evaluate.add_argument("--attempts", type=int, default=3, help="Schema retries per frame.")
    evaluate.add_argument(
        "--log",
        type=Path,
        default=None,
        help="Also store frames and reads here for a later detector.",
    )

    watch = sub.add_parser("watch", help="Print the perceived state whenever it is our turn.")
    watch.add_argument("--url", default="http://127.0.0.1:8000", help="Table server.")
    watch.add_argument(
        "--hero", type=int, required=True, help="Our seat index. 0 is the bottom seat."
    )
    watch.add_argument("--skin", default="felt")
    watch.add_argument("--backend", choices=("mock", "local", "qwen", "hosted"), default=None)
    watch.add_argument("--frames", type=int, default=0, help="Screenshots to take. 0 keeps going.")
    watch.add_argument("--interval", type=float, default=1.0, help="Seconds between screenshots.")
    watch.add_argument("--attempts", type=int, default=3)
    watch.add_argument(
        "--log",
        type=Path,
        default=None,
        help="Also store each printed read with its frame.",
    )

    read = sub.add_parser("read", help="Read one image and print the game state.")
    read.add_argument("image", type=Path)
    read.add_argument("--backend", choices=("mock", "local", "qwen", "hosted"), default=None)
    read.add_argument("--attempts", type=int, default=3)
    read.add_argument("--log", type=Path, default=None, help="Also store the read with the frame.")

    args = parser.parse_args(argv)
    try:
        if args.command == "eval":
            return _eval(args)
        if args.command == "watch":
            return _watch(args)
        if args.command == "read":
            return _read(args)
    except PerceptionError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    except FileNotFoundError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    return 2


def _eval(args: argparse.Namespace) -> int:
    if args.backend == "oracle":
        backend = OracleBackend()
    else:
        backend = _backend(args.backend)
    report = evaluate_dataset(
        args.data,
        backend,
        holdout_skin=args.holdout_skin,
        out=args.out,
        log_dir=args.log,
        limit=args.limit,
        attempts=args.attempts,
    )
    overall = report["overall"]["full_state_exact_match"]
    accuracy = overall["accuracy"]
    shown = "n/a" if accuracy is None else f"{accuracy * 100:.1f}%"
    print(
        f"wrote {args.out / 'report.json'} and {args.out / 'report.md'} "
        f"({report['frames']} frames, exact match {shown})"
    )
    return 0


def _watch(args: argparse.Namespace) -> int:
    reader = VlmReader(_backend(args.backend), attempts=args.attempts)
    read_log = ReadLog(args.log) if args.log is not None else None

    def on_turn(result: PerceptionResult) -> None:
        print(format_turn(result))
        print(format_state(result.state))
        print()
        if read_log is not None:
            write_result(read_log, result, skin=args.skin)

    def on_error(exc: PerceptionError) -> None:
        print(f"read failed: {exc}", file=sys.stderr)

    frames = None if args.frames == 0 else args.frames
    try:
        run_table_watch(
            base_url=args.url,
            hero_seat=args.hero,
            reader=reader,
            skin=args.skin,
            frames=frames,
            interval_s=args.interval,
            on_turn=on_turn,
            on_error=on_error,
        )
    except KeyboardInterrupt:
        return 0
    return 0


def _read(args: argparse.Namespace) -> int:
    image = args.image.read_bytes()
    result = VlmReader(_backend(args.backend), attempts=args.attempts).read_detail(image)
    print(format_turn(result, heading="perceived"))
    print(format_state(result.state))
    if args.log is not None:
        write_result(ReadLog(args.log), result)
    return 0


def _backend(name: str | None):
    if name is None:
        return backend_from_env()
    env = os.environ.copy()
    env["PIXELSHARK_VLM"] = name
    return backend_from_env(env)


if __name__ == "__main__":
    raise SystemExit(main())
