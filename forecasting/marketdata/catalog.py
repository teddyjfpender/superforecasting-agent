"""Load isolated catalog snapshots; pure schemas live in protocol.data_desk."""

from functools import lru_cache
from pathlib import Path

from protocol.data_desk import (
    DataCatalog as DataCatalog,
)
from protocol.data_desk import (
    DataCategory as DataCategory,
)
from protocol.data_desk import (
    DataCountry as DataCountry,
)
from protocol.data_desk import (
    DataKind as DataKind,
)
from protocol.data_desk import (
    DataLocation as DataLocation,
)
from protocol.data_desk import (
    DataPreset as DataPreset,
)
from protocol.data_desk import (
    DataProvider as DataProvider,
)
from protocol.data_desk import (
    DataRegion as DataRegion,
)
from protocol.data_desk import (
    DataSeries as DataSeries,
)
from protocol.data_desk import (
    Frequency as Frequency,
)


@lru_cache(maxsize=1)
def _catalog() -> DataCatalog:
    return DataCatalog.model_validate_json(
        Path(__file__).with_name("catalog.json").read_text(encoding="utf-8")
    )


def load_catalog() -> DataCatalog:
    """Return an isolated snapshot so callers cannot mutate the shared registry."""
    return _catalog().model_copy(deep=True)
