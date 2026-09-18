from __future__ import annotations

import io
import logging
import zipfile

import pandas as pd
import streamlit as st

from config import DEFAULT_CONFIG, AppConfig
from models import (
    GroundwaterStatistics,
    ProcessingResult,
    UploadedCsvFile,
)
from processing_service import GroundwaterProcessingService
from utilities import configure_logging


def configure_page() -> None:
    """Configureer de algemene Streamlit-pagina."""

    st.set_page_config(
        page_title="Grondwateranalyse",
        page_icon="💧",
        layout="wide",
        initial_sidebar_state="expanded",
    )

    st.title("💧 Grondwateranalyse")
    st.caption(
        "Analyseer grondwatermetingen, detecteer uitschieters "
        "en genereer een PDF-rapport met GHG- en GLG-proxywaarden."
    )


def render_sidebar() -> AppConfig:
    """Toon instellingen en retourneer de runtimeconfiguratie."""

    st.sidebar.header("Analyse-instellingen")

    start_month = st.sidebar.selectbox(
        "Startmaand hydrologisch jaar",
        options=list(range(1, 13)),
        index=DEFAULT_CONFIG.hydrological_year_start_month - 1,
        format_func=lambda month: {
            1: "Januari",
            2: "Februari",
            3: "Maart",
            4: "April",
            5: "Mei",
            6: "Juni",
            7: "Juli",
            8: "Augustus",
            9: "September",
            10: "Oktober",
            11: "November",
            12: "December",
        }[month],
        help=(
            "Een hydrologisch jaar krijgt het kalenderjaar van "
            "de geselecteerde startmaand."
        ),
    )

    minimum_measurements = st.sidebar.number_input(
        "Minimumaantal metingen per hydrologisch jaar",
        min_value=1,
        max_value=365,
        value=DEFAULT_CONFIG.minimum_measurements_per_year,
        step=1,
        help=(
            "Jaren met minder metingen worden niet meegenomen "
            "in de GHG- en GLG-proxy."
        ),
    )

    outlier_threshold = st.sidebar.number_input(
        "Uitschieterdrempel in meters",
        min_value=0.0,
        max_value=100.0,
        value=DEFAULT_CONFIG.outlier_threshold_meters,
        step=0.05,
        format="%.2f",
        help=(
            "Een meting wordt als uitschieter beschouwd wanneer "
            "de absolute afwijking ten opzichte van het "
            "jaargemiddelde groter is dan deze waarde."
        ),
    )

    debug_logging = st.sidebar.checkbox(
        "Debuglogging activeren",
        value=False,
    )

    configure_logging(
        logging.DEBUG
        if debug_logging
        else DEFAULT_CONFIG.log_level
    )

    st.sidebar.divider()

    st.sidebar.info(
        "De berekende GHG- en GLG-waarden zijn proxywaarden "
        "en vormen geen formele GxG-bepaling."
    )

    return DEFAULT_CONFIG.with_runtime_settings(
        hydrological_year_start_month=int(start_month),
        minimum_measurements_per_year=int(
            minimum_measurements
        ),
        outlier_threshold_meters=float(outlier_threshold),
    )


def initialize_session_state() -> None:
    """Initialiseer resultaten in de Streamlit-sessie."""

    if "processing_results" not in st.session_state:
        st.session_state.processing_results = []

    if "processing_signature" not in st.session_state:
        st.session_state.processing_signature = None


def build_processing_signature(
    uploaded_files: list,
    config: AppConfig,
) -> tuple:
    """
    Maak een eenvoudige handtekening van uploads en instellingen.

    Hiermee kan worden herkend of eerder berekende resultaten nog
    bij de huidige instellingen horen.
    """

    file_signature = tuple(
        (
            uploaded_file.name,
            uploaded_file.size,
            hash(uploaded_file.getvalue()),
        )
        for uploaded_file in uploaded_files
    )

    config_signature = (
        config.hydrological_year_start_month,
        config.minimum_measurements_per_year,
        config.outlier_threshold_meters,
        config.delimiter,
    )

    return file_signature, config_signature


