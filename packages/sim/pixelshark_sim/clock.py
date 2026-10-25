"""Clocks so tests can advance the shot clock without sleeping."""

from __future__ import annotations

import time
from typing import Protocol


class Clock(Protocol):
    def unix_ms(self) -> int:
        """Wall-clock milliseconds, used for the deadline in the state document."""

    def monotonic(self) -> float:
        """Seconds that only move forward. The autoplay loop schedules with this."""


class WallClock:
    """The real clock."""

    def unix_ms(self) -> int:
        return int(time.time() * 1000)

    def monotonic(self) -> float:
        return time.monotonic()
