import unittest
from datetime import date

import pandas as pd

from analysis_service import GroundwaterAnalysisService
from app import chart_selection_period
from config import DEFAULT_CONFIG
from models import ExcludedPeriod


class ExcludedPeriodsTests(unittest.TestCase):
    def test_chart_selection_accepts_epoch_milliseconds(self):
        selected_period = chart_selection_period(
            {"x": [1706745600000, 1706918400000]}
        )

        self.assertEqual(
            selected_period,
            (date(2024, 2, 1), date(2024, 2, 3)),
        )

    def test_excluded_periods_are_removed_before_outlier_analysis(self):
        config = DEFAULT_CONFIG.with_runtime_settings(
            hydrological_year_start_month=4,
            minimum_measurements_per_year=2,
            outlier_threshold_meters=100.0,
        )
        service = GroundwaterAnalysisService(config)
        dataframe = pd.DataFrame(
            {
                "datum": pd.to_datetime(
                    [
                        "2024-01-01 12:00",
                        "2024-02-01 12:00",
                        "2024-03-01 12:00",
                    ]
                ),
                "meting NAP": [1.0, 100.0, 3.0],
            }
        )
        periods = (
            ExcludedPeriod(
                start_date=pd.Timestamp("2024-02-01"),
                end_date=pd.Timestamp("2024-02-01"),
            ),
            ExcludedPeriod(
                start_date=pd.Timestamp("2024-02-01"),
                end_date=pd.Timestamp("2024-02-02"),
            ),
        )

        statistics, filtered_dataframe = service.calculate_statistics(
            dataframe,
            excluded_periods=periods,
        )

        self.assertEqual(statistics.original_measurement_count, 3)
        self.assertEqual(statistics.excluded_period_measurement_count, 1)
        self.assertEqual(statistics.filtered_measurement_count, 2)
        self.assertEqual(statistics.removed_outlier_count, 0)
        self.assertEqual(list(filtered_dataframe["meting NAP"]), [1.0, 3.0])
        self.assertEqual(statistics.ghg, 3.0)
        self.assertEqual(statistics.glg, 1.0)

    def test_reversed_period_is_rejected(self):
        service = GroundwaterAnalysisService(DEFAULT_CONFIG)
        dataframe = pd.DataFrame(
            {
                "datum": pd.to_datetime(["2024-01-01"]),
                "meting NAP": [1.0],
            }
        )

        with self.assertRaisesRegex(ValueError, "begindatum"):
            service.calculate_statistics(
                dataframe,
                excluded_periods=(
                    ExcludedPeriod(
                        start_date=pd.Timestamp("2024-02-01"),
                        end_date=pd.Timestamp("2024-01-01"),
                    ),
                ),
            )


if __name__ == "__main__":
    unittest.main()