def build_uploaded_models(
    uploaded_files: list,
) -> list"""Converteer Streamlit-uploads naar interne datamodellen."""

    return [
        UploadedCsvFile(
            filename=uploaded_file.name,
            content=uploaded_file.getvalue(),
        )
        for uploaded_file in uploaded_files
    ]


def format_optional_nap(value: float | None) -> str:
    """Formatteer een optionele NAP-waarde."""

    if value is None:
        return "Niet berekend"

    return f"{value:.2f} m NAP"


def create_yearly_dataframe(
    statistics: GroundwaterStatistics,
) -> pd.DataFrame:
    """Maak een tabel met jaarstatistieken voor Streamlit."""

    rows: list[dict[str, object]] = []

    for year in statistics.reference_years:
        rows.append(
            {
                "Hydrologisch jaar": year,
                "Aantal metingen": int(
                    statistics.yearly_count.loc[year]
                ),
                "Hoogste stand (m NAP)": float(
                    statistics.yearly_max.loc[year]
                ),
                "Laagste stand (m NAP)": float(
                    statistics.yearly_min.loc[year]
                ),
            }
        )

    return pd.DataFrame(rows)


def create_outlier_dataframe(
    statistics: GroundwaterStatistics,
) -> pd.DataFrame:
    """Maak een tabel van verwijderde uitschieters."""

    rows = [
        {
            "Datum": outlier.measurement_date.strftime(
                "%d-%m-%Y"
            ),
            "Hydrologisch jaar": outlier.hydrological_year,
            "Meting (m NAP)": outlier.measurement_value,
            "Jaargemiddelde (m NAP)": outlier.yearly_mean,
            "Absolute afwijking (m)": (
                outlier.absolute_deviation
            ),
        }
        for outlier in statistics.removed_outliers
    ]

    return pd.DataFrame(rows)


def create_zip_file(
    results: list[ProcessingResult],
) -> bytes:
    """Maak een ZIP-bestand met alle succesvolle PDF-rapporten."""

    zip_buffer = io.BytesIO()

    with zipfile.ZipFile(
        zip_buffer,
        mode="w",
        compression=zipfile.ZIP_DEFLATED,
    ) as zip_file:
        for result in results:
            if (
                result.success
                and result.pdf_bytes
                and result.output_filename
            ):
                zip_file.writestr(
                    result.output_filename,
                    result.pdf_bytes,
                )

    return zip_buffer.getvalue()


def render_summary_metrics(
    statistics: GroundwaterStatistics,
) -> None:
    """Toon de belangrijkste analyseresultaten."""

    column1, column2, column3, column4 = st.columns(4)

    column1.metric(
        "Geldige metingen",
        statistics.original_measurement_count,
    )

    column2.metric(
        "Metingen na filtering",
        statistics.filtered_measurement_count,
        delta=(
            -statistics.removed_outlier_count
            if statistics.removed_outlier_count
            else None
        ),
        delta_color="inverse",
    )

    column3.metric(
        "GHG-proxy",
        format_optional_nap(statistics.ghg),
    )

    column4.metric(
        "GLG-proxy",
        format_optional_nap(statistics.glg),
    )


def render_data_tab(
    result: ProcessingResult,
) -> None:
    """Toon gevalideerde brondata."""

    if result.dataframe is None:
        st.info("Geen gevalideerde data beschikbaar.")
        return

    st.dataframe(
        result.dataframe,
        use_container_width=True,
        hide_index=True,
    )

    csv_bytes = result.dataframe.to_csv(
        index=False,
        sep=";",
        date_format="%d-%m-%Y",
    ).encode("utf-8-sig")

    st.download_button(
        label="Download gevalideerde data als CSV",
        data=csv_bytes,
        file_name=(
            f"{result.source_filename.rsplit('.', 1)[0]}"
            "_gevalideerd.csv"
        ),
        mime="text/csv",
        key=f"validated_{result.source_filename}",
    )


