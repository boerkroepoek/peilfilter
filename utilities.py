from __future__ import annotations

import csv
import logging
import math
import re
from pathlib import Path

from config import AppConfig


def configure_logging(level: int) -> None:
    """Configureer applicatielogging."""

    logging.basicConfig(
        level=level,
        format="%(asctime)s - %(levelname)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        force=True,
    )


def normalize_text(value: object) -> str:
    """Normaliseer tekst voor betrouwbare vergelijkingen."""

    if value is None:
        return ""

    text = str(value).replace("\ufeff", "").strip()
    return re.sub(r"\s+", " ", text)


def normalize_column_name(value: object) -> str:
    """Normaliseer een CSV-kolomnaam."""

    return normalize_text(value).rstrip(";").strip()


def canonical_column_name(value: object) -> str:
    """Maak een kolomnaam geschikt voor hoofdletterongevoelige vergelijking."""

    return normalize_column_name(value).casefold()


def sanitize_filternummer(value: object) -> str:
    """Maak een filternummer geschikt voor grafiek- en PDF-weergave."""

    filternummer = normalize_text(value)

    if not filternummer:
        return "Onbekend"

    filternummer = "".join(
        character
        for character in filternummer
        if character.isprintable()
    )

    return filternummer[:200] or "Onbekend"


def encode_for_pdf(value: object) -> str:
    """Converteer tekst naar Latin-1 voor standaard PDF-lettertypen."""

    return (
        str(value)
        .encode("latin-1", errors="replace")
        .decode("latin-1")
    )


def validate_input_file(
    csv_file: Path,
    config: AppConfig,
) -> None:
    """Controleer of een invoerbestand bestaat en bruikbaar is."""

    if not csv_file.exists():
        raise FileNotFoundError(f"Bestand bestaat niet: {csv_file}")

    if not csv_file.is_file():
        raise ValueError(f"Pad is geen bestand: {csv_file}")

    try:
        file_size = csv_file.stat().st_size
    except OSError as exc:
        raise OSError(
            f"Bestandsinformatie kon niet worden gelezen: {csv_file}"
        ) from exc

    if file_size == 0:
        raise ValueError(f"Bestand is leeg: {csv_file.name}")

    maximum_size_bytes = config.maximum_upload_size_mb * 1024 * 1024

    if file_size > maximum_size_bytes:
        raise ValueError(
            f"Bestand {csv_file.name} is groter dan de toegestane "
            f"{config.maximum_upload_size_mb} MB."
        )


def parse_csv_line(
    line: str,
    delimiter: str,
) -> list:
    """Parse één CSV-regel met ondersteuning voor gequote velden."""

    if not line:
        return []

    try:
        reader = csv.reader(
            [line],
            delimiter=delimiter,
            skipinitialspace=True,
        )
        return next(reader)
    except (csv.Error, StopIteration):
        return []


def format_nap_value(value: float) -> str:
    """Formatteer een NAP-waarde met twee decimalen."""

    return f"{value:.2f} m NAP"


def parse_numeric_value(value: object) -> float:
    """Converteer één meetwaarde naar een float."""

    if value is None:
        return math.nan

    try:
        import pandas as pd

        if pd.isna(value):
            return math.nan
    except (TypeError, ValueError):
        pass

    if isinstance(value, bool):
        return math.nan

    if isinstance(value, (int, float)):
        numeric_value = float(value)
        return numeric_value if math.isfinite(numeric_value) else math.nan

    text = normalize_text(value)
    text = text.replace("\u00a0", "").replace(" ", "")
    text = re.sub(r"[^0-9,.\-+]", "", text)

    if not text or text in {"-", "+", ".", ","}:
        return math.nan

    sign_count = text.count("+") + text.count("-")

    if sign_count > 1:
        return math.nan

    if sign_count == 1 and text[0] not in {"+", "-"}:
        return math.nan

    sign = text[0] if text[0:1] in {"+", "-"} else ""
    unsigned_text = text[1:] if sign else text

    if not unsigned_text:
        return math.nan

    if not any(character.isdigit() for character in unsigned_text):
        return math.nan

    comma_count = unsigned_text.count(",")
    dot_count = unsigned_text.count(".")
    comma_position = unsigned_text.rfind(",")
    dot_position = unsigned_text.rfind(".")

    if comma_count and dot_count:
        if comma_position > dot_position:
            unsigned_text = unsigned_text.replace(".", "")
            unsigned_text = unsigned_text.replace(",", ".")
        else:
            unsigned_text = unsigned_text.replace(",", "")

    elif comma_count == 1:
        unsigned_text = unsigned_text.replace(",", ".")

    elif comma_count > 1:
        integer_part, decimal_part = unsigned_text.rsplit(",", maxsplit=1)
        unsigned_text = integer_part.replace(",", "") + "." + decimal_part

    elif dot_count > 1:
        integer_part, decimal_part = unsigned_text.rsplit(".", maxsplit=1)
        unsigned_text = integer_part.replace(".", "") + "." + decimal_part

    try:
        numeric_value = float(sign + unsigned_text)
    except ValueError:
        return math.nan

    return numeric_value if math.isfinite(numeric_value) else math.nan
