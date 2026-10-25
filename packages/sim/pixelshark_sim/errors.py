"""Errors a caller can recover from. They become HTTP 409 responses at the table."""


class PixelSharkError(Exception):
    """Base class for expected table failures."""


class TableConfigError(PixelSharkError):
    """The requested table cannot be built (seat count, blinds, stacks)."""


class IllegalAction(PixelSharkError):
    """The action is not legal for the current actor."""


class HumanToAct(PixelSharkError):
    """A bot step was requested, but the actor is a human seat."""
