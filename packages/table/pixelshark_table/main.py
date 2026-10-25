"""Run the table. ``pixelshark-table`` and ``python -m pixelshark_table`` both land here."""

from __future__ import annotations

import argparse

import uvicorn

from pixelshark_table.settings import Settings


def main(argv: list[str] | None = None) -> None:
    settings = Settings.from_env()
    parser = argparse.ArgumentParser(description="Serve the Pixel Shark poker table.")
    parser.add_argument("--host", default=settings.host)
    parser.add_argument("--port", type=int, default=settings.port)
    args = parser.parse_args(argv)
    uvicorn.run(
        "pixelshark_table.app:app",
        host=args.host,
        port=args.port,
        log_level="info",
    )


if __name__ == "__main__":
    main()
