"""Parsing and grid rules (synthetic fixture values)."""
from datetime import date

import pytest

from pyrosync import normalize as N
from pyrosync.query import GRID_R


def test_modis_confidence_numeric_bins():
    assert N.modis_conf("0") == (0, "low")
    assert N.modis_conf("29") == (29, "low")
    assert N.modis_conf("30") == (30, "nominal")
    assert N.modis_conf("79") == (79, "nominal")
    assert N.modis_conf("80") == (80, "high")
    assert N.modis_conf("100") == (100, "high")
    for bad in ("101", "-1", "n", "", "50.5"):
        with pytest.raises(N.RowError):
            N.modis_conf(bad)


def test_viirs_confidence_categorical():
    assert N.viirs_conf("l") == "low"
    assert N.viirs_conf("n") == "nominal"
    assert N.viirs_conf("h") == "high"
    for bad in ("50", "x", ""):
        with pytest.raises(N.RowError):
            N.viirs_conf(bad)


def test_acq_time_padding():
    assert N.parse_acq_time("402") == (4, 2)
    assert N.format_hhmm(*N.parse_acq_time("402")) == "0402"
    assert N.parse_acq_time("5") == (0, 5)
    assert N.parse_acq_time("2359") == (23, 59)
    assert N.parse_acq_time("04:02") == (4, 2)
    for bad in ("2400", "1260", "abc", ""):
        with pytest.raises(N.RowError):
            N.parse_acq_time(bad)


def test_acq_date_strict_and_leap_day():
    assert N.parse_acq_date("2024-02-29") == date(2024, 2, 29)
    for bad in ("2023-02-29", "2023/09/15", "15-09-2023", ""):
        with pytest.raises(N.RowError):
            N.parse_acq_date(bad)


def test_declared_window_from_filename():
    assert N.declared_window("2024-06-19_5d.csv") == (date(2024, 6, 19), date(2024, 6, 23))
    assert N.declared_window("2024-02-27_5d.csv") == (date(2024, 2, 27), date(2024, 3, 2))  # leap year
    assert N.declared_window("random.csv") is None


def test_declared_window_start_end_form():
    assert N.declared_window("2018-12-22_2018-12-26.csv") == (date(2018, 12, 22), date(2018, 12, 26))
    assert N.declared_window("2024-02-27_2024-03-02.csv") == (date(2024, 2, 27), date(2024, 3, 2))  # spans leap day
    assert N.declared_window("2024-03-02_2024-02-27.csv") is None  # reversed
    assert N.declared_window("2024-02-30_2024-03-02.csv") is None  # invalid date
    # the '_Nd' form keeps working
    assert N.declared_window("2024-06-19_5d.csv") == (date(2024, 6, 19), date(2024, 6, 23))


def test_stream_and_platform_detection():
    assert N.stream_from_path("MODIS_SP/2023-01-01_1d.csv") == "SP"
    assert N.stream_from_path("fire_nrt_J1V-C2_123.csv") == "NRT"
    assert N.stream_from_path("data.csv") is None
    assert N.stream_from_version("2.0NRT") == "NRT"
    assert N.stream_from_version("61.03") is None
    assert N.platform_for("MODIS", "Terra") == "Terra"
    assert N.platform_for("MODIS", "A") == "Aqua"
    assert N.platform_for("VIIRS", "N20") == "N20"
    assert N.platform_for("VIIRS", "N") == "SNPP"
    with pytest.raises(N.RowError):
        N.platform_for("VIIRS", "Landsat")


def _cell(lat, lon, g):
    """Python mirror of the documented grid rule (origin -180/-90, half-open cells)."""
    _, la = N.quantize_e5(str(lat), -90, 90, "latitude")
    _, lo = N.quantize_e5(str(lon), -180, 180, "longitude")
    r = GRID_R[g]
    ncols, nrows = 36_000_000 // r, 18_000_000 // r
    return min((lo + 18_000_000) // r, ncols - 1), min((la + 9_000_000) // r, nrows - 1)


def test_negative_coordinate_grid_indexing():
    # -2.55 lies in the cell [-2.6, -2.5); floor semantics, not truncation toward zero.
    ci, cj = _cell(-2.55, 113.55, 0.1)
    assert cj * 0.1 - 90 == pytest.approx(-2.6)
    assert ci * 0.1 - 180 == pytest.approx(113.5)
    # exact boundary belongs to the cell to its north/east (half-open)
    ci, cj = _cell(-2.5, 113.5, 0.1)
    assert cj * 0.1 - 90 == pytest.approx(-2.5)
    assert ci * 0.1 - 180 == pytest.approx(113.5)
    # -0.00001 is south of the equator
    assert _cell(-0.00001, 0, 0.1)[1] == 899
    assert _cell(0, 0, 0.1)[1] == 900
    # clamp at +180 / +90
    assert _cell(90, 180, 0.1) == (3599, 1799)


def test_quantize_rejects_out_of_range():
    with pytest.raises(N.RowError):
        N.quantize_e5("91", -90, 90, "latitude")
    with pytest.raises(N.RowError):
        N.quantize_e5("nan", -90, 90, "latitude")
