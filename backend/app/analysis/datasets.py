"""Future consumers receive detached canonical facts through a read-only port."""
from collections.abc import Sequence
from typing import Protocol

from app.contracts.measurement_dataset import MeasurementDataset


class DatasetReader(Protocol):
    def read(self, experiment_ids: Sequence[str]) -> MeasurementDataset: ...


def read_dataset(reader: DatasetReader, experiment_ids: Sequence[str]) -> MeasurementDataset:
    return reader.read(experiment_ids)
