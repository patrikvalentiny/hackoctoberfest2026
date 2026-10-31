import asyncio
import json
import os
import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient
from support import ApiTestCase, make_forecast, provider_payloads, wave_ensemble

from backend.api import planner
from backend.engine.briefing import build_pack
from backend.ingest.dmi_lightning import LightningError, LightningSummary
from backend.ingest.open_meteo import ProviderError
from backend.main import app
from backend.store import Store


def recent_payloads(hours_ago: float = 0) -> tuple[datetime, dict]:
    """Calm provider payloads starting at today's UTC midnight."""
    now = datetime.now(UTC)
    start = now.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=1)
    return now - timedelta(hours=hours_ago), provider_payloads(hours=96, start=start)


class ProfileTests(ApiTestCase):
    def test_sites(self) -> None:
        sites = self.client.get("/api/sites").json()["sites"]

        self.assertEqual([site["id"] for site in sites], ["hr1", "hr2", "hr3"])
        self.assertTrue(all(site["coordinates_verified"] is False for site in sites))

    def test_profile_echoes_limits_and_defaults(self) -> None:
        profile = self.create_profile(vessel="sov", task="lifting", sov_hs_limit_m=3.0)

        self.assertEqual(len(profile["profile_id"]), 8)
        limits = {limit["id"]: limit["value"] for limit in profile["limits"]}
        self.assertEqual(limits, {"wave_height": 3.0, "wind_100m": 10.0, "visibility": 1000.0})
        self.assertEqual(profile["transit_hours_each_way"], 0.0)
        start = datetime.fromisoformat(profile["start_date"]).date()
        self.assertEqual((datetime.fromisoformat(profile["end_date"]).date() - start).days, 20)
        self.assertIn("decide", profile["disclaimer"])
        self.assertTrue(profile["not_evaluated"])

    def test_profile_validation(self) -> None:
        cases = {
            "unknown site": {"site_id": "hr9"},
            "ctv custom hs": {"sov_hs_limit_m": 2.5},
            "sov hs too high": {"vessel": "sov", "sov_hs_limit_m": 4.0},
            "zero hours": {"work_hours_per_day": 0},
            "too many hours": {"work_hours_per_day": 13},
            "range over 21 days": {"start_date": "2026-11-01", "end_date": "2026-11-30"},
            "end before start": {"start_date": "2026-11-10", "end_date": "2026-11-09"},
            "more days than range": {"start_date": "2026-11-10", "end_date": "2026-11-11", "days_needed": 3},
            "unknown task": {"task": "painting"},
        }
        for name, body in cases.items():
            with self.subTest(name):
                response = self.client.post(
                    "/api/profiles",
                    json={"site_id": "hr1", "vessel": "ctv", "task": "nacelle", "work_hours_per_day": 4, **body},
                )
                self.assertEqual(response.status_code, 422, response.text)

    def test_unknown_profile_is_404(self) -> None:
        for path in ("windows", "days/2026-11-16", "task-fit?start=2026-11-16T10:00&duration_minutes=30", "briefing-pack"):
            with self.subTest(path):
                self.assertEqual(self.client.get(f"/api/profiles/nope/{path}").status_code, 404)


