from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Optional

import pandas as pd
from fpdf import FPDF, XPos, YPos

from config import AppConfig
from models import GroundwaterStatistics
from utilities import encode_for_pdf


class PDFReport(FPDF):
    """PDF-rapport met vaste kop- en voettekst."""

    def __init__(
        self,
        filternummer: str,
        config: AppConfig,
    ) -> None:
        super().__init__(
            orientation="P",
            unit="mm",
            format="A4",
        )

        self.config = config
        self.filternummer = encode_for_pdf(filternummer)

        self.set_margins(
            config.pdf_margin_mm,
            config.pdf_margin_mm,
            config.pdf_margin_mm,
        )

        self.set_auto_page_break(
            auto=True,
            margin=config.pdf_bottom_margin_mm,
        )

        self.set_title(
            encode_for_pdf(
                f"Waterstanden peilfilter {filternummer}"
            )
        )

        self.set_author("Grondwaterrapportage")

    @property
    def usable_width(self) -> float:
        """Geef de beschikbare breedte tussen de paginamarges."""

        return self.w - self.l_margin - self.r_margin

    def header(self) -> None:
        """Plaats de rapportkop."""

        self.set_font("Helvetica", "B", 15)

        self.cell(
            0,
            9,
            f"Waterstanden peilfilter: {self.filternummer}",
            border=0,
            new_x=XPos.LMARGIN,
            new_y=YPos.NEXT,
            align="C",
        )

        self.ln(3)

    def footer(self) -> None:
        """Plaats het paginanummer."""

        self.set_y(-15)
        self.set_font("Helvetica", "I", 8)
        self.set_text_color(90, 90, 90)

        self.cell(
            0,
            10,
            f"Pagina {self.page_no()}",
            border=0,
            new_x=XPos.RIGHT,
            new_y=YPos.TOP,
            align="C",
        )

        self.set_text_color(0, 0, 0)

    def section_title(self, title: str) -> None:
        """Schrijf een sectietitel."""

        self.set_font("Helvetica", "B", 11)
        self.set_fill_color(240, 240, 240)

        self.cell(
            0,
            8,
            encode_for_pdf(title),
            border=0,
            new_x=XPos.LMARGIN,
            new_y=YPos.NEXT,
            fill=True,
        )

        self.ln(2)


