from __future__ import annotations

import hashlib
import io
import logging
import zipfile
from collections.abc import Mapping
from datetime import date
from pathlib import Path
from typing import Any, Sequence

import altair as alt
import pandas as pd
import streamlit as st

from config import DEFAULT_CONFIG, AppConfig
from models import (
    ExcludedPeriod,
    GroundwaterStatistics,
    ProcessingResult,
    UploadedCsvFile,
)
from processing_service import GroundwaterProcessingService
from utilities import configure_logging


LOGGER = logging.getLogger(__name__)

PROCESSING_RESULTS_STATE_KEY = "processing_results"
PROCESSING_SIGNATURE_STATE_KEY = "processing_signature"
EXCLUDED_PERIODS_STATE_KEY = "excluded_periods"

MONTH_NAMES: dict[int, str] = {
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
}


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
        "Analyseer grondwatermetingen, sluit desgewenst periodes uit, "
        "detecteer uitschieters en genereer een PDF-rapport met "
        "GHG- en GLG-proxywaarden."
    )


def render_sidebar() -> AppConfig:
    """Toon instellingen en retourneer de runtimeconfiguratie."""

    st.sidebar.header("Analyse-instellingen")

    start_month = st.sidebar.selectbox(
        "Startmaand hydrologisch jaar",
        options=list(MONTH_NAMES),
        index=DEFAULT_CONFIG.hydrological_year_start_month - 1,
        format_func=lambda month: MONTH_NAMES[month],
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

    log_level = (
        logging.DEBUG
        if debug_logging
        else DEFAULT_CONFIG.log_level
    )
    configure_logging(log_level)

    st.sidebar.divider()

    st.sidebar.info(
        "De berekende GHG- en GLG-waarden zijn proxywaarden "
        "en vormen geen formele GxG-bepaling."
    )

    return DEFAULT_CONFIG.with_runtime_settings(
        hydrological_year_start_month=int(start_month),
        minimum_measurements_per_year=int(minimum_measurements),
        outlier_threshold_meters=float(outlier_threshold),
    )


def initialize_session_state() -> None:
    """Initialiseer resultaten in de Streamlit-sessie."""

    if PROCESSING_RESULTS_STATE_KEY not in st.session_state:
        st.session_state[PROCESSING_RESULTS_STATE_KEY] = []

    if PROCESSING_SIGNATURE_STATE_KEY not in st.session_state:
        st.session_state[PROCESSING_SIGNATURE_STATE_KEY] = None

    if EXCLUDED_PERIODS_STATE_KEY not in st.session_state:
        st.session_state[EXCLUDED_PERIODS_STATE_KEY] = []


def create_content_hash(content: bytes) -> str:
    """Maak een stabiele SHA-256-hash van bestandsinhoud."""

    return hashlib.sha256(content).hexdigest()


def build_processing_signature(
    uploaded_files: Sequence[Any],
    config: AppConfig,
    excluded_periods: tuple[ExcludedPeriod, ...] = (),
) -> tuple[
    tuple[tuple[str, int, str], ...],
    tuple[object, ...],
    tuple[tuple[str, str], ...],
]:
    """
    Maak een handtekening van uploads en analyse-instellingen.

    De handtekening wordt gebruikt om te bepalen of eerder
    berekende resultaten nog bij de huidige bestanden en
    instellingen horen.
    """

    file_signature = tuple(
        (
            uploaded_file.name,
            len(uploaded_file.getvalue()),
            create_content_hash(uploaded_file.getvalue()),
        )
        for uploaded_file in uploaded_files
    )

    config_signature: tuple[object, ...] = (
        config.hydrological_year_start_month,
        config.minimum_measurements_per_year,
        config.outlier_threshold_meters,
        config.delimiter,
        config.expected_date_column,
        config.expected_measurement_column,
    )

    period_signature = tuple(
        (
            period.start_date.strftime("%Y-%m-%d"),
            period.end_date.strftime("%Y-%m-%d"),
        )
        for period in excluded_periods
    )

    return file_signature, config_signature, period_signature


@st.cache_data(show_spinner=False)
def load_preview_data(
    filename: str,
    content: bytes,
    config: AppConfig,
) -> pd.DataFrame:
    """Parse en cache een upload voor de grafiekselectie."""

    processing_service = GroundwaterProcessingService(config)
    _, dataframe = processing_service.load_uploaded_data(
        UploadedCsvFile(filename=filename, content=content)
    )
    return dataframe


def chart_selection_period(selection: Any) -> tuple[date, date] | None:
    """Converteer een Altair-x-asselectie naar inclusieve kalenderdatums."""

    if not isinstance(selection, Mapping):
        return None

    bounds = selection.get("x")
    if isinstance(bounds, Mapping):
        bounds = next(
            (
                bounds.get(key)
                for key in ("value", "domain", "extent")
                if bounds.get(key) is not None
            ),
            None,
        )

    if bounds is None:
        bounds = selection.get("datum")

    if (
        not isinstance(bounds, (list, tuple))
        or len(bounds) != 2
        or any(isinstance(bound, (list, tuple, Mapping)) for bound in bounds)
    ):
        return None

    parsed_dates: list[date] = []
    for bound in bounds:
        if isinstance(bound, (int, float)):
            unit = "ms" if abs(bound) >= 100_000_000_000 else "s"
            timestamp = pd.to_datetime(bound, unit=unit)
        else:
            timestamp = pd.Timestamp(bound)

        if timestamp.tzinfo is not None:
            timestamp = timestamp.tz_convert(None)
        parsed_dates.append(timestamp.date())

    return min(parsed_dates), max(parsed_dates)


def render_excluded_period_controls(
    uploaded_files: Sequence[Any],
    config: AppConfig,
) -> tuple[ExcludedPeriod, ...]:
    """Toon handmatige en grafische invoer voor uitsluitingsperiodes."""

    stored_periods: list[tuple[date, date]] = st.session_state[
        EXCLUDED_PERIODS_STATE_KEY
    ]

    with st.expander(
        "Periodes buiten beschouwing laten",
        expanded=bool(stored_periods),
    ):
        if "excluded_period_start" not in st.session_state:
            st.session_state["excluded_period_start"] = date.today()
        if "excluded_period_end" not in st.session_state:
            st.session_state["excluded_period_end"] = date.today()

        st.caption(
            "Periodes zijn inclusief begin- en einddatum. "
            "Metingen blijven zichtbaar in de grafiek, maar tellen "
            "niet mee voor uitschieterfiltering en GHG/GLG."
        )

        chart_period: tuple[date, date] | None = None
        chart_add_button_key: str | None = None
        if uploaded_files:
            st.markdown("**Of selecteer een periode in de grafiek**")
            st.caption(
                "Sleep over het gewenste tijdvak en voeg de selectie "
                "daarna toe."
            )
            file_index = st.selectbox(
                "Meetreeks voor selectie",
                options=range(len(uploaded_files)),
                format_func=lambda index: uploaded_files[index].name,
                key="excluded_period_preview_file",
            )
            chart_add_button_key = (
                f"add_chart_excluded_period_{file_index}"
            )
            selected_upload = uploaded_files[file_index]

            try:
                preview_dataframe = load_preview_data(
                    filename=selected_upload.name,
                    content=selected_upload.getvalue(),
                    config=config,
                )
                date_column = config.expected_date_column
                measurement_column = config.expected_measurement_column
                brush = alt.selection_interval(
                    name="exclude_period",
                    encodings=["x"],
                )
                chart = (
                    alt.Chart(preview_dataframe)
                    .mark_line(
                        point=alt.OverlayMarkDef(size=35),
                        color="#1f77b4",
                    )
                    .encode(
                        x=alt.X(
                            f"{date_column}:T",
                            title="Datum",
                        ),
                        y=alt.Y(
                            f"{measurement_column}:Q",
                            title="Waterstand (m NAP)",
                        ),
                        tooltip=[
                            alt.Tooltip(f"{date_column}:T", title="Datum"),
                            alt.Tooltip(
                                f"{measurement_column}:Q",
                                title="Waterstand (m NAP)",
                                format=".3f",
                            ),
                        ],
                    )
                    .add_params(brush)
                    .properties(height=300)
                )
                chart_event = st.altair_chart(
                    chart,
                    use_container_width=True,
                    on_select="rerun",
                    selection_mode="exclude_period",
                    key=f"excluded_period_chart_{file_index}",
                )
                chart_state = chart_event.get("selection", {})
                selected_chart_period = chart_selection_period(
                    chart_state.get("exclude_period")
                    if isinstance(chart_state, Mapping)
                    else None
                )
                cached_period_key = (
                    f"excluded_period_chart_selection_{file_index}"
                )
                if selected_chart_period is not None:
                    st.session_state[cached_period_key] = (
                        selected_chart_period
                    )
                chart_period = selected_chart_period or st.session_state.get(
                    cached_period_key
                )

                if chart_period is not None:
                    applied_selection_key = (
                        f"excluded_period_applied_selection_{file_index}"
                    )
                    if st.session_state.get(
                        applied_selection_key
                    ) != chart_period:
                        st.session_state["excluded_period_start"] = (
                            chart_period[0]
                        )
                        st.session_state["excluded_period_end"] = (
                            chart_period[1]
                        )
                        st.session_state[applied_selection_key] = (
                            chart_period
                        )
                    st.caption(
                        "Geselecteerd: "
                        f"{chart_period[0]:%d-%m-%Y} t/m "
                        f"{chart_period[1]:%d-%m-%Y}"
                    )

            except Exception as exc:
                st.warning(
                    f"De meetreeks kan niet voor selectie worden getoond: {exc}"
                )
        else:
            st.info(
                "Upload eerst een CSV om periodes via een grafiek te selecteren."
            )

        manual_column1, manual_column2 = st.columns(2)
        start_date = manual_column1.date_input(
            "Begindatum",
            key="excluded_period_start",
        )
        end_date = manual_column2.date_input(
            "Einddatum",
            key="excluded_period_end",
        )

        if st.button(
            "Handmatige periode toevoegen",
            key="add_manual_excluded_period",
        ):
            if start_date > end_date:
                st.error("De begindatum moet op of vóór de einddatum liggen.")
            else:
                period = (start_date, end_date)
                if period not in stored_periods:
                    stored_periods.append(period)

        if chart_add_button_key is not None and st.button(
            "Geselecteerde periode toevoegen",
            disabled=chart_period is None,
            key=chart_add_button_key,
        ) and chart_period is not None:
            if chart_period not in stored_periods:
                stored_periods.append(chart_period)

        if stored_periods:
            st.markdown("**Uitgesloten periodes**")
            for index, (period_start, period_end) in enumerate(
                stored_periods
            ):
                period_column, remove_column = st.columns([5, 1])
                period_column.write(
                    f"{period_start:%d-%m-%Y} t/m {period_end:%d-%m-%Y}"
                )
                if remove_column.button(
                    "Verwijderen",
                    key=f"remove_excluded_period_{index}",
                ):
                    stored_periods.pop(index)
                    st.rerun()

    return tuple(
        ExcludedPeriod(
            start_date=pd.Timestamp(period_start),
            end_date=pd.Timestamp(period_end),
        )
        for period_start, period_end in stored_periods
    )


def build_uploaded_models(
    uploaded_files: Sequence[Any],
) -> list:
    """Converteer Streamlit-uploads naar interne datamodellen."""

    return [
        UploadedCsvFile(
            filename=uploaded_file.name,
            content=uploaded_file.getvalue(),
        )
        for uploaded_file in uploaded_files
    ]


def create_failed_processing_result(
    source_filename: str,
    message: str,
) -> ProcessingResult:
    """
    Maak een mislukt verwerkingsresultaat.

    Deze functie gaat ervan uit dat ProcessingResult minimaal
    de velden success, message en source_filename vereist en
    dat de overige velden optioneel zijn.
    """

    return ProcessingResult(
        success=False,
        message=message,
        source_filename=source_filename,
        filternummer=None,
        dataframe=None,
        statistics=None,
        plot_png=None,
        pdf_bytes=None,
        output_filename=None,
    )


def process_uploaded_models(
    uploaded_models: Sequence[UploadedCsvFile],
    processing_service: GroundwaterProcessingService,
    excluded_periods: tuple[ExcludedPeriod, ...] = (),
) -> list:
    """
    Verwerk alle uploads en isoleer fouten per bestand.

    Een onverwachte fout in één bestand voorkomt niet dat de
    overige bestanden worden verwerkt.
    """

    results: list[ProcessingResult] = []
    total_files = len(uploaded_models)

    progress_bar = st.progress(
        0.0,
        text="Analyse wordt gestart.",
    )

    try:
        for index, uploaded_model in enumerate(
            uploaded_models,
            start=1,
        ):
            progress_bar.progress(
                (index - 1) / total_files,
                text=f"Verwerken van {uploaded_model.filename}...",
            )

            try:
                result = processing_service.process_uploaded_file(
                    uploaded_model,
                    excluded_periods=excluded_periods,
                )
            except Exception as exception:
                LOGGER.exception(
                    "Onverwachte fout tijdens verwerking van %s.",
                    uploaded_model.filename,
                )

                result = create_failed_processing_result(
                    source_filename=uploaded_model.filename,
                    message=(
                        "Er is een onverwachte fout opgetreden "
                        f"tijdens de verwerking: {exception}"
                    ),
                )

            results.append(result)

            progress_bar.progress(
                index / total_files,
                text=(
                    f"{index} van {total_files} "
                    "bestand(en) verwerkt."
                ),
            )
    finally:
        progress_bar.empty()

    return results


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

    rows: list[dict[str, object]] = [
        {
            "Datum": outlier.measurement_date.strftime("%d-%m-%Y"),
            "Hydrologisch jaar": outlier.hydrological_year,
            "Meting (m NAP)": outlier.measurement_value,
            "Jaargemiddelde (m NAP)": outlier.yearly_mean,
            "Absolute afwijking (m)": outlier.absolute_deviation,
        }
        for outlier in statistics.removed_outliers
    ]

    return pd.DataFrame(rows)


def create_unique_zip_filename(
    requested_filename: str,
    used_filenames: set[str],
) -> str:
    """Maak een unieke bestandsnaam voor gebruik in een ZIP-bestand."""

    original_path = Path(requested_filename)
    stem = original_path.stem or "grondwaterrapport"
    suffix = original_path.suffix or ".pdf"

    candidate = f"{stem}{suffix}"
    sequence_number = 2

    while candidate.lower() in used_filenames:
        candidate = f"{stem}_{sequence_number}{suffix}"
        sequence_number += 1

    used_filenames.add(candidate.lower())
    return candidate


def create_zip_file(
    results: Sequence[ProcessingResult],
) -> bytes:
    """Maak een ZIP-bestand met alle succesvolle PDF-rapporten."""

    zip_buffer = io.BytesIO()
    used_filenames: set[str] = set()

    with zipfile.ZipFile(
        zip_buffer,
        mode="w",
        compression=zipfile.ZIP_DEFLATED,
    ) as zip_file:
        for result in results:
            if not (
                result.success
                and result.pdf_bytes
                and result.output_filename
            ):
                continue

            zip_filename = create_unique_zip_filename(
                requested_filename=result.output_filename,
                used_filenames=used_filenames,
            )

            zip_file.writestr(
                zip_filename,
                result.pdf_bytes,
            )

    return zip_buffer.getvalue()


def create_validated_csv_filename(
    source_filename: str,
) -> str:
    """Maak een veilige naam voor de gevalideerde CSV-download."""

    source_path = Path(source_filename)
    source_stem = source_path.stem or "grondwaterdata"
    return f"{source_stem}_gevalideerd.csv"


def render_summary_metrics(
    statistics: GroundwaterStatistics,
) -> None:
    """Toon de belangrijkste analyseresultaten."""

    column1, column2, column3, column4 = st.columns(4)
    excluded_count = (
        statistics.excluded_period_measurement_count
        + statistics.removed_outlier_count
    )

    column1.metric(
        "Metingen voor filtering",
        statistics.original_measurement_count,
    )

    column2.metric(
        "Metingen na filtering",
        statistics.filtered_measurement_count,
        delta=(
            -excluded_count
            if excluded_count
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

    if statistics.excluded_periods:
        periods = ", ".join(
            (
                f"{period.start_date:%d-%m-%Y} t/m "
                f"{period.end_date:%d-%m-%Y}"
            )
            for period in statistics.excluded_periods
        )
        st.caption(
            f"{statistics.excluded_period_measurement_count} meting(en) "
            f"buiten de analyse door uitgesloten periode(s): {periods}."
        )


def render_data_tab(
    result: ProcessingResult,
    result_index: int,
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
        file_name=create_validated_csv_filename(
            result.source_filename
        ),
        mime="text/csv",
        key=(
            f"validated_{result_index}_"
            f"{result.source_filename}"
        ),
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
                "Hoogste stand (m NAP)":
                    st.column_config.NumberColumn(
                        format="%.3f",
                    ),
                "Laagste stand (m NAP)":
                    st.column_config.NumberColumn(
                        format="%.3f",
                    ),
            },
        )

    if statistics.excluded_years:
        st.warning(
            "Uitgesloten hydrologische jaren: "
            + ", ".join(map(str, statistics.excluded_years))
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
            "Meting (m NAP)":
                st.column_config.NumberColumn(
                    format="%.3f",
                ),
            "Jaargemiddelde (m NAP)":
                st.column_config.NumberColumn(
                    format="%.3f",
                ),
            "Absolute afwijking (m)":
                st.column_config.NumberColumn(
                    format="%.3f",
                ),
        },
    )


def render_summary_tab(
    result: ProcessingResult,
    statistics: GroundwaterStatistics,
) -> None:
    """Toon de samenvatting van een succesvol resultaat."""

    summary_data = {
        "Eigenschap": [
            "Bestandsnaam",
            "Filternummer",
            "Metingen uitgesloten op periode",
            "Uitgesloten periodes",
            "GHG-proxy",
            "GLG-proxy",
            "Referentiejaren",
            "Uitgesloten jaren",
            "Verwijderde uitschieters",
        ],
        "Waarde": [
            result.source_filename,
            result.filternummer or "Onbekend",
            str(statistics.excluded_period_measurement_count),
            (
                "; ".join(
                    (
                        f"{period.start_date:%d-%m-%Y} t/m "
                        f"{period.end_date:%d-%m-%Y}"
                    )
                    for period in statistics.excluded_periods
                )
                if statistics.excluded_periods
                else "Geen"
            ),
            format_optional_nap(statistics.ghg),
            format_optional_nap(statistics.glg),
            (
                ", ".join(map(str, statistics.reference_years))
                if statistics.reference_years
                else "Geen"
            ),
            (
                ", ".join(map(str, statistics.excluded_years))
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
                "Grondwaterverloop voor peilfilter "
                f"{result.filternummer or 'onbekend'}"
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
        render_summary_tab(
            result=result,
            statistics=statistics,
        )

    with tab_yearly:
        render_yearly_tab(statistics)

    with tab_outliers:
        render_outlier_tab(statistics)

    with tab_data:
        render_data_tab(
            result=result,
            result_index=result_index,
        )

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
    else:
        st.info(
            "Voor dit resultaat is geen PDF-rapport beschikbaar."
        )


def render_results(
    results: Sequence[ProcessingResult],
) -> None:
    """Toon alle verwerkingsresultaten."""

    if not results:
        return

    successful_results = [
        result
        for result in results
        if result.success
    ]

    failed_results = [
        result
        for result in results
        if not result.success
    ]

    results_with_pdf = [
        result
        for result in successful_results
        if result.pdf_bytes and result.output_filename
    ]

    st.divider()
    st.header("Analyseresultaten")

    summary_column1, summary_column2, summary_column3 = st.columns(3)

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

    if len(results_with_pdf) > 1:
        zip_bytes = create_zip_file(results_with_pdf)

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


def render_expected_csv_structure() -> None:
    """Toon een voorbeeld van de verwachte CSV-structuur."""

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
        render_expected_csv_structure()
        return

    total_size_bytes = sum(
        len(uploaded_file.getvalue())
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
        excluded_periods=render_excluded_period_controls(
            uploaded_files=uploaded_files,
            config=config,
        ),
    )

    stored_signature = st.session_state[
        PROCESSING_SIGNATURE_STATE_KEY
    ]

    signature_changed = stored_signature != current_signature

    if signature_changed and stored_signature is not None:
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
        uploaded_models = build_uploaded_models(uploaded_files)

        processing_service = GroundwaterProcessingService(config)

        results = process_uploaded_models(
            uploaded_models=uploaded_models,
            processing_service=processing_service,
            excluded_periods=tuple(
                ExcludedPeriod(
                    start_date=pd.Timestamp(period_start),
                    end_date=pd.Timestamp(period_end),
                )
                for period_start, period_end in st.session_state[
                    EXCLUDED_PERIODS_STATE_KEY
                ]
            ),
        )

        st.session_state[
            PROCESSING_RESULTS_STATE_KEY
        ] = results

        st.session_state[
            PROCESSING_SIGNATURE_STATE_KEY
        ] = current_signature

        signature_changed = False

    if not signature_changed:
        render_results(
            st.session_state[PROCESSING_RESULTS_STATE_KEY]
        )


if __name__ == "__main__":
    main()
