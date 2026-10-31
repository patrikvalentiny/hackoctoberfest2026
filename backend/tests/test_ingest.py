import asyncio
import io
import json
import sqlite3
import unittest
from contextlib import redirect_stdout
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

import eccodes
import httpx
from support import provider_payloads, wave_ensemble

from backend.engine.profiles import SITES
from backend.ingest import ecmwf_waef
from backend.ingest.dmi_lightning import LightningError, fetch_lightning, summarize
from backend.ingest.ecmwf_waef import (
    WaveDataError,
    WaveEnsemble,
    candidate_runs,
    hourly,
)
from backend.ingest.open_meteo import (
    ProviderError,
    build_site_forecast,
    fetch_payloads,
    fetch_site_forecast,
)
from backend.store import Store

RUN = datetime(2026, 11, 10, tzinfo=UTC)


def run(coro):
    return asyncio.run(coro)


class BuildSiteForecastTests(unittest.TestCase):
    def test_without_waves_heights_are_shared_and_labelled(self) -> None:
        forecast = build_site_forecast(SITES["hr1"], provider_payloads(), datetime.now(UTC))

        self.assertEqual(forecast.ensemble.members, 3)
        self.assertEqual(forecast.ensemble.variables["wind_speed_100m_ms"][2][0], 9.0)
        self.assertIn("wave_height_m", forecast.ensemble.deterministic_variables)
        self.assertEqual(forecast.ensemble.variables["swell_wave_height_m"][0][0], 0.4)
        self.assertEqual(len(forecast.weekly_outlook), 2)
        self.assertTrue(any("deterministic (ECMWF WAM)" in note for note in forecast.notes))
        self.assertEqual(forecast.times[0], RUN)
        self.assertNotIn("wave_ensemble", [source.id for source in forecast.sources])

    def test_pairs_wind_and_wave_members_by_number(self) -> None:
        forecast = build_site_forecast(SITES["hr1"], provider_payloads(), RUN + timedelta(hours=2), wave_ensemble())

        # The control wind run has no waef pair, so members 1 and 2 remain.
        self.assertEqual(forecast.ensemble.members, 2)
        self.assertEqual(forecast.ensemble.variables["wind_speed_100m_ms"][0][0], 8.0)
        self.assertEqual(forecast.ensemble.variables["wave_height_m"][0][3], 1.3)
        self.assertEqual(forecast.ensemble.variables["wave_height_m"][1][3], 0.5)
        # After the last waef step (24 h), deterministic WAM fills in.
        self.assertEqual(forecast.ensemble.variables["wave_height_m"][0][40], 1.0)
        self.assertNotIn("wave_height_m", forecast.ensemble.deterministic_variables)
        source = next(source for source in forecast.sources if source.id == "wave_ensemble")
        self.assertEqual(source.run, RUN)
        self.assertTrue(any("fall back to deterministic WAM" in note for note in forecast.notes))

    def test_ignores_wave_run_too_old_to_pair(self) -> None:
        forecast = build_site_forecast(
            SITES["hr1"], provider_payloads(), RUN + timedelta(hours=40), wave_ensemble()
        )

        self.assertEqual(forecast.ensemble.members, 3)
        self.assertIn("wave_height_m", forecast.ensemble.deterministic_variables)
        self.assertTrue(any("too old" in note for note in forecast.notes))

    def test_ignores_wave_ensemble_without_matching_members(self) -> None:
        waves = WaveEnsemble(**{**wave_ensemble().__dict__, "members": {7: [1.0] * 5}})

        forecast = build_site_forecast(SITES["hr1"], provider_payloads(), RUN, waves)

        self.assertEqual(forecast.ensemble.members, 3)
        self.assertTrue(any("no members matching" in note for note in forecast.notes))

    def test_optional_sources_degrade_with_a_note(self) -> None:
        payloads = provider_payloads()
        payloads["swell"] = None
        payloads["seasonal"] = {"weekly": {"time": ["not a date"], "wind_speed_10m_mean": [1.0], "wind_speed_10m_anomaly": [0.0]}}

        forecast = build_site_forecast(SITES["hr1"], payloads, RUN)

        self.assertEqual(forecast.weekly_outlook, ())
        self.assertEqual(forecast.ensemble.variables["swell_wave_height_m"][0][0], None)
        self.assertTrue(any("Swell" in note for note in forecast.notes))
        self.assertTrue(any("EC46" in note for note in forecast.notes))

    def test_malformed_swell_does_not_break_the_forecast(self) -> None:
        payloads = provider_payloads()
        payloads["swell"] = {"hourly": {"time": ["x"]}}

        forecast = build_site_forecast(SITES["hr1"], payloads, RUN)

        self.assertTrue(any("Swell" in note for note in forecast.notes))

    def test_required_sources_must_be_valid(self) -> None:
        cases = {
            "no hourly block": ("marine", {}),
            "no wave heights": ("marine", {"hourly": {"time": [], "wave_height": [], "wave_period": [], "wave_direction": []}}),
            "mismatched lengths": ("visibility", {"hourly": {"time": ["2026-11-10T00:00"], "visibility": []}}),
            "bad timestamp": ("dmi", {"hourly": {"time": ["yesterday"]}}),
        }
        for name, (key, payload) in cases.items():
            with self.subTest(name):
                payloads = provider_payloads()
                payloads[key] = payload
                with self.assertRaises(ProviderError):
                    build_site_forecast(SITES["hr1"], payloads, RUN)

    def test_ensemble_must_be_consistent(self) -> None:
        cases = {
            "no times": {"hourly": {}},
            "only control": {"hourly": {"time": [], "wind_speed_10m": [], "wind_speed_100m": []}},
            "member count differs": {
                "hourly": {
                    "time": ["2026-11-10T00:00"],
                    "wind_speed_10m": [1.0],
                    "wind_speed_10m_member01": [1.0],
                    "wind_speed_100m": [1.0],
                }
            },
        }
        for name, ensemble in cases.items():
            with self.subTest(name):
                payloads = provider_payloads()
                payloads["ensemble"] = ensemble
                with self.assertRaises(ProviderError):
                    build_site_forecast(SITES["hr1"], payloads, RUN)

    def test_seasonal_without_weekly_block_is_skipped(self) -> None:
        payloads = provider_payloads()
        payloads["seasonal"] = {"error": True}

        forecast = build_site_forecast(SITES["hr1"], payloads, RUN)

        self.assertEqual(forecast.weekly_outlook, ())

    def test_aligns_sources_on_different_hours(self) -> None:
        payloads = provider_payloads(hours=4)
        payloads["marine"]["hourly"] = {
            "time": ["2026-11-10T02:00", "2026-11-10T03:00", "2026-11-10T04:00"],
            "wave_height": [1.1, 1.2, 1.3],
            "wave_period": [6.0, 6.0, 6.0],
            "wave_direction": [200.0, 200.0, 200.0],
        }

        forecast = build_site_forecast(SITES["hr1"], payloads, RUN)

        self.assertEqual(forecast.ensemble.variables["wave_height_m"][0], [None, None, 1.1, 1.2])


