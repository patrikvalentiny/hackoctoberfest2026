import json
import unittest
from datetime import UTC, date, datetime, timedelta
from unittest.mock import patch

from fastapi.testclient import TestClient

from backend.api import planner
from backend.engine.briefing import MAX_BYTES, BriefingPackError, build_pack, load_pack
from backend.engine.forecast import WeeklyOutlook, forecast_from_dict, forecast_to_dict
from backend.engine.profiles import SITES, profile_from_dict, profile_to_dict
from backend.engine.windows import evaluate_day, find_windows
from backend.ingest.dmi_lightning import summarize
from backend.ingest.ecmwf_waef import WaveEnsemble, candidate_runs, hourly
from backend.ingest.open_meteo import ProviderError, build_site_forecast
from backend.main import app
from backend.store import Store
from test_engine import DAY, make_forecast, make_profile


def provider_payloads(hours: int = 48) -> dict:
    start = datetime(2026, 11, 10, tzinfo=UTC)
    times = [(start + timedelta(hours=h)).strftime("%Y-%m-%dT%H:%M") for h in range(hours)]
    ensemble = {"time": times, "wind_speed_10m": [5.0] * hours, "wind_speed_100m": [7.0] * hours}
    for member in (1, 2):
        ensemble[f"wind_speed_10m_member{member:02}"] = [5.0 + member] * hours
        ensemble[f"wind_speed_100m_member{member:02}"] = [7.0 + member] * hours
    return {
        "ensemble": {"hourly": ensemble},
        "marine": {
            "hourly": {
                "time": times,
                "wave_height": [1.0] * hours,
                "wave_period": [6.0] * hours,
                "wave_direction": [220.0] * hours,
            }
        },
        "swell": None,
        "visibility": {"hourly": {"time": times, "visibility": [20000.0] * hours}},
        "dmi": {
            "hourly": {
                "time": times,
                "wind_speed_10m": [4.0] * hours,
                "wind_speed_100m": [6.0] * hours,
                "visibility": [21000.0] * hours,
            }
        },
        "seasonal": {
            "weekly": {
                "time": ["2026-11-09", "2026-11-16"],
                "wind_speed_10m_mean": [6.5, 8.0],
                "wind_speed_10m_anomaly": [0.5, 1.2],
            }
        },
    }


def wave_ensemble() -> WaveEnsemble:
    run = datetime(2026, 11, 10, tzinfo=UTC)
    return WaveEnsemble(
        run=run,
        times=[run + timedelta(hours=6 * i) for i in range(5)],
        members={1: [1.0, 1.6, 2.2, 2.2, 2.2], 2: [0.5, 0.5, 0.5, 0.5, 0.5]},
        grid_latitude=55.5,
        grid_longitude=7.75,
    )


class WaveEnsembleTests(unittest.TestCase):
    def test_interpolates_six_hourly_values(self) -> None:
        waves = wave_ensemble()
        times = [waves.run + timedelta(hours=h) for h in (0, 3, 6, 30)]

        self.assertEqual(hourly(waves, 1, times), [1.0, 1.3, 1.6, None])

    def test_candidate_runs_are_00_and_12_utc(self) -> None:
        runs = candidate_runs(datetime(2026, 10, 31, 9, 30, tzinfo=UTC))

        self.assertEqual(runs[0], datetime(2026, 10, 31, 0, tzinfo=UTC))
        self.assertEqual(runs[1], datetime(2026, 10, 30, 12, tzinfo=UTC))

    def test_pairs_wind_and_wave_members_by_number(self) -> None:
        forecast = build_site_forecast(SITES["hr1"], provider_payloads(), datetime.now(UTC), wave_ensemble())

        # Control wind run has no waef pair, so members 1 and 2 remain.
        self.assertEqual(forecast.ensemble.members, 2)
        self.assertEqual(forecast.ensemble.variables["wind_speed_100m_ms"][0][0], 8.0)
        self.assertEqual(forecast.ensemble.variables["wave_height_m"][0][3], 1.3)
        self.assertEqual(forecast.ensemble.variables["wave_height_m"][1][3], 0.5)
        # After the last waef step, deterministic WAM fills in.
        self.assertEqual(forecast.ensemble.variables["wave_height_m"][0][40], 1.0)
        self.assertNotIn("wave_height_m", forecast.ensemble.deterministic_variables)
        self.assertIn("wave_ensemble", [source.id for source in forecast.sources])

    def test_without_waves_heights_are_shared_and_labelled(self) -> None:
        forecast = build_site_forecast(SITES["hr1"], provider_payloads(), datetime.now(UTC))

        self.assertEqual(forecast.ensemble.members, 3)
        self.assertIn("wave_height_m", forecast.ensemble.deterministic_variables)
        self.assertTrue(any("deterministic" in note for note in forecast.notes))

    def test_missing_required_payload_is_an_error(self) -> None:
        payloads = provider_payloads()
        payloads["marine"] = {"hourly": {"time": []}}

        with self.assertRaises(ProviderError):
            build_site_forecast(SITES["hr1"], payloads, datetime.now(UTC))