class PdfService:
    """Service voor het opbouwen van PDF-grondwaterrapporten."""

    def __init__(self, config: AppConfig) -> None:
        self.config = config

    def add_summary(
        self,
        pdf: PDFReport,
        dataframe: pd.DataFrame,
        statistics: GroundwaterStatistics,
    ) -> None:
        """Voeg een compacte analysesamenvatting toe."""

        if dataframe.empty:
            raise ValueError(
                "De samenvatting kan niet worden gemaakt "
                "zonder metingen."
            )

        pdf.section_title("Samenvatting")

        date_column = self.config.expected_date_column
        first_date = dataframe[date_column].min()
        last_date = dataframe[date_column].max()

        summary_rows: list[tuple[str, str]] = [
            (
                "Aantal geldige metingen",
                str(len(dataframe)),
            ),
            (
                "Aantal metingen na uitschieterfiltering",
                str(statistics.filtered_measurement_count),
            ),
            (
                "Aantal verwijderde uitschieters",
                str(statistics.removed_outlier_count),
            ),
            (
                "Eerste meetdatum",
                first_date.strftime("%d-%m-%Y"),
            ),
            (
                "Laatste meetdatum",
                last_date.strftime("%d-%m-%Y"),
            ),
            (
                "Gebruikte hydrologische jaren",
                (
                    ", ".join(
                        map(str, statistics.reference_years)
                    )
                    if statistics.reference_years
                    else "Geen"
                ),
            ),
        ]

        if statistics.ghg is not None:
            summary_rows.append(
                (
                    "GHG-proxy",
                    f"{statistics.ghg:.2f} m NAP",
                )
            )

        if statistics.glg is not None:
            summary_rows.append(
                (
                    "GLG-proxy",
                    f"{statistics.glg:.2f} m NAP",
                )
            )

        if statistics.excluded_years:
            summary_rows.append(
                (
                    "Uitgesloten hydrologische jaren",
                    ", ".join(
                        map(str, statistics.excluded_years)
                    ),
                )
            )

        label_width = pdf.usable_width * 0.37
        value_width = pdf.usable_width - label_width

        for label, value in summary_rows:
            pdf.set_font("Helvetica", "B", 9)

            pdf.cell(
                label_width,
                7,
                encode_for_pdf(label),
                border=1,
                new_x=XPos.RIGHT,
                new_y=YPos.TOP,
            )

            pdf.set_font("Helvetica", "", 9)

            pdf.cell(
                value_width,
                7,
                encode_for_pdf(value),
                border=1,
                new_x=XPos.LMARGIN,
                new_y=YPos.NEXT,
            )

        pdf.ln(4)

    @staticmethod
    def get_yearly_table_widths(
        pdf: PDFReport,
    ) -> tuple[float, float, float, float]:
        """Bereken kolombreedtes voor de jaartabel."""

        return (
            pdf.usable_width * 0.24,
            pdf.usable_width * 0.21,
            pdf.usable_width * 0.275,
            pdf.usable_width * 0.275,
        )

    def add_yearly_table_header(
        self,
        pdf: PDFReport,
    ) -> None:
        """Voeg de tabelkop voor hydrologische jaarwaarden toe."""

        headers = (
            "Hydrologisch jaar",
            "Aantal metingen",
            "Hoogste stand",
            "Laagste stand",
        )

        widths = self.get_yearly_table_widths(pdf)

        pdf.set_font("Helvetica", "B", 8)
        pdf.set_fill_color(225, 225, 225)

        for index, (header, width) in enumerate(
            zip(headers, widths)
        ):
            is_last = index == len(headers) - 1

            pdf.cell(
                width,
                8,
                encode_for_pdf(header),
                border=1,
                new_x=(
                    XPos.LMARGIN if is_last else XPos.RIGHT
                ),
                new_y=(
                    YPos.NEXT if is_last else YPos.TOP
                ),
                align="C",
                fill=True,
            )

    def ensure_yearly_table_space(
        self,
        pdf: PDFReport,
        required_height: float = 16.0,
    ) -> None:
        """Voeg zo nodig een nieuwe pagina toe voor de jaartabel."""

        if (
            pdf.get_y() + required_height
            > pdf.h - pdf.b_margin
        ):
            pdf.add_page()

            pdf.section_title(
                "Jaarlijkse hoogste en laagste standen "
                "(vervolg)"
            )

            self.add_yearly_table_header(pdf)

    def add_yearly_table(
        self,
        pdf: PDFReport,
        statistics: GroundwaterStatistics,
    ) -> None:
        """Voeg jaarlijkse hoogste en laagste standen toe."""

        pdf.section_title(
            "Jaarlijkse hoogste en laagste standen"
        )

        if (
            statistics.yearly_max.empty
            or statistics.yearly_min.empty
        ):
            pdf.set_font("Helvetica", "", 10)

            pdf.cell(
                0,
                9,
                "Geen bruikbare jaargegevens beschikbaar.",
                border=1,
                new_x=XPos.LMARGIN,
                new_y=YPos.NEXT,
                align="C",
            )

            return

        self.add_yearly_table_header(pdf)
        widths = self.get_yearly_table_widths(pdf)

        for year in statistics.reference_years:
            self.ensure_yearly_table_space(pdf)

            row_values = (
                str(year),
                str(int(statistics.yearly_count.loc[year])),
                (
                    f"{float(statistics.yearly_max.loc[year]):.2f} "
                    "m NAP"
                ),
                (
                    f"{float(statistics.yearly_min.loc[year]):.2f} "
                    "m NAP"
                ),
            )

            pdf.set_font("Helvetica", "", 8)

            for index, (value, width) in enumerate(
                zip(row_values, widths)
            ):
                is_last = index == len(row_values) - 1

                pdf.cell(
                    width,
                    7,
                    encode_for_pdf(value),
                    border=1,
                    new_x=(
                        XPos.LMARGIN
                        if is_last
                        else XPos.RIGHT
                    ),
                    new_y=(
                        YPos.NEXT
                        if is_last
                        else YPos.TOP
                    ),
                    align="C",
                )

    @staticmethod
    def get_outlier_table_widths(
        pdf: PDFReport,
    ) -> tuple[float, float, float, float, float]:
        """Bereken kolombreedtes voor de uitschietertabel."""

        return (
            pdf.usable_width * 0.18,
            pdf.usable_width * 0.18,
            pdf.usable_width * 0.20,
            pdf.usable_width * 0.22,
            pdf.usable_width * 0.22,
        )

    def add_outlier_table_header(
        self,
        pdf: PDFReport,
    ) -> None:
        """Voeg de kop van de uitschietertabel toe."""

        headers = (
            "Datum",
            "Hydr. jaar",
            "Meting",
            "Jaargemiddelde",
            "Afwijking",
        )

        widths = self.get_outlier_table_widths(pdf)

        pdf.set_font("Helvetica", "B", 7)
        pdf.set_fill_color(255, 220, 220)

        for index, (header, width) in enumerate(
            zip(headers, widths)
        ):
            is_last = index == len(headers) - 1

            pdf.cell(
                width,
                8,
                encode_for_pdf(header),
                border=1,
                new_x=(
                    XPos.LMARGIN if is_last else XPos.RIGHT
                ),
                new_y=(
                    YPos.NEXT if is_last else YPos.TOP
                ),
                align="C",
                fill=True,
            )

    def ensure_outlier_table_space(
        self,
        pdf: PDFReport,
        required_height: float = 9.0,
    ) -> None:
        """Voeg zo nodig een vervolgpagina voor uitschieters toe."""

        if (
            pdf.get_y() + required_height
            > pdf.h - pdf.b_margin
        ):
            pdf.add_page()
            pdf.section_title(
                "Verwijderde uitschieters (vervolg)"
            )
            self.add_outlier_table_header(pdf)

    def add_outlier_table(
        self,
        pdf: PDFReport,
        statistics: GroundwaterStatistics,
    ) -> None:
        """Voeg een volledige lijst van uitschieters toe."""

        pdf.ln(5)
        pdf.section_title("Verwijderde uitschieters")

        if not statistics.removed_outliers:
            pdf.set_font("Helvetica", "", 9)

            pdf.cell(
                0,
                8,
                "Er zijn geen uitschieters verwijderd.",
                border=1,
                new_x=XPos.LMARGIN,
                new_y=YPos.NEXT,
                align="C",
            )

            return

        pdf.set_font("Helvetica", "", 8)

        pdf.multi_cell(
            0,
            5,
            encode_for_pdf(
                "Onderstaande metingen zijn niet gebruikt voor de "
                "berekening van de GHG- en GLG-proxy. Zij zijn in "
                "de grafiek met een rood kruis gemarkeerd."
            ),
            new_x=XPos.LMARGIN,
            new_y=YPos.NEXT,
        )

        pdf.ln(2)
        self.add_outlier_table_header(pdf)

        widths = self.get_outlier_table_widths(pdf)

        for outlier in statistics.removed_outliers:
            self.ensure_outlier_table_space(pdf)

            row_values = (
                outlier.measurement_date.strftime("%d-%m-%Y"),
                str(outlier.hydrological_year),
                f"{outlier.measurement_value:.3f}",
                f"{outlier.yearly_mean:.3f}",
                f"{outlier.absolute_deviation:.3f}",
            )

            pdf.set_font("Helvetica", "", 7)

            for index, (value, width) in enumerate(
                zip(row_values, widths)
            ):
                is_last = index == len(row_values) - 1

                pdf.cell(
                    width,
                    7,
                    encode_for_pdf(value),
                    border=1,
                    new_x=(
                        XPos.LMARGIN
                        if is_last
                        else XPos.RIGHT
                    ),
                    new_y=(
                        YPos.NEXT
                        if is_last
                        else YPos.TOP
                    ),
                    align="C",
                )

    def add_method_note(
        self,
        pdf: PDFReport,
    ) -> None:
        """Voeg een methodologische toelichting toe."""

        pdf.ln(5)
        pdf.section_title("Methodologische toelichting")
        pdf.set_font("Helvetica", "", 8)

        note = (
            "De weergegeven GHG- en GLG-waarden zijn "
            "proxywaarden. Per hydrologisch jaar worden metingen "
            "verwijderd waarvan de absolute afwijking ten opzichte "
            "van het jaargemiddelde groter is dan "
            f"{self.config.outlier_threshold_meters:.2f} meter. "
            "De verwijderde punten worden rood weergegeven in de "
            "grafiek. Een hydrologisch jaar wordt alleen gebruikt "
            "wanneer na filtering minimaal "
            f"{self.config.minimum_measurements_per_year} metingen "
            "overblijven. Vervolgens wordt per gebruikt jaar de "
            "hoogste en laagste gemeten waterstand bepaald. De "
            "uiteindelijke proxy is het gemiddelde van deze "
            "jaarlijkse waarden. Deze werkwijze is niet gelijk aan "
            "een formele GxG-bepaling."
        )

        pdf.multi_cell(
            0,
            5,
            encode_for_pdf(note),
            border=0,
            align="L",
            new_x=XPos.LMARGIN,
            new_y=YPos.NEXT,
        )

    def create_pdf_bytes(
        self,
        plot_png: bytes,
        filternummer: str,
        dataframe: pd.DataFrame,
        statistics: GroundwaterStatistics,
    ) -> bytes:
        """Genereer een volledig PDF-rapport als bytes."""

        if not plot_png:
            raise ValueError(
                "De grafiekdata voor het PDF-rapport is leeg."
            )

        temporary_plot_path: Optional[Path] = None
        file_descriptor: Optional[int] = None

        try:
            file_descriptor, temporary_name = tempfile.mkstemp(
                prefix="grondwater_plot_",
                suffix=".png",
            )

            os.close(file_descriptor)
            file_descriptor = None

            temporary_plot_path = Path(temporary_name)
            temporary_plot_path.write_bytes(plot_png)

            pdf = PDFReport(
                filternummer=filternummer,
                config=self.config,
            )

            pdf.add_page()

            pdf.image(
                str(temporary_plot_path),
                x=pdf.l_margin,
                y=None,
                w=pdf.usable_width,
            )

            pdf.ln(3)

            self.add_summary(
                pdf=pdf,
                dataframe=dataframe,
                statistics=statistics,
            )

            self.add_yearly_table(
                pdf=pdf,
                statistics=statistics,
            )

            self.add_outlier_table(
                pdf=pdf,
                statistics=statistics,
            )

            self.add_method_note(pdf)

            output = pdf.output()

            if isinstance(output, bytearray):
                pdf_bytes = bytes(output)
            elif isinstance(output, bytes):
                pdf_bytes = output
            else:
                pdf_bytes = bytes(output)

            if not pdf_bytes:
                raise OSError(
                    "Het gegenereerde PDF-bestand is leeg."
                )

            return pdf_bytes

        finally:
            if file_descriptor is not None:
                try:
                    os.close(file_descriptor)
                except OSError:
                    pass

            if temporary_plot_path is not None:
                try:
                    temporary_plot_path.unlink(missing_ok=True)
                except OSError:
                    pass