class FetchPayloadsTests(unittest.TestCase):
    def client(self, handler) -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=httpx.MockTransport(handler))

    def test_returns_all_payloads(self) -> None:
        payloads = provider_payloads()
        routes = {
            "ensemble-api": "ensemble",
            "seasonal-api": "seasonal",
        }

        def handler(request: httpx.Request) -> httpx.Response:
            host = request.url.host.split(".")[0]
            params = request.url.params
            if host in routes:
                return httpx.Response(200, json=payloads[routes[host]])
            if host == "marine-api":
                return httpx.Response(200, json=payloads["marine" if params.get("models") else "swell"])
            return httpx.Response(200, json=payloads["dmi" if "wind_speed_100m" in params["hourly"] else "visibility"])

        result = run(fetch_payloads(SITES["hr1"], self.client(handler)))

        self.assertEqual(set(result), {"ensemble", "marine", "swell", "visibility", "dmi", "seasonal"})
        forecast = build_site_forecast(SITES["hr1"], result, RUN)
        self.assertEqual(len(forecast.weekly_outlook), 2)

    def test_optional_failure_becomes_none(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            if "seasonal" in request.url.host:
                return httpx.Response(503)
            return httpx.Response(200, json={"hourly": {"time": []}})

        result = run(fetch_payloads(SITES["hr1"], self.client(handler)))

        self.assertIsNone(result["seasonal"])
        self.assertIsNotNone(result["ensemble"])

    def test_required_failure_raises_provider_error(self) -> None:
        def unavailable(request: httpx.Request) -> httpx.Response:
            return httpx.Response(503 if "ensemble" in request.url.host else 200, json={})

        def unreadable(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, content=b"<html>")

        with self.assertRaisesRegex(ProviderError, "unavailable"):
            run(fetch_payloads(SITES["hr1"], self.client(unavailable)))
        with self.assertRaisesRegex(ProviderError, "unreadable"):
            run(fetch_payloads(SITES["hr1"], self.client(unreadable)))

    def test_network_error_raises_provider_error(self) -> None:
        def offline(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("no route", request=request)

        with self.assertRaises(ProviderError):
            run(fetch_payloads(SITES["hr1"], self.client(offline)))

    def test_fetch_site_forecast_builds_from_responses(self) -> None:
        payloads = provider_payloads(hours=24)

        def handler(request: httpx.Request) -> httpx.Response:
            host, params = request.url.host, request.url.params
            if host.startswith("ensemble"):
                return httpx.Response(200, json=payloads["ensemble"])
            if host.startswith("seasonal"):
                return httpx.Response(200, json=payloads["seasonal"])
            if host.startswith("marine"):
                return httpx.Response(200, json=payloads["marine" if params.get("models") else "swell"])
            return httpx.Response(200, json=payloads["dmi" if "wind_speed_100m" in params["hourly"] else "visibility"])

        forecast = run(fetch_site_forecast(SITES["hr2"], self.client(handler)))

        self.assertEqual(forecast.site_id, "hr2")
        self.assertEqual(len(forecast.times), 24)

    def test_programming_errors_are_not_hidden(self) -> None:
        def broken(request: httpx.Request) -> httpx.Response:
            raise KeyError("bug")

        with self.assertRaises(KeyError):
            run(fetch_payloads(SITES["hr1"], self.client(broken)))


def grib_message(value_at: dict[tuple[float, float], float]) -> bytes:
    """A real 0.25 degree GRIB2 field over 55-56 N, 7-8 E (9999 = missing)."""
    gid = eccodes.codes_grib_new_from_samples("regular_ll_sfc_grib2")
    try:
        for key, value in (
            ("Ni", 5),
            ("Nj", 5),
            ("latitudeOfFirstGridPointInDegrees", 56.0),
            ("longitudeOfFirstGridPointInDegrees", 7.0),
            ("latitudeOfLastGridPointInDegrees", 55.0),
            ("longitudeOfLastGridPointInDegrees", 8.0),
            ("iDirectionIncrementInDegrees", 0.25),
            ("jDirectionIncrementInDegrees", 0.25),
            ("bitmapPresent", 1),
            ("missingValue", 9999),
        ):
            eccodes.codes_set(gid, key, value)
        values = [
            value_at.get((56.0 - 0.25 * row, 7.0 + 0.25 * col), 0.5) for row in range(5) for col in range(5)
        ]
        eccodes.codes_set_values(gid, values)
        return eccodes.codes_get_message(gid)
    finally:
        eccodes.codes_release(gid)


class FakeEcmwf:
    """Serves waef index and GRIB byte ranges like data.ecmwf.int."""

    def __init__(self, runs: list[datetime], steps: tuple[int, ...], fail_first: int = 0, truncate: bool = False):
        self.runs = runs
        self.steps = steps
        self.fail_first = fail_first
        self.truncate = truncate
        self.requests = 0
        self.files: dict[str, tuple[bytes, list[dict]]] = {}
        for run_time in runs:
            for step in steps:
                blob, rows = b"", []
                for number in (1, 2):
                    # HR1's nearest point (55.5, 7.75) is missing, so (55.5, 8.0) is used;
                    # HR2's nearest point is (55.5, 7.5).
                    message = grib_message(
                        {(55.5, 7.75): 9999, (55.5, 8.0): number + step / 100, (55.5, 7.5): 10 + number}
                    )
                    rows.append({"param": "swh", "type": "pf", "number": str(number), "_offset": len(blob), "_length": len(message)})
                    blob += message
                    rows.append({"param": "mwp", "type": "pf", "number": str(number), "_offset": len(blob), "_length": 10})
                    blob += b"x" * 10
                self.files[ecmwf_waef._url(run_time, step, "grib2")] = (blob, rows)

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests += 1
        if self.fail_first > 0:
            self.fail_first -= 1
            return httpx.Response(503)
        url = str(request.url)
        if url.endswith(".index"):
            grib = url.removesuffix("index") + "grib2"
            if grib not in self.files:
                return httpx.Response(404)
            if request.method == "HEAD":
                return httpx.Response(200)
            return httpx.Response(200, text="\n".join(json.dumps(row) for row in self.files[grib][1]))
        blob, _ = self.files[url]
        start, end = (int(x) for x in request.headers["Range"].removeprefix("bytes=").split("-"))
        content = blob[start : end + 1]
        return httpx.Response(206, content=content[:-1] if self.truncate else content)


class WaveEnsembleTests(unittest.TestCase):
    def test_interpolates_six_hourly_values(self) -> None:
        waves = wave_ensemble()
        times = [waves.run + timedelta(hours=h) for h in (-1, 0, 3, 6, 23, 24, 30)]

        self.assertEqual(hourly(waves, 1, times), [None, 1.0, 1.3, 1.6, 2.2, 2.2, None])
        self.assertEqual(hourly(waves, 99, times[:2]), [None, None])

    def test_candidate_runs_are_00_and_12_utc(self) -> None:
        self.assertEqual(
            candidate_runs(datetime(2026, 10, 31, 9, 30, tzinfo=UTC))[:2],
            [datetime(2026, 10, 31, 0, tzinfo=UTC), datetime(2026, 10, 30, 12, tzinfo=UTC)],
        )
        self.assertEqual(candidate_runs(datetime(2026, 10, 31, 13, tzinfo=UTC))[0], datetime(2026, 10, 31, 12, tzinfo=UTC))

    def test_round_trip(self) -> None:
        waves = wave_ensemble()

        self.assertEqual(WaveEnsemble.from_dict(json.loads(json.dumps(waves.to_dict()))), waves)

    def test_latest_complete_run_skips_unpublished(self) -> None:
        fake = FakeEcmwf([RUN], ecmwf_waef.STEPS)
        now = RUN + timedelta(hours=14)  # the 12 UTC run is not published yet

        async def latest():
            async with httpx.AsyncClient(transport=httpx.MockTransport(fake.handler)) as client:
                return await ecmwf_waef.latest_complete_run(client, now)

        self.assertEqual(run(latest()), RUN)

    def download(self, fake: FakeEcmwf):
        async def go():
            async with httpx.AsyncClient(transport=httpx.MockTransport(fake.handler)) as client:
                return await ecmwf_waef.download_run(RUN, [SITES["hr1"], SITES["hr2"]], client)

        with patch.object(ecmwf_waef, "STEPS", fake.steps), patch.object(ecmwf_waef.asyncio, "sleep", AsyncMock()):
            return run(go())

    def test_download_decodes_nearest_valid_point_per_site(self) -> None:
        result = self.download(FakeEcmwf([RUN], (0, 6, 12)))

        hr1 = result["hr1"]
        self.assertEqual(hr1.times, [RUN, RUN + timedelta(hours=6), RUN + timedelta(hours=12)])
        self.assertEqual(sorted(hr1.members), [1, 2])
        # Missing nearest point skipped in favour of the next valid one.
        self.assertEqual((hr1.grid_latitude, hr1.grid_longitude), (55.5, 8.0))
        self.assertEqual([round(v or 0, 2) for v in hr1.members[2]], [2.0, 2.06, 2.12])
        hr2 = result["hr2"]
        self.assertEqual((hr2.grid_latitude, hr2.grid_longitude), (55.5, 7.5))
        self.assertEqual(hr2.members[1], [11.0, 11.0, 11.0])

    def test_download_retries_transient_failures(self) -> None:
        fake = FakeEcmwf([RUN], (0, 6), fail_first=2)

        result = self.download(fake)

        self.assertEqual(len(result["hr1"].members), 2)

    def test_download_fails_cleanly(self) -> None:
        with self.assertRaises(WaveDataError):
            self.download(FakeEcmwf([RUN], (0, 6), truncate=True))
        with self.assertRaises(WaveDataError):
            self.download(FakeEcmwf([RUN], (0, 6), fail_first=100))


class WaveEnsembleErrorTests(unittest.TestCase):
    def serve(self, index_text: str | None = None, grib: bytes | None = None):
        def handler(request: httpx.Request) -> httpx.Response:
            if str(request.url).endswith(".index"):
                return httpx.Response(200 if index_text is not None else 404, text=index_text or "")
            return httpx.Response(206, content=grib or b"")

        async def go():
            async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
                return await ecmwf_waef.download_run(RUN, [SITES["hr1"]], client)

        with patch.object(ecmwf_waef, "STEPS", (0,)), patch.object(ecmwf_waef.asyncio, "sleep", AsyncMock()):
            return run(go())

    def test_unreadable_index(self) -> None:
        with self.assertRaisesRegex(WaveDataError, "unreadable index"):
            self.serve("{not json")

    def test_index_without_swh(self) -> None:
        with self.assertRaisesRegex(WaveDataError, "no swh members"):
            self.serve(json.dumps({"param": "mwp", "type": "pf", "number": "1", "_offset": 0, "_length": 1}))

    def test_grid_without_valid_values_near_site(self) -> None:
        message = grib_message({(lat, lon): 9999 for lat in (55.25, 55.5, 55.75) for lon in (7.5, 7.75, 8.0)})
        index = json.dumps({"param": "swh", "type": "pf", "number": "1", "_offset": 0, "_length": len(message)})

        with self.assertRaisesRegex(WaveDataError, "No valid ECMWF wave values"):
            self.serve(index, message)

    def test_reports_progress(self) -> None:
        fake = FakeEcmwf([RUN], (0, 6))
        progress = []

        async def go():
            async with httpx.AsyncClient(transport=httpx.MockTransport(fake.handler)) as client:
                return await ecmwf_waef.download_run(
                    RUN, [SITES["hr1"]], client, on_step=lambda done, total: progress.append((done, total))
                )

        with patch.object(ecmwf_waef, "STEPS", fake.steps):
            run(go())

        self.assertEqual(progress, [(1, 2), (2, 2)])

    def test_no_published_run(self) -> None:
        async def go():
            async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _r: httpx.Response(404))) as client:
                return await ecmwf_waef.latest_complete_run(client, RUN)

        self.assertIsNone(run(go()))

    def test_cli_downloads_and_saves(self) -> None:
        store = Store(":memory:")
        saved = {}
        store.save_waves = lambda site_id, run_time, payload: saved.update({site_id: payload})  # type: ignore[method-assign]
        result = {"hr1": wave_ensemble(RUN)}

        with (
            patch("backend.store.Store", return_value=store),
            patch.object(ecmwf_waef, "latest_complete_run", AsyncMock(return_value=RUN)),
            patch.object(ecmwf_waef, "download_run", AsyncMock(return_value=result)),
            redirect_stdout(io.StringIO()) as output,
        ):
            run(ecmwf_waef._main())

        self.assertEqual(saved["hr1"]["run"], RUN.isoformat())
        self.assertIn("Saved 1 sites", output.getvalue())
        # The CLI closes its database when done.
        with self.assertRaises(sqlite3.ProgrammingError):
            store.latest_waves("hr1")

    def test_cli_exits_when_nothing_is_published(self) -> None:
        with (
            patch("backend.store.Store", return_value=Store(":memory:")),
            patch.object(ecmwf_waef, "latest_complete_run", AsyncMock(return_value=None)),
            self.assertRaises(SystemExit),
        ):
            run(ecmwf_waef._main())