class PlannerEndpointTests(ApiTestCase):
    def setUp(self) -> None:
        super().setUp()
        start = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
        planner._forecasts["hr1"] = make_forecast(
            fetched_at=datetime.now(UTC) - timedelta(minutes=5), start=start - timedelta(days=1), days=17
        )

    def test_windows_shape(self) -> None:
        profile = self.create_profile(days_needed=2)

        payload = self.client.get(f"/api/profiles/{profile['profile_id']}/windows").json()

        self.assertEqual(len(payload["days"]), 21)
        self.assertEqual(len(payload["suggested_days"]), 2)
        self.assertEqual(payload["data"]["freshness"], "fresh")
        self.assertFalse(payload["data"]["offline"])
        day = next(day for day in payload["days"] if day["window"])
        self.assertTrue(day["window"]["start"]["utc"].endswith("Z"))
        self.assertRegex(day["window"]["start"]["local"], r"\+0[12]:00$")
        self.assertIn(payload["days"][-1]["confidence"], {"outlook", "low"})

    def test_explain_day(self) -> None:
        profile = self.create_profile()
        day = profile["start_date"]

        payload = self.client.get(f"/api/profiles/{profile['profile_id']}/days/{day}").json()

        self.assertEqual(len(payload["hours"]), 24)
        self.assertEqual(payload["day"]["date"], day)
        self.assertEqual({limit["id"] for limit in payload["limits"]}, {"wave_height", "wind_100m", "visibility"})

    def test_task_fit_treats_naive_start_as_local_time(self) -> None:
        profile = self.create_profile()
        tomorrow = (datetime.now(planner.LOCAL_TZ) + timedelta(days=1)).date()

        payload = self.client.get(
            f"/api/profiles/{profile['profile_id']}/task-fit",
            params={"start": f"{tomorrow}T10:00", "duration_minutes": 90},
        ).json()

        self.assertTrue(payload["start"]["local"].startswith(f"{tomorrow}T10:00"))
        self.assertTrue(payload["fits"])
        self.assertIsNotNone(payload["latest_start"])
        self.assertIsNotNone(payload["last_transfer_back"])

    def test_task_fit_validates_duration(self) -> None:
        profile = self.create_profile()
        for minutes in (0, 721):
            response = self.client.get(
                f"/api/profiles/{profile['profile_id']}/task-fit",
                params={"start": "2026-11-16T10:00", "duration_minutes": minutes},
            )
            self.assertEqual(response.status_code, 422)

    def test_conditions_now_with_lightning(self) -> None:
        now = datetime.now(UTC)
        summary = LightningSummary(now - timedelta(hours=1), now, 2, 5, 31.4, now - timedelta(minutes=3), now, False)

        with patch.object(planner, "fetch_lightning", AsyncMock(return_value=summary)) as fetch:
            payload = self.client.get("/api/conditions-now", params={"site_id": "hr1"}).json()

        fetch.assert_awaited_once()
        self.assertEqual(fetch.await_args.kwargs["minutes"], 60)
        lightning = payload["lightning"]
        self.assertTrue(lightning["available"])
        self.assertEqual((lightning["strikes_within_48km"], lightning["strikes_within_80km"]), (2, 5))
        self.assertTrue(lightning["last_within_48km"]["utc"].endswith("Z"))
        self.assertEqual(payload["limits_from"], "default CTV nacelle profile")
        self.assertIsNotNone(payload["forecast_now"])
        self.assertIn("not observations", payload["forecast_note"])
        self.assertIn("48 km", payload["lightning_procedure_reference"])

    def test_conditions_now_reports_lightning_failure(self) -> None:
        profile = self.create_profile(task="lifting")

        with patch.object(planner, "fetch_lightning", AsyncMock(side_effect=LightningError("DMI lightning data is unavailable."))):
            payload = self.client.get(
                "/api/conditions-now", params={"site_id": "hr1", "profile_id": profile["profile_id"]}
            ).json()

        self.assertFalse(payload["lightning"]["available"])
        self.assertIn("unavailable", payload["lightning"]["note"])
        self.assertEqual(payload["limits_from"], "profile")
        wind = next(limit for limit in payload["forecast_now"]["limits"] if limit["id"] == "wind_100m")
        self.assertEqual(wind["limit"], 10.0)

    def test_conditions_now_rejects_profile_for_other_site(self) -> None:
        profile = self.create_profile(site_id="hr2")

        response = self.client.get("/api/conditions-now", params={"site_id": "hr1", "profile_id": profile["profile_id"]})

        self.assertEqual(response.status_code, 422)

    def test_data_status(self) -> None:
        payload = self.client.get("/api/data-status", params={"site_id": "hr1"}).json()

        self.assertFalse(payload["offline"])
        self.assertTrue(payload["live_lightning"])
        self.assertIn("state", payload["wave_ensemble_download"])
        self.assertEqual(self.client.get("/api/data-status", params={"site_id": "x"}).status_code, 422)


