from __future__ import annotations

import logging
from dataclasses import dataclass, replace


@dataclass(frozen=True)
class AppConfig:
    """Centrale configuratie van de grondwaterapplicatie."""

    encodings_to_try: tuple[str, ...] = (
        "utf-8-sig",
        "utf-8",
        "cp1252",
        "latin-1",
        "iso-8859-1",
    )

    delimiter: str = ";"
    expected_date_column: str = "datum"
    expected_measurement_column: str = "meting NAP"
    hydrological_year_column: str = "hydrologisch_jaar"

    hydrological_year_start_month: int = 4
    minimum_measurements_per_year: int = 2
    outlier_threshold_meters: float = 0.5

    graph_dpi: int = 200
    plot_width_inches: float = 10.5
    plot_height_inches: float = 6.0

    pdf_margin_mm: float = 10.0
    pdf_bottom_margin_mm: float = 18.0

    output_suffix: str = "_rapport.pdf"
    log_level: int = logging.INFO

    csv_na_values: tuple[str, ...] = (
        "",
        "NA",
        "N/A",
        "null",
        "None",
        "-",
    )

    maximum_upload_size_mb: int = 100

    def with_runtime_settings(
        self,
        hydrological_year_start_month: int,
        minimum_measurements_per_year: int,
        outlier_threshold_meters: float,
    ) -> AppConfig:
        """
        Maak een nieuwe configuratie met instellingen uit de Streamlit-interface.

        Omdat de dataclass frozen is, wordt de oorspronkelijke configuratie
        niet gewijzigd.
        """

        return replace(
            self,
            hydrological_year_start_month=hydrological_year_start_month,
            minimum_measurements_per_year=minimum_measurements_per_year,
            outlier_threshold_meters=outlier_threshold_meters,
        )


DEFAULT_CONFIG = AppConfig()