class LightningTests(unittest.TestCase):
    now = datetime(2026, 11, 16, 12, tzinfo=UTC)

    def strike(self, lon_offset: float, minutes_ago: int) -> dict:
        site = SITES["hr1"]
        observed = (self.now - timedelta(minutes=minutes_ago)).isoformat().replace("+00:00", "Z")
        return {
            "geometry": {"coordinates": [site.longitude + lon_offset, site.latitude]},
            "properties": {"observed": observed},
        }

    def test_counts_strikes_by_radius(self) -> None:
        summary = summarize(
            [self.strike(0.2, 5), self.strike(1.0, 20), self.strike(2.0, 1)],  # ~13, ~63, ~126 km
            SITES["hr1"],
            self.now - timedelta(hours=1),
            self.now,
            truncated=False,
        )

        self.assertEqual(summary.strikes_within_48km, 1)
        self.assertEqual(summary.strikes_within_80km, 2)
        self.assertEqual(summary.last_within_48km, self.now - timedelta(minutes=5))
        self.assertEqual(summary.last_within_80km, self.now - timedelta(minutes=5))
        self.assertAlmostEqual(summary.nearest_km or 0, 12.6, delta=0.5)

    def test_no_strikes(self) -> None:
        summary = summarize([], SITES["hr1"], self.now, self.now, truncated=False)

        self.assertEqual((summary.strikes_within_80km, summary.nearest_km, summary.last_within_48km), (0, None, None))

    def test_fetch_queries_bbox_and_period(self) -> None:
        seen = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen.update(request.url.params)
            return httpx.Response(200, json={"type": "FeatureCollection", "features": [self.strike(0.1, 2)]})

        async def go():
            async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
                return await fetch_lightning(SITES["hr1"], self.now, minutes=30, client=client)

        summary = run(go())

        self.assertEqual(summary.strikes_within_48km, 1)
        self.assertEqual(seen["datetime"], "2026-11-16T11:30:00Z/2026-11-16T12:00:00Z")
        west, south, east, north = (float(v) for v in seen["bbox"].split(","))
        site = SITES["hr1"]
        self.assertLess(west, site.longitude)
        self.assertGreater(east, site.longitude)
        self.assertLess(south, site.latitude)
        self.assertGreater(north, site.latitude)
        # The box spans 80 km either way: about 0.72 degrees of latitude.
        self.assertAlmostEqual(north - site.latitude, 0.72, delta=0.01)

    def test_fetch_errors_raise_lightning_error(self) -> None:
        responses = [
            httpx.Response(500),
            httpx.Response(200, content=b"not json"),
            httpx.Response(200, json={"features": "nope"}),
            httpx.Response(200, json={"features": [{"geometry": None}]}),
        ]
        for response in responses:
            with self.subTest(status=response.status_code):

                async def go(response=response):
                    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _r: response)) as client:
                        return await fetch_lightning(SITES["hr1"], self.now, client=client)

                with self.assertRaises(LightningError):
                    run(go())


if __name__ == "__main__":
    unittest.main()