class ForecastCacheTests(ApiTestCase):
    def test_fresh_forecast_is_fetched_once_and_stored(self) -> None:
        _, payloads = recent_payloads()

        with patch.object(planner, "fetch_payloads", AsyncMock(return_value=payloads)) as fetch:
            self.client.get("/api/data-status", params={"site_id": "hr1"})
            self.client.get("/api/data-status", params={"site_id": "hr1"})

        fetch.assert_awaited_once()
        self.assertIsNotNone(self.store.latest_payloads("hr1"))

    def test_restart_reuses_stored_payloads_within_ttl(self) -> None:
        fetched, payloads = recent_payloads(hours_ago=1)
        self.store.save_payloads("hr1", fetched, payloads)

        with patch.object(planner, "fetch_payloads", AsyncMock(side_effect=AssertionError("should not fetch"))):
            payload = self.client.get("/api/data-status", params={"site_id": "hr1"}).json()

        self.assertEqual(payload["data"]["age_hours"], 1.0)

    def test_expired_cache_is_refreshed(self) -> None:
        fetched, payloads = recent_payloads(hours_ago=4)
        self.store.save_payloads("hr1", fetched, payloads)

        with patch.object(planner, "fetch_payloads", AsyncMock(return_value=payloads)) as fetch:
            payload = self.client.get("/api/data-status", params={"site_id": "hr1"}).json()

        fetch.assert_awaited_once()
        self.assertEqual(payload["data"]["age_hours"], 0.0)

    def test_failed_refresh_falls_back_to_stored_forecast_with_note(self) -> None:
        fetched, payloads = recent_payloads(hours_ago=5)
        self.store.save_payloads("hr1", fetched, payloads)

        with patch.object(planner, "fetch_payloads", AsyncMock(side_effect=ProviderError("Open-Meteo is unavailable."))):
            payload = self.client.get("/api/data-status", params={"site_id": "hr1"}).json()

        self.assertEqual(payload["data"]["age_hours"], 5.0)
        self.assertIn("Live refresh failed", payload["notes"][0])

    def test_failed_refresh_without_stored_data_is_502(self) -> None:
        with patch.object(planner, "fetch_payloads", AsyncMock(side_effect=ProviderError("Open-Meteo is unavailable."))):
            response = self.client.get("/api/data-status", params={"site_id": "hr2"})

        self.assertEqual(response.status_code, 502)
        self.assertEqual(response.json()["detail"], "Open-Meteo is unavailable.")

    def test_unusable_payloads_are_not_cached(self) -> None:
        _, payloads = recent_payloads()
        payloads["marine"] = {"hourly": {"time": []}}

        with patch.object(planner, "fetch_payloads", AsyncMock(return_value=payloads)):
            response = self.client.get("/api/data-status", params={"site_id": "hr1"})

        self.assertEqual(response.status_code, 502)
        self.assertIsNone(self.store.latest_payloads("hr1"))

    def test_corrupt_stored_payloads_are_ignored(self) -> None:
        self.store.save_payloads("hr1", datetime.now(UTC), {"ensemble": None})
        _, payloads = recent_payloads()

        with (
            patch.object(planner, "fetch_payloads", AsyncMock(return_value=payloads)) as fetch,
            self.assertLogs(planner.logger, "WARNING"),
        ):
            response = self.client.get("/api/data-status", params={"site_id": "hr1"})

        self.assertEqual(response.status_code, 200)
        fetch.assert_awaited_once()

    def test_stored_wave_ensemble_is_used(self) -> None:
        fetched, payloads = recent_payloads()
        # Today's 00 UTC run: recent enough to pair with the wind forecast.
        run = fetched.replace(hour=0, minute=0, second=0, microsecond=0)
        self.store.save_payloads("hr1", fetched, payloads)
        self.store.save_waves("hr1", run, wave_ensemble(run=run).to_dict())

        payload = self.client.get("/api/data-status", params={"site_id": "hr1"}).json()

        self.assertIn("wave_ensemble", [source["id"] for source in payload["sources"]])
        self.assertIsNotNone(payload["data"]["wave_ensemble_run"])


