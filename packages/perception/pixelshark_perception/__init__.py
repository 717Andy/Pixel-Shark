"""Read a table from pixels.

Phase 0 does not call a model. :class:`GroundTruthReader` stands in for one by
returning a state the table already produced, so the rest of the loop can be
tested. :class:`VlmReader` is the planned first real reader: a vision-language
model that fills this same schema. Distilled detectors can replace it later
behind the same ``read`` method.
"""

from pixelshark_perception.reader import GroundTruthReader, TableReader, VlmReader

__all__ = ["GroundTruthReader", "TableReader", "VlmReader"]