class SerializationTests(unittest.TestCase):
    def test_forecast_round_trip(self) -> None:
        forecast = build_site_forecast(SITES["hr1"], provider_payloads(), datetime.now(UTC), wave_ensemble())

        restored = forecast_from_dict(json.loads(json.dumps(forecast_to_dict(forecast))))

        self.assertEqual(restored.times, forecast.times)
        self.assertEqual(restored.ensemble.variables, forecast.ensemble.variables)
        self.assertEqual(restored.sources, forecast.sources)
        self.assertEqual(restored.weekly_outlook, forecast.weekly_outlook)

    def test_profile_round_trip_keeps_limits(self) -> None:
        profile = make_profile("sov", "lifting")

        self.assertEqual(profile_from_dict(json.loads(json.dumps(profile_to_dict(profile)))), profile)


class BriefingPackTests(unittest.TestCase):
    def test_full_size_pack_fits_under_limit_and_reloads(self) -> None:
        # 51 members over 15 days is the real shape.
        forecast = make_forecast(members=51, days=15)
        profile = make_profile()

        pack = build_pack(profile, forecast, {"days": []}, datetime.now(UTC))
        size = len(json.dumps(pack, separators=(",", ":"), default=str).encode())
        loaded_profile, loaded_forecast = load_pack(json.loads(json.dumps(pack, default=str)))

        self.assertLess(size, MAX_BYTES)
        self.assertEqual(loaded_profile, profile)
        self.assertEqual(
            evaluate_day(loaded_profile, loaded_forecast, DAY).probability,
            evaluate_day(profile, forecast, DAY).probability,
        )

    def test_rejects_other_files(self) -> None:
        with self.assertRaises(BriefingPackError):
            load_pack({"format": "something-else"})


class OutlookAndRankingTests(unittest.TestCase):
    def test_outlook_day_carries_weekly_signal(self) -> None:
        forecast = make_forecast(days=10)
        forecast = forecast.__class__(
            **{**forecast.__dict__, "weekly_outlook": (WeeklyOutlook(date(2026, 11, 23), 9.1, 1.4),)}
        )

        result = evaluate_day(make_profile(), forecast, date(2026, 11, 25))

        self.assertEqual(result.confidence, "outlook")
        self.assertIsNone(result.probability)
        assert result.weekly_outlook
        self.assertEqual(result.weekly_outlook.wind_speed_10m_mean_ms, 9.1)

    def test_equal_probability_ranks_larger_margin_first(self) -> None:
        start = datetime(2026, 11, 10, tzinfo=UTC)
        windier_day = datetime(2026, 11, 14, tzinfo=UTC)
        windier = [
            15.0 if windier_day <= start + timedelta(hours=h) < windier_day + timedelta(days=1) else 8.0
            for h in range(240)
        ]
        forecast = make_forecast(overrides={("wind_speed_100m_ms", m): windier for m in range(4)})
        profile = make_profile(days_needed=1, start_date=date(2026, 11, 13), end_date=date(2026, 11, 14))

        days, suggested = find_windows(profile, forecast)

        self.assertEqual([day.probability for day in days], [1.0, 1.0])
        self.assertGreater(days[0].margin, days[1].margin)
        self.assertEqual(suggested, [date(2026, 11, 13)])


