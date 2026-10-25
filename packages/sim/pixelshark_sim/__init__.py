"""Headless no-limit hold'em. The web table and the screenshot generator both use this.

PokerKit numbers players relative to the blinds, so those numbers change every
hand. :class:`Table` keeps stable seats (0 is across the bottom of the UI) and
moves the button clockwise instead.
"""

from pixelshark_sim.bots import RandomPolicy, ScriptedPolicy, make_policy
from pixelshark_sim.clock import Clock, WallClock
from pixelshark_sim.engine import Table
from pixelshark_sim.errors import HumanToAct, IllegalAction, TableConfigError

__all__ = [
    "Clock",
    "HumanToAct",
    "IllegalAction",
    "RandomPolicy",
    "ScriptedPolicy",
    "Table",
    "TableConfigError",
    "WallClock",
    "make_policy",
]