class OfflineTests(ApiTestCase):
    def setUp(self) -> None:
        super().setUp()
        start = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
        planner._forecasts["hr1"] = make_forecast(
            fetched_at=datetime.now(UTC) - timedelta(hours=1), start=start - timedelta(days=1), days=17
        )

    def test_pack_download_then_offline_tools(self) -> None:
        profile = self.create_profile()
        response = self.client.get(f"/api/profiles/{profile['profile_id']}/briefing-pack")
        self.assertIn("attachment", response.headers["content-disposition"])
        pack = response.json()
        planner._forecasts.clear()
        planner._profiles.clear()

        loaded = self.client.post("/api/briefing-pack", json=pack)
        self.assertEqual(loaded.status_code, 200)
        self.assertTrue(loaded.json()["data"]["offline"])

        no_network = AsyncMock(side_effect=AssertionError("no network offline"))
        with patch.object(planner, "fetch_payloads", no_network), patch.object(planner, "fetch_lightning", no_network):
            windows = self.client.get(f"/api/profiles/{profile['profile_id']}/windows")
            conditions = self.client.get("/api/conditions-now", params={"site_id": "hr1"})
            status = self.client.get("/api/data-status", params={"site_id": "hr1"})
            # A new profile for the offline site also uses the pack.
            other = self.create_profile(vessel="sov", task="lifting")
            other_windows = self.client.get(f"/api/profiles/{other['profile_id']}/windows")

        self.assertEqual(windows.status_code, 200)
        self.assertEqual(windows.json()["data"]["age_hours"], 1.0)
        self.assertFalse(conditions.json()["lightning"]["available"])
        self.assertIn("Offline", conditions.json()["lightning"]["note"])
        self.assertTrue(status.json()["offline"])
        self.assertFalse(status.json()["live_lightning"])
        self.assertEqual(other_windows.status_code, 200)

        self.assertFalse(self.client.delete("/api/briefing-pack/hr1").json()["offline"])
        self.assertEqual(self.client.delete("/api/briefing-pack/hr1").status_code, 404)

    def test_oversized_pack_is_a_server_error(self) -> None:
        profile = self.create_profile()

        with patch.object(planner, "build_pack", side_effect=planner.BriefingPackError("too big")):
            response = self.client.get(f"/api/profiles/{profile['profile_id']}/briefing-pack")

        self.assertEqual(response.status_code, 500)

    def test_rejects_invalid_packs(self) -> None:
        for body in ({"format": "nope"}, {"format": "harbour-pulse-briefing-pack", "version": 99}, {"format": "harbour-pulse-briefing-pack", "version": 1}):
            with self.subTest(body=body):
                self.assertEqual(self.client.post("/api/briefing-pack", json=body).status_code, 422)


class WaveEnsembleJobTests(ApiTestCase):
    def test_skips_download_when_latest_run_is_stored(self) -> None:
        run = datetime(2026, 11, 10, tzinfo=UTC)
        for site_id in planner.SITES:
            self.store.save_waves(site_id, run, wave_ensemble(run).to_dict())

        with (
            patch.object(planner.ecmwf_waef, "latest_complete_run", AsyncMock(return_value=run)),
            patch.object(planner.ecmwf_waef, "download_run", AsyncMock(side_effect=AssertionError("no download"))),
        ):
            asyncio.run(planner.refresh_wave_ensemble())

        self.assertEqual(planner._waef_status["state"], "ready")

    def test_downloads_new_run_and_clears_forecasts(self) -> None:
        run = datetime(2026, 11, 10, 12, tzinfo=UTC)
        planner._forecasts["hr1"] = make_forecast()
        result = {site_id: wave_ensemble(run) for site_id in planner.SITES}

        with (
            patch.object(planner.ecmwf_waef, "latest_complete_run", AsyncMock(return_value=run)),
            patch.object(planner.ecmwf_waef, "download_run", AsyncMock(return_value=result)),
        ):
            asyncio.run(planner.refresh_wave_ensemble())

        self.assertEqual(planner._forecasts, {})
        self.assertEqual(self.store.latest_waves("hr2")["run"], run.isoformat())
        self.assertEqual(planner._waef_status["state"], "ready")

    def test_reports_download_progress(self) -> None:
        run = datetime(2026, 11, 10, 12, tzinfo=UTC)
        seen = []

        async def fake_download(_run, _sites, _client, on_step):
            on_step(1, 61)
            seen.append(dict(planner._waef_status))
            return {site_id: wave_ensemble(run) for site_id in planner.SITES}

        with (
            patch.object(planner.ecmwf_waef, "latest_complete_run", AsyncMock(return_value=run)),
            patch.object(planner.ecmwf_waef, "download_run", fake_download),
        ):
            asyncio.run(planner.refresh_wave_ensemble())

        self.assertEqual((seen[0]["state"], seen[0]["steps_done"], seen[0]["steps_total"]), ("downloading", 1, 61))

    def test_loop_records_download_errors(self) -> None:
        with (
            patch.object(planner, "refresh_wave_ensemble", AsyncMock(side_effect=planner.WaveDataError("offline"))),
            patch.object(planner.asyncio, "sleep", AsyncMock(side_effect=asyncio.CancelledError())),
            self.assertLogs(planner.logger, "WARNING"),
            self.assertRaises(asyncio.CancelledError),
        ):
            asyncio.run(planner._wave_ensemble_loop())

        self.assertEqual((planner._waef_status["state"], planner._waef_status["message"]), ("error", "offline"))

    def test_waits_when_no_run_is_published(self) -> None:
        with patch.object(planner.ecmwf_waef, "latest_complete_run", AsyncMock(return_value=None)):
            asyncio.run(planner.refresh_wave_ensemble())

        self.assertEqual(planner._waef_status["state"], "waiting")

    def test_loop_survives_unexpected_errors(self) -> None:
        stop = asyncio.CancelledError()

        with (
            patch.object(planner, "refresh_wave_ensemble", AsyncMock(side_effect=RuntimeError("boom"))),
            patch.object(planner.asyncio, "sleep", AsyncMock(side_effect=stop)),
            self.assertLogs(planner.logger, "ERROR"),
            self.assertRaises(asyncio.CancelledError),
        ):
            asyncio.run(planner._wave_ensemble_loop())

        self.assertEqual(planner._waef_status["state"], "error")
        self.assertIn("boom", planner._waef_status["message"])


