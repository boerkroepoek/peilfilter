from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import pandas as pd


@dataclass(frozen=True)
class CsvMetadata:
    """Metadata die tijdens de eerste scan van een CSV wordt gevonden."""

    filternummer: str
    header_row_index: int
    encoding: str


@dataclass(frozen=True)
class OutlierRecord:
    """Gegevens van één verwijderde uitschieter."""

    measurement_date: pd.Timestamp
    measurement_value: float
    hydrological_year: int
    yearly_mean: float
    absolute_deviation: float


@dataclass(frozen=True)
class OutlierFilterResult:
    """Resultaat van de uitschieterfiltering."""

    filtered_data: pd.DataFrame
    removed_outliers: tuple[OutlierRecord, ...]


@dataclass(frozen=True)
class GroundwaterStatistics:
    """Resultaat van de GHG- en GLG-proxyberekening."""

    ghg: Optional[float]
    glg: Optional[float]
    yearly_max: pd.Series
    yearly_min: pd.Series
    yearly_count: pd.Series
    reference_years: tuple[int, ...]
    excluded_years: tuple[int, ...]
    removed_outliers: tuple[OutlierRecord, ...]
    original_measurement_count: int = 0
    filtered_measurement_count: int = 0

    @property
    def removed_outlier_count(self) -> int:
        """Geef het aantal verwijderde uitschieters terug."""

        return len(self.removed_outliers)


@dataclass(frozen=True)
class UploadedCsvFile:
    """Browserupload van een CSV-bestand."""

    filename: str
    content: bytes


@dataclass
class ProcessingResult:
    """Resultaat van de verwerking van één CSV-bestand."""

    source_filename: str
    output_filename: Optional[str]
    success: bool
    message: str
    filternummer: Optional[str] = None
    dataframe: Optional[pd.DataFrame] = None
    filtered_dataframe: Optional[pd.DataFrame] = None
    statistics: Optional[GroundwaterStatistics] = None
    plot_png: Optional[bytes] = None
    pdf_bytes: Optional[bytes] = None
