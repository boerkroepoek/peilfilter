from __future__ import annotations

from io import BytesIO

import matplotlib

matplotlib.use("Agg")

import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import pandas as pd
from matplotlib.figure import Figure

from config import AppConfig
from models import GroundwaterStatistics
from utilities import format_nap_value


class ChartService:
    """Service voor het genereren van grondwatergrafieken."""

    def __init__(self, config: AppConfig) -> None:
        self.config = config

    def create_figure(
        self,
        dataframe: pd.DataFrame,
        filternummer: str,
        statistics: GroundwaterStatistics,
    ) -> Figure:
        """Genereer een Matplotlib-figuur."""

        if dataframe is None or dataframe.empty:
            raise ValueError(
                "Geen data beschikbaar om te plotten."
            )

        figure, axis = plt.subplots(
            figsize=(
                self.config.plot_width_inches,
                self.config.plot_height_inches,
            )
        )

        date_column = self.config.expected_date_column
        measurement_column = (
            self.config.expected_measurement_column
        )

        axis.plot(
            dataframe[date_column],
            dataframe[measurement_column],
            marker="o",
            markersize=3.5,
            markeredgewidth=0,
            linewidth=1.2,
            linestyle="-",
            color="#1f77b4",
            label="Gevalideerde waterstand",
            zorder=2,
        )

        if statistics.removed_outliers:
            outlier_dates = [
                outlier.measurement_date
                for outlier in statistics.removed_outliers
            ]

            outlier_values = [
                outlier.measurement_value
                for outlier in statistics.removed_outliers
            ]

            axis.scatter(
                outlier_dates,
                outlier_values,
                marker="x",
                s=55,
                linewidths=1.8,
                color="#d32f2f",
                label=(
                    "Verwijderde uitschieters "
                    f"(n={statistics.removed_outlier_count})"
                ),
                zorder=5,
            )

        if statistics.ghg is not None:
            axis.axhline(
                y=statistics.ghg,
                color="#c62828",
                linewidth=1.2,
                linestyle="--",
                label=(
                    "GHG-proxy "
                    f"({format_nap_value(statistics.ghg)})"
                ),
                zorder=1,
            )

        if statistics.glg is not None:
            axis.axhline(
                y=statistics.glg,
                color="#1565c0",
                linewidth=1.2,
                linestyle="--",
                label=(
                    "GLG-proxy "
                    f"({format_nap_value(statistics.glg)})"
                ),
                zorder=1,
            )

        axis.set_title(
            f"Waterstanden peilfilter {filternummer} "
            f"(n={len(dataframe)})",
            fontsize=14,
            pad=12,
        )

        axis.set_xlabel("Datum")
        axis.set_ylabel("Waterstand (m NAP)")

        axis.grid(
            visible=True,
            which="major",
            linestyle="--",
            linewidth=0.5,
            alpha=0.7,
        )

        axis.legend(loc="best")

        axis.xaxis.set_major_formatter(
            mdates.DateFormatter("%Y-%m")
        )

        axis.xaxis.set_major_locator(
            mdates.AutoDateLocator(
                minticks=5,
                maxticks=10,
            )
        )

        figure.autofmt_xdate()

        if statistics.ghg is not None and statistics.glg is not None:
            summary_text = (
                f"GHG-proxy: {statistics.ghg:.2f} m NAP   |   "
                f"GLG-proxy: {statistics.glg:.2f} m NAP   |   "
                f"Referentiejaren: "
                f"{len(statistics.reference_years)}   |   "
                f"Uitschieters: "
                f"{statistics.removed_outlier_count}"
            )

            figure.text(
                0.5,
                0.015,
                summary_text,
                horizontalalignment="center",
                verticalalignment="bottom",
                fontsize=9,
                bbox={
                    "boxstyle": "round,pad=0.45",
                    "facecolor": "white",
                    "edgecolor": "gray",
                    "alpha": 0.95,
                },
            )

            figure.tight_layout(rect=(0, 0.075, 1, 1))
        else:
            figure.tight_layout()

        return figure

    def figure_to_png(self, figure: Figure) -> bytes:
        """Converteer een Matplotlib-figuur naar PNG-bytes."""

        buffer = BytesIO()

        try:
            figure.savefig(
                buffer,
                format="png",
                dpi=self.config.graph_dpi,
                bbox_inches="tight",
                facecolor="white",
            )

            png_bytes = buffer.getvalue()

            if not png_bytes:
                raise OSError(
                    "De gegenereerde grafiek is leeg."
                )

            return png_bytes
        finally:
            buffer.close()
            plt.close(figure)

    def create_png(
        self,
        dataframe: pd.DataFrame,
        filternummer: str,
        statistics: GroundwaterStatistics,
    ) -> bytes:
        """Genereer een volledige PNG-grafiek in het geheugen."""

        figure = self.create_figure(
            dataframe=dataframe,
            filternummer=filternummer,
            statistics=statistics,
        )

        return self.figure_to_png(figure)
