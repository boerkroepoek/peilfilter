from __future__ import annotations

import logging
import tempfile
from pathlib import Path

from analysis_service import GroundwaterAnalysisService
from chart_service import ChartService
from config import AppConfig
from csv_service import CsvService
from models import ProcessingResult, UploadedCsvFile
from pdf_service import PdfService


class GroundwaterProcessingService:
    """Orkestreert de volledige verwerking van CSV naar rapport."""

    def __init__(self, config: AppConfig) -> None:
        self.config = config
        self.csv_service = CsvService(config)
        self.analysis_service = GroundwaterAnalysisService(config)
        self.chart_service = ChartService(config)
        self.pdf_service = PdfService(config)

    @staticmethod
    def sanitize_filename(filename: str) -> str:
        """Verwijder padinformatie uit een geüploade bestandsnaam."""

        safe_name = Path(filename).name

        if not safe_name:
            return "upload.csv"

        return safe_name

    def process_uploaded_file(
        self,
        uploaded_file: UploadedCsvFile,
    ) -> ProcessingResult:
        """Verwerk één browserupload tot analyse en PDF."""

        safe_filename = self.sanitize_filename(
            uploaded_file.filename
        )

        if not uploaded_file.content:
            return ProcessingResult(
                source_filename=safe_filename,
                output_filename=None,
                success=False,
                message="Het geüploade bestand is leeg.",
            )

        logging.info(
            "Start analyse van %s.",
            safe_filename,
        )

        try:
            with tempfile.TemporaryDirectory(
                prefix="grondwater_streamlit_"
            ) as temporary_directory:
                temporary_path = (
                    Path(temporary_directory) / safe_filename
                )

                temporary_path.write_bytes(
                    uploaded_file.content
                )

                metadata = (
                    self.csv_service.find_metadata_and_header(
                        temporary_path
                    )
                )

                dataframe = (
                    self.csv_service.load_and_prepare_data(
                        csv_file=temporary_path,
                        metadata=metadata,
                    )
                )

                statistics, filtered_dataframe = (
                    self.analysis_service.calculate_statistics(
                        dataframe
                    )
                )

                plot_png = self.chart_service.create_png(
                    dataframe=dataframe,
                    filternummer=metadata.filternummer,
                    statistics=statistics,
                )

                pdf_bytes = self.pdf_service.create_pdf_bytes(
                    plot_png=plot_png,
                    filternummer=metadata.filternummer,
                    dataframe=dataframe,
                    statistics=statistics,
                )

            output_filename = (
                f"{Path(safe_filename).stem}"
                f"{self.config.output_suffix}"
            )

            message = (
                f"Rapport aangemaakt. "
                f"Geldige metingen: {len(dataframe)}. "
                f"Verwijderde uitschieters: "
                f"{statistics.removed_outlier_count}."
            )

            return ProcessingResult(
                source_filename=safe_filename,
                output_filename=output_filename,
                success=True,
                message=message,
                filternummer=metadata.filternummer,
                dataframe=dataframe,
                filtered_dataframe=filtered_dataframe,
                statistics=statistics,
                plot_png=plot_png,
                pdf_bytes=pdf_bytes,
            )

        except Exception as exc:
            logging.exception(
                "Verwerking van %s is mislukt.",
                safe_filename,
            )

            return ProcessingResult(
                source_filename=safe_filename,
                output_filename=None,
                success=False,
                message=str(exc),
            )

    def process_uploaded_files(
        self,
        uploaded_files: list[UploadedCsvFile],
    ) -> list"""Verwerk meerdere bestanden en isoleer fouten per bestand."""

        return [
            self.process_uploaded_file(uploaded_file)
            for uploaded_file in uploaded_files
        ]