class LightningTests(unittest.TestCase):
    def test_counts_strikes_by_radius(self) -> None:
        site = SITES["hr1"]
        now = datetime(2026, 11, 16, 12, tzinfo=UTC)

        def strike(lon: float, lat: float, minutes_ago: int) -> dict:
            observed = (now - timedelta(minutes=minutes_ago)).isoformat().replace("+00:00", "Z")
            return {"geometry": {"coordinates": [lon, lat]}, "properties": {"observed": observed}}

        summary = summarize(
            [
                strike(site.longitude + 0.2, site.latitude, 5),  # about 13 km
                strike(site.longitude + 1.0, site.latitude, 20),  # about 63 km
                strike(site.longitude + 2.0, site.latitude, 1),  # about 126 km
            ],
            site,
            now - timedelta(hours=1),
            now,
            truncated=False,
        )

        self.assertEqual(summary.strikes_within_48km, 1)
        self.assertEqual(summary.strikes_within_80km, 2)
        self.assertEqual(summary.last_within_48km, now - timedelta(minutes=5))
        self.assertAlmostEqual(summary.nearest_km or 0, 12.6, delta=0.5)


class StoreTests(unittest.TestCase):
    def test_keeps_latest_wave_run(self) -> None:
        store = Store(":memory:")
        self.addCleanup(store.close)
        older, newer = wave_ensemble(), wave_ensemble()
        newer = WaveEnsemble(**{**newer.__dict__, "run": newer.run + timedelta(hours=12)})

        store.save_waves("hr1", older.run, older.to_dict())
        store.save_waves("hr1", newer.run, newer.to_dict())

        latest = store.latest_waves("hr1")
        assert latest
        self.assertEqual(WaveEnsemble.from_dict(latest).run, newer.run)


class OfflineApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.client = TestClient(app)
        planner._store = Store(":memory:")
        self.addCleanup(planner._store.close)
        planner._forecasts["hr1"] = make_forecast(fetched_at=datetime.now(UTC) - timedelta(hours=1))

    def tearDown(self) -> None:
        planner._forecasts.clear()
        planner._profiles.clear()
        planner._offline.clear()

    def test_pack_download_then_offline_tools(self) -> None:
        profile = self.client.post(
            "/api/profiles", json={"site_id": "hr1", "vessel": "ctv", "task": "nacelle", "work_hours_per_day": 4}
        ).json()
        pack = self.client.get(f"/api/profiles/{profile['profile_id']}/briefing-pack").json()
        planner._forecasts.clear()
        planner._profiles.clear()

        loaded = self.client.post("/api/briefing-pack", json=pack)
        self.assertEqual(loaded.status_code, 200)
        self.assertTrue(loaded.json()["data"]["offline"])

        with patch.object(planner, "fetch_payloads", side_effect=AssertionError("no network offline")):
            windows = self.client.get(f"/api/profiles/{profile['profile_id']}/windows")
            conditions = self.client.get("/api/conditions-now", params={"site_id": "hr1"})
            status = self.client.get("/api/data-status", params={"site_id": "hr1"})

        self.assertEqual(windows.status_code, 200)
        self.assertFalse(conditions.json()["lightning"]["available"])
        self.assertIn("Offline", conditions.json()["lightning"]["note"])
        self.assertTrue(status.json()["offline"])

        self.assertEqual(self.client.delete("/api/briefing-pack/hr1").json()["offline"], False)

    def test_failed_refresh_falls_back_to_stored_forecast_with_note(self) -> None:
        planner._forecasts.clear()
        fetched = datetime.now(UTC) - timedelta(hours=5)
        payloads = provider_payloads()
        planner._store.save_payloads("hr1", fetched, payloads)  # type: ignore[union-attr]

        with patch.object(planner, "fetch_payloads", side_effect=ProviderError("Open-Meteo is unavailable.")):
            status = self.client.get("/api/data-status", params={"site_id": "hr1"})

        self.assertEqual(status.status_code, 200)
        self.assertEqual(status.json()["data"]["age_hours"], 5.0)
        self.assertIn("Live refresh failed", status.json()["notes"][0])

    def test_failed_refresh_without_stored_data_is_502(self) -> None:
        planner._forecasts.clear()

        with patch.object(planner, "fetch_payloads", side_effect=ProviderError("Open-Meteo is unavailable.")):
            status = self.client.get("/api/data-status", params={"site_id": "hr2"})

        self.assertEqual(status.status_code, 502)


if __name__ == "__main__":
    unittest.main()
