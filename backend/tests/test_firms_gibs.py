"""FIRMS connector (mocked with httpx.MockTransport; no network, no real key) and GIBS URL rules."""
from datetime import date

import httpx
import pytest

from pyrosync import firms, gibs, query as Q
from pyrosync.config import get_settings
from conftest import VIIRS_HDR, csv_bytes, viirs_row

FAKE_KEY = "abcdef0123456789FAKEKEY"


def client(handler):
    return httpx.Client(transport=httpx.MockTransport(handler))


def job(start=date(2023, 9, 14), end=date(2023, 9, 16), source="VIIRS_NOAA20_SP"):
    return firms.FirmsJob(id="t1", source=source, bbox=(113.0, -3.0, 114.0, -2.0), start=start, end=end)


def test_window_splitting():
    w = firms.split_windows(date(2023, 1, 1), date(2023, 1, 12))
    assert w == [(date(2023, 1, 1), 5), (date(2023, 1, 6), 5), (date(2023, 1, 11), 2)]
    assert firms.split_windows(date(2024, 2, 28), date(2024, 3, 1)) == [(date(2024, 2, 28), 3)]


def test_bbox_validation():
    with pytest.raises(firms.FirmsError):
        firms.validate_bbox((170, 0, -170, 1))
    with pytest.raises(firms.FirmsError):
        firms.validate_bbox((0, 5, 1, 4))


def test_no_key(env):
    j = job()
    firms.run_job(j, client(lambda r: httpx.Response(200, text="")))
    assert j.status == "error" and "No FIRMS_MAP_KEY" in j.error


def test_invalid_key_redacted(env):
    get_settings().firms_map_key = FAKE_KEY
    j = job()
    firms.run_job(j, client(lambda r: httpx.Response(400, text="Invalid MAP_KEY.")), sleep=lambda s: None)
    assert j.status == "error" and "MAP_KEY" in j.error
    assert FAKE_KEY not in str(j.public())


def test_unexpected_error_text_redacted(env):
    get_settings().firms_map_key = FAKE_KEY
    j = job()
    firms.run_job(j, client(lambda r: httpx.Response(418, text=f"teapot at {r.url}")), sleep=lambda s: None)
    assert j.status == "error"
    assert FAKE_KEY not in j.error


def test_rate_limit_retries_then_fails(env):
    get_settings().firms_map_key = FAKE_KEY
    calls, sleeps = [], []
    def h(r):
        calls.append(r); return httpx.Response(429, text="Exceeding allowed transaction limit")
    j = job()
    firms.run_job(j, client(h), sleep=sleeps.append)
    assert j.status == "error" and "transaction limit" in j.error
    assert len(calls) == firms.MAX_RETRIES + 1 and all(s >= 30 for s in sleeps)


def test_empty_result_imports_zero_reported(env):
    get_settings().firms_map_key = FAKE_KEY
    urls = []
    def h(r):
        urls.append(str(r.url)); return httpx.Response(200, text=",".join(VIIRS_HDR) + "\n")
    j = job()
    firms.run_job(j, client(h), sleep=lambda s: None)
    assert j.status == "done", j.error
    assert j.report["new_observations"] == 0
    assert urls[0].endswith("/VIIRS_NOAA20_SP/113,-3,114,-2/3/2023-09-14")
    # empty response inside an api-request interval, bbox containing the AOI: but sensor never had rows -> sensor_unavailable
    d = Q.daily(Q.Filters(start=date(2023, 9, 14), end=date(2023, 9, 16)))
    assert set(d["series"]["VIIRS_N20"]["status"]) <= {"sensor_unavailable", "outside_range", "zero_reported"}


def test_rows_imported_and_cache_reused(env):
    get_settings().firms_map_key = FAKE_KEY
    body = csv_bytes(VIIRS_HDR, [viirs_row(date="2023-09-15", version="2.0NRT")]).decode()
    n = []
    def h(r):
        n.append(1); return httpx.Response(200, text=body)
    j = job(source="VIIRS_NOAA20_NRT")
    firms.run_job(j, client(h), sleep=lambda s: None)
    assert j.status == "done" and j.report["new_observations"] == 1
    d = Q.daily(Q.Filters(start=date(2023, 9, 14), end=date(2023, 9, 16)))
    st = d["series"]["VIIRS_N20"]["status"]
    assert st == ["zero_reported", "detections", "zero_reported"]
    j2 = job(source="VIIRS_NOAA20_NRT")
    firms.run_job(j2, client(h), sleep=lambda s: None)
    assert j2.cached_hits == 1 and len(n) == 1  # served from disk cache
    assert j2.report["new_observations"] == 0


def test_cancel_before_download(env):
    get_settings().firms_map_key = FAKE_KEY
    j = job()
    j.cancel.set()
    firms.run_job(j, client(lambda r: httpx.Response(200, text="")), sleep=lambda s: None)
    assert j.status == "cancelled"
    assert Q.inventory()["date_range"] is None


def test_network_error(env):
    get_settings().firms_map_key = FAKE_KEY
    def h(r):
        raise httpx.ConnectError("boom")
    j = job()
    firms.run_job(j, client(h), sleep=lambda s: None)
    assert j.status == "error" and "Network failure" in j.error


def test_redact_patterns():
    assert FAKE_KEY not in firms.redact(f"https://x/api/area/csv/{FAKE_KEY}/MODIS_SP/1,2,3,4/1/2023-01-01", FAKE_KEY)
    assert "***" in firms.redact("https://x/api/area/csv/SOMEKEY/MODIS_SP/", "")


# ---------------------------------------------------------------- GIBS
def test_gibs_tile_url_contains_explicit_date():
    u = gibs.tile_url("VIIRS_NOAA20_CorrectedReflectance_TrueColor", date(2023, 9, 15), 5, 16, 25)
    assert "/default/2023-09-15/GoogleMapsCompatible_Level9/5/16/25.jpg" in u


def test_gibs_template_has_date_placeholder(env):
    info = gibs.layer_info(client(lambda r: httpx.Response(503)))
    for l in info["layers"]:
        assert "/default/{date}/" in l["url_template"]
    assert info["domain_source"] != "live"


def test_gibs_domain_parsing_and_nearest():
    rng = gibs.parse_domain("2002-07-03/2002-07-30/P1D,2022-04-17/2026-10-11/P1D")
    ranges = [[a.isoformat(), b.isoformat()] for a, b in rng]
    assert gibs.available(ranges, date(2023, 9, 15))
    assert not gibs.available(ranges, date(2022, 4, 1))
    assert gibs.nearest(ranges, date(2022, 4, 1)) == date(2022, 4, 17)
