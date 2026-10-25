"""Errors a caller can catch when a frame cannot be read."""


class PerceptionError(Exception):
    """The reader could not return a schema-valid game state.

    This is a bad model answer, a backend that could not be reached, or a mock
    with nothing left to say. It is not an illegal poker action.
    """
