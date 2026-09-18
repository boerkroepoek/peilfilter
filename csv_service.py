from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd
from pandas.errors import EmptyDataError, ParserError

from config import AppConfig
from models import CsvMetadata
from utilities import (
    canonical_column_name,
    normalize_column_name,
    parse_csv_line,
    parse_numeric_value,
    sanitize_filternummer,
    validate_input_file,
)


class CsvService:
    """Service voor CSV-detectie, parsing, normalisatie en validatie."""

    def __init__(self, config: AppConfig) -> None:
        self.config = config

    def line_starts_with_expected_header(self, line: str) -> bool:
        """Controleer of een regel begint met de vereiste kolommen."""

        parts = [
            canonical_column_name(part)
            for part in parse_csv_line(
                line=line,
                delimiter=self.config.delimiter,
            )
        ]

        if len(parts) < 2:
            return False

        return (
            parts[0] == self.config.expected_date_column.casefold()
            and parts[1]
            == self.config.expected_measurement_column.casefold()
        )

    def extract_filternummer_from_first_line(
        self,
        first_line: str,
    ) -> str:
        """Haal het filternummer uit het eerste veld van de eerste regel."""

        if self.line_starts_with_expected_header(first_line):
            return "Onbekend"

        fields = parse_csv_line(
            line=first_line,
            delimiter=self.config.delimiter,
        )

        if not fields:
            return "Onbekend"

        return sanitize_filternummer(fields[0])

    def find_metadata_and_header(
        self,
        csv_file: Path,
    ) -> CsvMetadata:
        """Zoek encoding, filternummer en headerregel van een CSV-bestand."""

        validate_input_file(csv_file, self.config)

        unicode_errors: list[str] = []
        successfully_decoded_encodings: list[str] = []

        for encoding in self.config.encodings_to_try:
            try:
                with csv_file.open(
                    mode="r",
                    encoding=encoding,
                    errors="strict",
                    newline="",
                ) as handle:
                    lines = handle.readlines()

                successfully_decoded_encodings.append(encoding)

                if not lines:
                    raise ValueError(
                        f"CSV-bestand is leeg: {csv_file.name}"
                    )

                filternummer = self.extract_filternummer_from_first_line(
                    lines[0]
                )

                for row_index, line in enumerate(lines):
                    if self.line_starts_with_expected_header(line):
                        return CsvMetadata(
                            filternummer=filternummer,
                            header_row_index=row_index,
                            encoding=encoding,
                        )

            except UnicodeDecodeError as exc:
                unicode_errors.append(f"{encoding}: {exc}")
            except OSError as exc:
                raise OSError(
                    f"CSV-bestand kon niet worden gelezen: {csv_file.name}"
                ) from exc

        if not successfully_decoded_encodings:
            details = "; ".join(unicode_errors)

            raise UnicodeError(
                f"Geen geschikte tekstencoding gevonden voor "
                f"{csv_file.name}. Geprobeerde encodings: "
                f"{', '.join(self.config.encodings_to_try)}. "
                f"Details: {details}"
            )

        raise ValueError(
            f"De verwachte header met kolommen "
            f"'{self.config.expected_date_column}' en "
            f"'{self.config.expected_measurement_column}' "
            f"is niet gevonden in {csv_file.name}."
        )

    def standardize_required_columns(
        self,
        dataframe: pd.DataFrame,
    ) -> pd.DataFrame:
        """Normaliseer kolomnamen en geef vereiste kolommen vaste namen."""

        cleaned_df = dataframe.copy()
        cleaned_df.columns = [
            normalize_column_name(column)
            for column in cleaned_df.columns
        ]

        valid_columns = [
            column
            for column in cleaned_df.columns
            if column
            and not canonical_column_name(column).startswith("unnamed")
        ]

        cleaned_df = cleaned_df.loc[:, valid_columns]

        canonical_lookup: dict[str, list[str]] = {}

        for column in cleaned_df.columns:
            canonical_lookup.setdefault(
                canonical_column_name(column),
                [],
            ).append(column)

        required_mapping = {
            self.config.expected_date_column.casefold():
                self.config.expected_date_column,
            self.config.expected_measurement_column.casefold():
                self.config.expected_measurement_column,
        }

        rename_mapping: dict[str, str] = {}

        for canonical_name, target_name in required_mapping.items():
            matches = canonical_lookup.get(canonical_name, [])

            if not matches:
                raise ValueError(
                    f"Vereiste kolom '{target_name}' ontbreekt. "
                    f"Gevonden kolommen: {list(cleaned_df.columns)}"
                )

            if len(matches) > 1:
                raise ValueError(
                    f"Kolom '{target_name}' komt meerdere keren voor: "
                    f"{matches}"
                )

            rename_mapping[matches[0]] = target_name

        return cleaned_df.rename(columns=rename_mapping)

    @staticmethod
    def parse_numeric_measurements(
        series: pd.Series,
    ) -> pd.Series:
        """Converteer een reeks meetwaarden robuust naar floats."""

        return series.map(parse_numeric_value).astype("float64")

    @staticmethod
    def parse_dates(series: pd.Series) -> pd.Series:
        """Parse datums en retourneer timezone-naive timestamps."""

        raw_values = series.astype("string").str.strip()

        try:
            parsed = pd.to_datetime(
                raw_values,
                format="mixed",
                dayfirst=True,
                errors="coerce",
                utc=True,
            )
        except (TypeError, ValueError):
            parsed = pd.to_datetime(
                raw_values,
                dayfirst=True,
                errors="coerce",
                utc=True,
            )

        return parsed.dt.tz_convert(None)

    def load_and_prepare_data(
        self,
        csv_file: Path,
        metadata: CsvMetadata,
    ) -> pd.DataFrame:
        """Laad, normaliseer en valideer de meetgegevens."""

        try:
            dataframe = pd.read_csv(
                csv_file,
                sep=self.config.delimiter,
                skiprows=metadata.header_row_index,
                encoding=metadata.encoding,
                dtype=str,
                keep_default_na=True,
                na_values=list(self.config.csv_na_values),
                engine="python",
                on_bad_lines="warn",
            )
        except EmptyDataError as exc:
            raise ValueError(
                f"Geen tabelgegevens gevonden in {csv_file.name}."
            ) from exc
        except ParserError as exc:
            raise ValueError(
                f"CSV-structuur van {csv_file.name} is ongeldig: {exc}"
            ) from exc
        except UnicodeError as exc:
            raise ValueError(
                f"CSV-bestand {csv_file.name} bevat ongeldige "
                f"tekstdata: {exc}"
            ) from exc
        except OSError as exc:
            raise OSError(
                f"CSV-data kon niet worden gelezen uit "
                f"{csv_file.name}: {exc}"
            ) from exc

        if dataframe.empty:
            raise ValueError(
                f"Geen datarijen gevonden in {csv_file.name}."
            )

        dataframe = self.standardize_required_columns(dataframe)
        original_row_count = len(dataframe)

        date_column = self.config.expected_date_column
        measurement_column = self.config.expected_measurement_column

        dataframe[date_column] = self.parse_dates(
            dataframe[date_column]
        )

        invalid_date_count = int(
            dataframe[date_column].isna().sum()
        )

        dataframe[measurement_column] = (
            self.parse_numeric_measurements(
                dataframe[measurement_column]
            )
        )

        invalid_measurement_count = int(
            dataframe[measurement_column].isna().sum()
        )

        if invalid_date_count:
            logging.warning(
                "[%s] %d ongeldige datumwaarde(n) verwijderd.",
                csv_file.name,
                invalid_date_count,
            )

        if invalid_measurement_count:
            logging.warning(
                "[%s] %d ongeldige of lege meetwaarde(n) verwijderd.",
                csv_file.name,
                invalid_measurement_count,
            )

        dataframe = dataframe.dropna(
            subset=[
                date_column,
                measurement_column,
            ]
        ).copy()

        if dataframe.empty:
            raise ValueError(
                f"Na validatie zijn geen bruikbare metingen "
                f"overgebleven in {csv_file.name}."
            )

        duplicate_subset = [
            date_column,
            measurement_column,
        ]

        duplicate_count = int(
            dataframe.duplicated(
                subset=duplicate_subset
            ).sum()
        )

        if duplicate_count:
            logging.warning(
                "[%s] %d exacte dubbele meting(en) verwijderd.",
                csv_file.name,
                duplicate_count,
            )

            dataframe = dataframe.drop_duplicates(
                subset=duplicate_subset,
                keep="first",
            )

        dataframe = dataframe.sort_values(
            date_column,
            kind="stable",
        ).reset_index(drop=True)

        logging.info(
            "[%s] Data geladen met encoding %s: %d geldige "
            "metingen, %d verwijderde rijen.",
            csv_file.name,
            metadata.encoding,
            len(dataframe),
            original_row_count - len(dataframe),
        )

        return dataframe