def render_yearly_tab(
    statistics: GroundwaterStatistics,
) -> None:
    """Toon hydrologische jaarstatistieken."""

    yearly_dataframe = create_yearly_dataframe(statistics)

    if yearly_dataframe.empty:
        st.info(
            "Er zijn geen hydrologische jaren met voldoende "
            "metingen beschikbaar."
        )
    else:
        st.dataframe(
            yearly_dataframe,
            use_container_width=True,
            hide_index=True,
            column_config={
                "Hoogste stand (m NAP)": st.column_config.NumberColumn(
                    format="%.3f"
                ),
                "Laagste stand (m NAP)": st.column_config.NumberColumn(
                    format="%.3f"
                ),
            },
        )

    if statistics.excluded_years:
        st.warning(
            "Uitgesloten hydrologische jaren: "
            + ", ".join(
                map(str, statistics.excluded_years)
            )
        )


def render_outlier_tab(
    statistics: GroundwaterStatistics,
) -> None:
    """Toon de verwijderde uitschieters."""

    outlier_dataframe = create_outlier_dataframe(statistics)

    if outlier_dataframe.empty:
        st.success("Er zijn geen uitschieters verwijderd.")
        return

    st.warning(
        f"{statistics.removed_outlier_count} uitschieter(s) "
        "zijn niet gebruikt voor de proxyberekening."
    )

    st.dataframe(
        outlier_dataframe,
        use_container_width=True,
        hide_index=True,
        column_config={
            "Meting (m NAP)": st.column_config.NumberColumn(
                format="%.3f"
            ),
            "Jaargemiddelde (m NAP)":
                st.column_config.NumberColumn(
                    format="%.3f"
                ),
            "Absolute afwijking (m)":
                st.column_config.NumberColumn(
                    format="%.3f"
                ),
        },
    )


def render_successful_result(
    result: ProcessingResult,
    result_index: int,
) -> None:
    """Toon één geslaagd verwerkingsresultaat."""

    if result.statistics is None:
        st.error(
            "Het resultaat bevat geen statistische gegevens."
        )
        return

    statistics = result.statistics

    st.success(result.message)

    render_summary_metrics(statistics)

    if result.plot_png:
        st.image(
            result.plot_png,
            caption=(
                f"Grondwaterverloop voor peilfilter "
                f"{result.filternummer}"
            ),
            use_container_width=True,
        )

    tab_summary, tab_yearly, tab_outliers, tab_data = st.tabs(
        [
            "Samenvatting",
            "Hydrologische jaren",
            "Uitschieters",
            "Gevalideerde data",
        ]
    )

    with tab_summary:
        summary_data = {
            "Eigenschap": [
                "Bestandsnaam",
                "Filternummer",
                "GHG-proxy",
                "GLG-proxy",
                "Referentiejaren",
                "Uitgesloten jaren",
                "Verwijderde uitschieters",
            ],
            "Waarde": [
                result.source_filename,
                result.filternummer or "Onbekend",
                format_optional_nap(statistics.ghg),
                format_optional_nap(statistics.glg),
                (
                    ", ".join(
                        map(str, statistics.reference_years)
                    )
                    if statistics.reference_years
                    else "Geen"
                ),
                (
                    ", ".join(
                        map(str, statistics.excluded_years)
                    )
                    if statistics.excluded_years
                    else "Geen"
                ),
                str(statistics.removed_outlier_count),
            ],
        }

        st.dataframe(
            pd.DataFrame(summary_data),
            use_container_width=True,
            hide_index=True,
        )

    with tab_yearly:
        render_yearly_tab(statistics)

    with tab_outliers:
        render_outlier_tab(statistics)

    with tab_data:
        render_data_tab(result)

    if (
        result.pdf_bytes is not None
        and result.output_filename is not None
    ):
        st.download_button(
            label="Download PDF-rapport",
            data=result.pdf_bytes,
            file_name=result.output_filename,
            mime="application/pdf",
            key=(
                f"pdf_{result_index}_"
                f"{result.source_filename}"
            ),
            type="primary",
        )


