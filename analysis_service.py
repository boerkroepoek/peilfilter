from __future__ import annotations

import logging
import math

import pandas as pd

from config import AppConfig
from models import (
    GroundwaterStatistics,
    OutlierFilterResult,
    OutlierRecord,
)


class GroundwaterAnalysisService:
    """Service voor hydrologische berekeningen en uitschieteranalyse."""

    def __init__(self, config: AppConfig) -> None:
        self.config = config

    def add_hydrological_year(
        self,
        dataframe: pd.DataFrame,
    ) -> pd.DataFrame:
        """Voeg het hydrologische startjaar aan een kopie toe."""

        start_month = self.config.hydrological_year_start_month

        if not 1 <= start_month <= 12:
            raise ValueError(
                "De startmaand moet tussen 1 en 12 liggen."
            )

        date_column = self.config.expected_date_column

        if date_column not in dataframe.columns:
            raise ValueError(
                f"Datumkolom '{date_column}' ontbreekt."
            )

        enriched_df = dataframe.copy()
        dates = enriched_df[date_column]

        if not pd.api.types.is_datetime64_any_dtype(dates):
            raise TypeError(
                f"Kolom '{date_column}' moet datetime-waarden bevatten."
            )

        if dates.isna().any():
            raise ValueError(
                f"Kolom '{date_column}' bevat lege datums."
            )

        enriched_df[self.config.hydrological_year_column] = (
            dates.dt.year.where(
                dates.dt.month >= start_month,
                dates.dt.year - 1,
            ).astype("int64")
        )

        return enriched_df

    def hydrological_year_boundaries(
        self,
        hydrological_year: int,
    ) -> tuple[pd.Timestamp, pd.Timestamp]:
        """Geef begin en einde van een hydrologisch jaar terug."""

        start_month = self.config.hydrological_year_start_month

        if not 1 <= start_month <= 12:
            raise ValueError(
                "De startmaand moet tussen 1 en 12 liggen."
            )

        start = pd.Timestamp(
            year=hydrological_year,
            month=start_month,
            day=1,
        )

        end = (
            start
            + pd.DateOffset(years=1)
            - pd.Timedelta(days=1)
        )

        return start, end

    def remove_outliers_per_hydrological_year(
        self,
        dataframe: pd.DataFrame,
    ) -> OutlierFilterResult:
        """
        Verwijder uitschieters per hydrologisch jaar.

        Een meetwaarde is een uitschieter wanneer de absolute afwijking
        ten opzichte van het gemiddelde van het hydrologische jaar groter
        is dan de ingestelde drempel.
        """

        threshold_meters = self.config.outlier_threshold_meters

        if dataframe.empty:
            return OutlierFilterResult(
                filtered_data=dataframe.copy(),
                removed_outliers=(),
            )

        if not math.isfinite(threshold_meters):
            raise ValueError(
                "De uitschieterdrempel moet een eindig getal zijn."
            )

        if threshold_meters < 0:
            raise ValueError(
                "De uitschieterdrempel mag niet negatief zijn."
            )

        year_column = self.config.hydrological_year_column
        date_column = self.config.expected_date_column
        measurement_column = self.config.expected_measurement_column

        required_columns = {
            year_column,
            date_column,
            measurement_column,
        }

        missing_columns = required_columns.difference(
            dataframe.columns
        )

        if missing_columns:
            raise ValueError(
                "Ontbrekende kolommen voor uitschieterfiltering: "
                f"{sorted(missing_columns)}"
            )

        result = dataframe.copy()

        if not pd.api.types.is_numeric_dtype(
            result[measurement_column]
        ):
            raise TypeError(
                f"Kolom '{measurement_column}' moet numeriek zijn."
            )

        result["_yearly_mean"] = result.groupby(
            year_column,
            sort=False,
        )[measurement_column].transform("mean")

        result["_absolute_deviation"] = (
            result[measurement_column]
            - result["_yearly_mean"]
        ).abs()

        candidate_outlier_mask = (
            result["_absolute_deviation"] > threshold_meters
        )

        keep_mask = ~candidate_outlier_mask

        retained_counts = keep_mask.groupby(
            result[year_column]
        ).sum()

        fully_rejected_years = retained_counts[
            retained_counts == 0
        ].index

        if len(fully_rejected_years) > 0:
            restore_mask = result[year_column].isin(
                fully_rejected_years
            )
            keep_mask = keep_mask | restore_mask

            for year in fully_rejected_years:
                logging.warning(
                    "Hydrologisch jaar %s zou volledig verdwijnen "
                    "na filtering. De oorspronkelijke metingen zijn "
                    "behouden.",
                    int(year),
                )

        removed_mask = ~keep_mask
        removed_data = result.loc[removed_mask].copy()

        removed_outliers = tuple(
            OutlierRecord(
                measurement_date=pd.Timestamp(
                    row[date_column]
                ),
                measurement_value=float(
                    row[measurement_column]
                ),
                hydrological_year=int(
                    row[year_column]
                ),
                yearly_mean=float(
                    row["_yearly_mean"]
                ),
                absolute_deviation=float(
                    row["_absolute_deviation"]
                ),
            )
            for _, row in removed_data.sort_values(
                date_column,
                kind="stable",
            ).iterrows()
        )

        filtered_df = (
            result.loc[keep_mask]
            .drop(
                columns=[
                    "_yearly_mean",
                    "_absolute_deviation",
                ]
            )
            .sort_values(
                date_column,
                kind="stable",
            )
            .reset_index(drop=True)
        )

        logging.info(
            "Totaal %d uitschieter(s) verwijderd.",
            len(removed_outliers),
        )

        return OutlierFilterResult(
            filtered_data=filtered_df,
            removed_outliers=removed_outliers,
        )

    def select_reference_years(
        self,
        yearly_count: pd.Series,
    ) -> tuple[tuple[int, ...], tuple[int, ...]]:
        """Selecteer hydrologische jaren met voldoende metingen."""

        minimum_measurements = (
            self.config.minimum_measurements_per_year
        )

        if minimum_measurements < 1:
            raise ValueError(
                "Het minimumaantal metingen per jaar moet "
                "minimaal 1 zijn."
            )

        if yearly_count.empty:
            return (), ()

        reference_years = tuple(
            sorted(
                int(year)
                for year, count in yearly_count.items()
                if int(count) >= minimum_measurements
            )
        )

        excluded_years = tuple(
            sorted(
                int(year)
                for year, count in yearly_count.items()
                if int(count) < minimum_measurements
            )
        )

        return reference_years, excluded_years

    @staticmethod
    def empty_statistics(
        original_measurement_count: int = 0,
        filtered_measurement_count: int = 0,
        removed_outliers: tuple[OutlierRecord, ...] = (),
        excluded_years: tuple[int, ...] = (),
    ) -> GroundwaterStatistics:
        """Maak een leeg statistiekresultaat."""

        return GroundwaterStatistics(
            ghg=None,
            glg=None,
            yearly_max=pd.Series(dtype="float64"),
            yearly_min=pd.Series(dtype="float64"),
            yearly_count=pd.Series(dtype="int64"),
            reference_years=(),
            excluded_years=excluded_years,
            removed_outliers=removed_outliers,
            original_measurement_count=original_measurement_count,
            filtered_measurement_count=filtered_measurement_count,
        )

    def calculate_statistics(
        self,
        dataframe: pd.DataFrame,
    ) -> tuple[GroundwaterStatistics, pd.DataFrame]:
        """Bereken GHG- en GLG-proxywaarden per hydrologisch jaar."""

        if dataframe is None or dataframe.empty:
            return self.empty_statistics(), pd.DataFrame()

        original_measurement_count = len(dataframe)
        calculation_df = self.add_hydrological_year(dataframe)

        filter_result = (
            self.remove_outliers_per_hydrological_year(
                calculation_df
            )
        )

        filtered_df = filter_result.filtered_data
        removed_outliers = filter_result.removed_outliers
        filtered_measurement_count = len(filtered_df)

        if filtered_df.empty:
            return (
                self.empty_statistics(
                    original_measurement_count=(
                        original_measurement_count
                    ),
                    filtered_measurement_count=(
                        filtered_measurement_count
                    ),
                    removed_outliers=removed_outliers,
                ),
                filtered_df,
            )

        year_column = self.config.hydrological_year_column
        measurement_column = (
            self.config.expected_measurement_column
        )

        grouped = filtered_df.groupby(
            year_column,
            sort=True,
        )[measurement_column]

        yearly_max_all = grouped.max()
        yearly_min_all = grouped.min()
        yearly_count_all = grouped.count().astype("int64")

        reference_years, excluded_years = (
            self.select_reference_years(
                yearly_count_all
            )
        )

        if excluded_years:
            logging.warning(
                "Hydrologische jaren uitgesloten wegens minder "
                "dan %d metingen: %s",
                self.config.minimum_measurements_per_year,
                list(excluded_years),
            )

        if not reference_years:
            return (
                self.empty_statistics(
                    original_measurement_count=(
                        original_measurement_count
                    ),
                    filtered_measurement_count=(
                        filtered_measurement_count
                    ),
                    removed_outliers=removed_outliers,
                    excluded_years=excluded_years,
                ),
                filtered_df,
            )

        year_index = list(reference_years)

        reference_max = yearly_max_all.loc[year_index].copy()
        reference_min = yearly_min_all.loc[year_index].copy()
        reference_count = yearly_count_all.loc[year_index].copy()

        ghg = float(reference_max.mean())
        glg = float(reference_min.mean())

        if not math.isfinite(ghg) or not math.isfinite(glg):
            raise ValueError(
                "De berekende GHG- of GLG-proxy is geen geldig getal."
            )

        statistics = GroundwaterStatistics(
            ghg=ghg,
            glg=glg,
            yearly_max=reference_max,
            yearly_min=reference_min,
            yearly_count=reference_count,
            reference_years=reference_years,
            excluded_years=excluded_years,
            removed_outliers=removed_outliers,
            original_measurement_count=original_measurement_count,
            filtered_measurement_count=filtered_measurement_count,
        )

        return statistics, filtered_df
