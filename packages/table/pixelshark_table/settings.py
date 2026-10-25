"""Process settings. Environment variables override the defaults."""

from __future__ import annotations

import os
from dataclasses import dataclass


def _flag(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    return int(raw)


@dataclass
class Settings:
    """What ``pixelshark-table`` builds when the process starts."""

    host: str = "127.0.0.1"
    port: int = 8000
    autoplay: bool = True
    create_default: bool = True
    seats: int = 6
    small_blind: int = 50
    big_blind: int = 100
    starting_stack: int = 10_000
    seed: int = 1
    shot_clock_ms: int = 20_000
    hero_seat: int | None = None
    reveal: str = "showdown"
    bot_policy: str = "scripted"

    @classmethod
    def from_env(cls) -> Settings:
        hero = os.environ.get("PIXELSHARK_HERO_SEAT")
        return cls(
            host=os.environ.get("PIXELSHARK_HOST", "127.0.0.1"),
            port=_int("PIXELSHARK_PORT", 8000),
            autoplay=_flag("PIXELSHARK_AUTOPLAY", True),
            create_default=_flag("PIXELSHARK_CREATE_DEFAULT", True),
            seats=_int("PIXELSHARK_SEATS", 6),
            small_blind=_int("PIXELSHARK_SB", 50),
            big_blind=_int("PIXELSHARK_BB", 100),
            starting_stack=_int("PIXELSHARK_STACK", 10_000),
            seed=_int("PIXELSHARK_SEED", 1),
            shot_clock_ms=_int("PIXELSHARK_SHOT_CLOCK_MS", 20_000),
            hero_seat=None if hero in (None, "") else int(hero),
            reveal=os.environ.get("PIXELSHARK_REVEAL", "showdown"),
            bot_policy=os.environ.get("PIXELSHARK_BOT_POLICY", "scripted"),
        )