def render_results(
    results: list[ProcessingResult],
) -> None:
    """Toon alle verwerkingsresultaten."""

    if not results:
        return

    successful_results = [
        result for result in results if result.success
    ]

    failed_results = [
        result for result in results if not result.success
    ]

    st.divider()
    st.header("Analyseresultaten")

    summary_column1, summary_column2, summary_column3 = (
        st.columns(3)
    )

    summary_column1.metric(
        "Aangeleverde bestanden",
        len(results),
    )

    summary_column2.metric(
        "Succesvol verwerkt",
        len(successful_results),
    )

    summary_column3.metric(
        "Mislukt",
        len(failed_results),
    )

    if len(successful_results) > 1:
        zip_bytes = create_zip_file(successful_results)

        st.download_button(
            label="Download alle PDF-rapporten als ZIP",
            data=zip_bytes,
            file_name="grondwaterrapporten.zip",
            mime="application/zip",
            key="download_all_reports",
            type="primary",
        )

    for index, result in enumerate(results):
        status_icon = "✅" if result.success else "❌"

        with st.expander(
            f"{status_icon} {result.source_filename}",
            expanded=len(results) == 1,
        ):
            if result.success:
                render_successful_result(
                    result=result,
                    result_index=index,
                )
            else:
                st.error(
                    f"Verwerking mislukt: {result.message}"
                )


def main() -> None:
    """Start de Streamlit-applicatie."""

    configure_page()
    initialize_session_state()

    config = render_sidebar()

    st.subheader("CSV-bestanden uploaden")

    uploaded_files = st.file_uploader(
        "Selecteer één of meerdere CSV-bestanden",
        type=["csv"],
        accept_multiple_files=True,
        help=(
            "De applicatie zoekt automatisch naar de kolommen "
            f"'{config.expected_date_column}' en "
            f"'{config.expected_measurement_column}'."
        ),
    )

    if not uploaded_files:
        st.info(
            "Upload één of meerdere CSV-bestanden om de analyse "
            "te starten."
        )

        with st.expander("Verwachte CSV-structuur"):
            st.code(
                """PB-001
datum;meting NAP
01-01-2024;1,23
15-01-2024;1,18
01-02-2024;1,30
""",
                language="text",
            )

        return

    total_size_bytes = sum(
        uploaded_file.size
        for uploaded_file in uploaded_files
    )

    total_size_mb = total_size_bytes / (1024 * 1024)

    st.caption(
        f"{len(uploaded_files)} bestand(en) geselecteerd, "
        f"totaal {total_size_mb:.2f} MB."
    )

    current_signature = build_processing_signature(
        uploaded_files=uploaded_files,
        config=config,
    )

    signature_changed = (
        st.session_state.processing_signature
        != current_signature
    )

    if signature_changed:
        st.warning(
            "De bestanden of analyse-instellingen zijn gewijzigd. "
            "Klik opnieuw op 'Analyse starten' om de resultaten "
            "bij te werken."
        )

    analyze_button = st.button(
        "Analyse starten",
        type="primary",
        use_container_width=True,
    )

    if analyze_button:
        uploaded_models = build_uploaded_models(
            uploaded_files
        )

        processing_service = (
            GroundwaterProcessingService(config)
        )

        progress_bar = st.progress(
            0,
            text="Analyse wordt gestart.",
        )

        results: list[ProcessingResult] = []
        total_files = len(uploaded_models)

        for index, uploaded_model in enumerate(
            uploaded_models,
            start=1,
        ):
            progress_bar.progress(
                (index - 1) / total_files,
                text=(
                    f"Verwerken van "
                    f"{uploaded_model.filename}..."
                ),
            )

            result = (
                processing_service.process_uploaded_file(
                    uploaded_model
                )
            )

            results.append(result)

            progress_bar.progress(
                index / total_files,
                text=(
                    f"{index} van {total_files} "
                    "bestand(en) verwerkt."
                ),
            )

        progress_bar.empty()

        st.session_state.processing_results = results
        st.session_state.processing_signature = (
            current_signature
        )

    render_results(
        st.session_state.processing_results
    )


if __name__ == "__main__":
    main()