class LifespanTests(unittest.TestCase):
    def tearDown(self) -> None:
        planner._offline.clear()
        planner._profiles.clear()

    def test_loads_pack_from_env_relative_to_repo_root(self) -> None:
        profile_forecast = make_forecast(fetched_at=datetime.now(UTC))
        from support import make_profile

        pack = json.loads(json.dumps(build_pack(make_profile(id="envpack"), profile_forecast, {}, datetime.now(UTC)), default=str))
        with tempfile.NamedTemporaryFile("w", suffix=".json", dir=planner.REPO_ROOT / "data", delete=False) as handle:
            json.dump(pack, handle)
        path = Path(handle.name)
        self.addCleanup(path.unlink)

        env = {"HARBOUR_PULSE_PACK": str(path.relative_to(planner.REPO_ROOT)), "HARBOUR_PULSE_WAEF": "0"}
        with patch.dict(os.environ, env), TestClient(app) as client:
            response = client.get("/api/profiles/envpack/windows")

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["data"]["offline"])

    def test_waef_job_runs_unless_disabled(self) -> None:
        with (
            patch.object(planner, "_wave_ensemble_loop", AsyncMock()) as loop,
            patch.dict(os.environ, {"HARBOUR_PULSE_WAEF": "1"}),
            TestClient(app),
        ):
            pass
        loop.assert_awaited_once()

        with (
            patch.object(planner, "_wave_ensemble_loop", AsyncMock()) as loop,
            patch.dict(os.environ, {"HARBOUR_PULSE_WAEF": "0"}),
            TestClient(app),
        ):
            pass
        loop.assert_not_called()


class SnapshotTests(ApiTestCase):
    def test_writes_loadable_pack(self) -> None:
        from backend import snapshot

        _, payloads = recent_payloads()
        with (
            tempfile.TemporaryDirectory() as directory,
            patch.object(snapshot, "DATA_DIR", Path(directory)),
            patch.object(snapshot, "fetch_payloads", AsyncMock(return_value=payloads)),
            patch("builtins.print"),
        ):
            asyncio.run(snapshot.main("hr1"))
            files = list((Path(directory) / "snapshots").glob("hr1-*.json"))
            self.assertEqual(len(files), 1)
            pack = json.loads(files[0].read_text())

        self.assertEqual(self.client.post("/api/briefing-pack", json=pack).status_code, 200)
        self.assertEqual(pack["profile"]["days_needed"], 4)
        self.assertLess(len(json.dumps(pack)), 1_000_000)


class StoreTests(unittest.TestCase):
    def test_payload_round_trip_and_latest_wave_run(self) -> None:
        store = Store(":memory:")
        self.addCleanup(store.close)
        fetched = datetime(2026, 11, 10, 6, tzinfo=UTC)
        older, newer = wave_ensemble(), wave_ensemble(datetime(2026, 11, 10, 12, tzinfo=UTC))

        store.save_payloads("hr1", fetched, {"a": [1, None]})
        store.save_waves("hr1", newer.run, newer.to_dict())
        store.save_waves("hr1", older.run, older.to_dict())

        self.assertEqual(store.latest_payloads("hr1"), (fetched, {"a": [1, None]}))
        self.assertIsNone(store.latest_payloads("hr2"))
        self.assertEqual(store.latest_waves("hr1")["run"], newer.run.isoformat())

    def test_creates_database_directory(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = Store(Path(directory) / "nested" / "cache.sqlite3")
            store.save_payloads("hr1", datetime.now(UTC), {})
            store.close()
            self.assertTrue((Path(directory) / "nested" / "cache.sqlite3").exists())


if __name__ == "__main__":
    unittest.main()
