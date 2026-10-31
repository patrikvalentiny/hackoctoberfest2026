import unittest
from datetime import UTC, date, datetime, timedelta

from fastapi.testclient import TestClient

from backend.api import planner
from backend.engine.forecast import MemberSet, SiteForecast
from backend.engine.profiles import SITES, JobProfile, build_limits
from backend.engine.windows import LOCAL_TZ, check_task_fits, daylight, evaluate_day, find_windows
from backend.ingest.open_meteo import build_site_forecast
from backend.main import app

DAY = date(2026, 11, 16)
FETCHED = datetime(2026, 11, 10, 0, tzinfo=UTC)


def make_forecast(
    members: int = 4,
    days: int = 10,
    wind_100m: float = 8.0,
    wave: float = 1.0,
    visibility: float | None = 20000.0,
    overrides: dict[tuple[str, int], list[float | None]] | None = None,
    fetched_at: datetime = FETCHED,
) -> SiteForecast:
    """Calm conditions everywhere unless overridden per (variable, member)."""
    start = datetime(2026, 11, 10, tzinfo=UTC)
    times = [start + timedelta(hours=h) for h in range(days * 24)]
    base = {
        "wind_speed_10m_ms": wind_100m * 0.8,
        "wind_speed_100m_ms": wind_100m,
        "wave_height_m": wave,
        "visibility_m": visibility,
    }
    variables = {
        name: [[value] * len(times) for _ in range(members)] for name, value in base.items()
    }
    for (name, member), series in (overrides or {}).items():
        variables[name][member] = series
    return SiteForecast(
        site_id="hr1",
        fetched_at=fetched_at,
        times=times,
        ensemble=MemberSet(name="test", variables=variables),
        deterministic=None,
        sources=(),
    )


def make_profile(vessel: str = "ctv", task: str = "nacelle", hours: float = 4, **kwargs) -> JobProfile:
    return JobProfile(
        id="test",
        site=SITES["hr1"],
        vessel=vessel,  # type: ignore[arg-type]
        task=task,  # type: ignore[arg-type]
        work_hours_per_day=hours,
        days_needed=kwargs.pop("days_needed", 1),
        start_date=kwargs.pop("start_date", DAY),
        end_date=kwargs.pop("end_date", DAY),
        consecutive=kwargs.pop("consecutive", False),
        limits=build_limits(vessel, task),  # type: ignore[arg-type]
    )


def series_with(forecast: SiteForecast, value: float | None, start: datetime, end: datetime, base: float | None):
    return [value if start <= time < end else base for time in forecast.times]


class EvaluateDayTests(unittest.TestCase):
    def test_calm_day_has_window_for_all_members(self) -> None:
        result = evaluate_day(make_profile(), make_forecast(), DAY)

        self.assertEqual(result.probability, 1.0)
        self.assertEqual(result.members_with_window, 4)
        self.assertIsNone(result.limiting_parameter)
        assert result.window
        rise, set_ = daylight(SITES["hr1"], DAY)
        self.assertGreaterEqual(result.window.start, rise)
        self.assertLessEqual(result.window.end, set_)
        # 1 h out + 4 h work + 1 h back.
        self.assertEqual(result.window.end - result.window.start, timedelta(hours=6))

    def test_probability_is_share_of_members_with_window(self) -> None:
        forecast = make_forecast()
        windy = [25.0] * len(forecast.times)
        forecast = make_forecast(overrides={("wind_speed_100m_ms", 0): windy})

        result = evaluate_day(make_profile(), forecast, DAY)

        self.assertEqual(result.probability, 0.75)
        self.assertEqual(result.limiting_parameter, "wind_100m")
        self.assertEqual(result.limit_failures["wind_100m"], 1)

    def test_wave_limit_depends_on_vessel(self) -> None:
        forecast = make_forecast(wave=2.0)

        self.assertEqual(evaluate_day(make_profile("ctv"), forecast, DAY).probability, 0.0)
        self.assertEqual(evaluate_day(make_profile("ctv"), forecast, DAY).limiting_parameter, "wave_height")
        self.assertEqual(evaluate_day(make_profile("sov"), forecast, DAY).probability, 1.0)

    def test_task_wind_limit_applies_only_during_work(self) -> None:
        forecast = make_forecast()
        rise, _ = daylight(SITES["hr1"], DAY)
        first_hour = rise.replace(minute=0, second=0, microsecond=0)
        # Strong wind only during the first hour after sunrise: a CTV still
        # sails then, but lifting may not start until the wind drops.
        gust = series_with(forecast, 12.0, first_hour, first_hour + timedelta(hours=1), 8.0)
        forecast = make_forecast(overrides={("wind_speed_100m_ms", m): gust for m in range(4)})

        result = evaluate_day(make_profile(task="lifting"), forecast, DAY)

        self.assertEqual(result.probability, 1.0)

    def test_missing_values_count_as_failures(self) -> None:
        result = evaluate_day(make_profile(), make_forecast(visibility=None), DAY)

        self.assertEqual(result.probability, 0.0)
        self.assertEqual(result.limiting_parameter, "visibility")

    def test_job_longer_than_daylight_reports_daylight(self) -> None:
        profile = make_profile(hours=7)  # 1 + 7 + 1 h in mid-November daylight

        result = evaluate_day(profile, make_forecast(), DAY)

        self.assertEqual(result.probability, 0.0)
        self.assertEqual(result.limiting_parameter, "daylight")
        self.assertIsNotNone(result.note)

    def test_confidence_tiers_by_lead_time(self) -> None:
        forecast = make_forecast(days=10)
        profile = make_profile()

        self.assertEqual(evaluate_day(profile, forecast, date(2026, 11, 11)).confidence, "high")
        self.assertEqual(evaluate_day(profile, forecast, date(2026, 11, 14)).confidence, "medium")
        self.assertEqual(evaluate_day(profile, forecast, date(2026, 11, 18)).confidence, "low")
        outlook = evaluate_day(profile, forecast, date(2026, 11, 25))
        self.assertEqual(outlook.confidence, "outlook")
        self.assertIsNone(outlook.probability)

    def test_recompute_date_is_sunset_minus_60_hours(self) -> None:
        result = evaluate_day(make_profile(), make_forecast(), DAY)

        self.assertEqual(result.recompute_at, result.sunset - timedelta(hours=60))

    def test_windows_never_start_before_data_time(self) -> None:
        fetched = datetime(2026, 11, 16, 8, 10, tzinfo=UTC)
        result = evaluate_day(make_profile(), make_forecast(fetched_at=fetched), DAY)

        assert result.window
        self.assertGreaterEqual(result.window.start, fetched)

    def test_daylight_handles_dst_change(self) -> None:
        before = daylight(SITES["hr1"], date(2026, 10, 24))
        after = daylight(SITES["hr1"], date(2026, 10, 25))

        self.assertEqual(before[0].astimezone(LOCAL_TZ).utcoffset(), timedelta(hours=2))
        self.assertEqual(after[0].astimezone(LOCAL_TZ).utcoffset(), timedelta(hours=1))
        # Sunrise moves by minutes in UTC, not by the one-hour clock change.
        self.assertLess(abs((after[0] - before[0]) - timedelta(days=1)), timedelta(minutes=5))


class FindWindowsTests(unittest.TestCase):
    def test_consecutive_days_prefer_best_block(self) -> None:
        forecast = make_forecast()
        bad_day_start = datetime(2026, 11, 13, tzinfo=LOCAL_TZ).astimezone(UTC)
        rough = series_with(forecast, 3.0, bad_day_start, bad_day_start + timedelta(days=1), 1.0)
        forecast = make_forecast(overrides={("wave_height_m", m): rough for m in range(4)})
        profile = make_profile(
            days_needed=3, start_date=date(2026, 11, 11), end_date=date(2026, 11, 18), consecutive=True
        )

        days, suggested = find_windows(profile, forecast)

        self.assertEqual(len(days), 8)
        self.assertNotIn(date(2026, 11, 13), suggested)
        self.assertEqual(suggested, [date(2026, 11, 14), date(2026, 11, 15), date(2026, 11, 16)])


class TaskFitTests(unittest.TestCase):
    def test_last_transfer_respects_wave_rise_and_transit(self) -> None:
        now = datetime(2026, 11, 16, 9, tzinfo=LOCAL_TZ).astimezone(UTC)
        forecast = make_forecast(fetched_at=now)
        rise_at = datetime(2026, 11, 16, 13, tzinfo=LOCAL_TZ).astimezone(UTC)
        rough = series_with(forecast, 2.0, rise_at, rise_at + timedelta(hours=6), 1.0)
        forecast = make_forecast(overrides={("wave_height_m", m): rough for m in range(4)}, fetched_at=now)
        start = datetime(2026, 11, 16, 10, tzinfo=LOCAL_TZ)

        fit = check_task_fits(make_profile(), forecast, start, timedelta(minutes=90), now)

        assert fit.last_transfer_back and fit.latest_start
        # Waves exceed 1.5 m from 13:00, and the CTV needs 1 h back.
        self.assertEqual(fit.last_transfer_back.astimezone(LOCAL_TZ).hour, 12)
        self.assertEqual(fit.last_transfer_back.astimezone(LOCAL_TZ).minute, 0)
        self.assertEqual(fit.latest_start, fit.last_transfer_back - timedelta(minutes=90))
        self.assertTrue(fit.fits)

        late = check_task_fits(make_profile(), forecast, start + timedelta(hours=1), timedelta(minutes=90), now)
        self.assertFalse(late.fits)
        self.assertIn("wave_height", late.blocking_limits)

    def test_stale_data_withholds_timing(self) -> None:
        start = datetime(2026, 11, 16, 10, tzinfo=LOCAL_TZ)

        fit = check_task_fits(
            make_profile(), make_forecast(), start, timedelta(minutes=90), FETCHED + timedelta(hours=13)
        )

        self.assertIsNone(fit.fits)
        self.assertIsNone(fit.latest_start)
        self.assertIsNotNone(fit.note)


class LimitTests(unittest.TestCase):
    def test_sov_limit_is_bounded_and_ctv_is_fixed(self) -> None:
        self.assertEqual(build_limits("sov", "nacelle", 3.0)[0].value, 3.0)
        with self.assertRaises(ValueError):
            build_limits("sov", "nacelle", 4.0)
        with self.assertRaises(ValueError):
            build_limits("ctv", "nacelle", 2.5)


class IngestTests(unittest.TestCase):
    def test_builds_members_and_aligns_deterministic_sources(self) -> None:
        times = ["2026-11-10T00:00", "2026-11-10T01:00"]
        ensemble = {
            "hourly": {
                "time": times,
                "wind_speed_10m": [5.0, 6.0],
                "wind_speed_10m_member01": [5.5, None],
                "wind_speed_100m": [7.0, 8.0],
                "wind_speed_100m_member01": [7.5, 8.5],
            }
        }
        marine = {
            "hourly": {
                "time": times[1:],
                "wave_height": [1.1],
                "wave_period": [6.0],
                "wave_direction": [220.0],
            }
        }
        visibility = {"hourly": {"time": times, "visibility": [20000.0, 15000.0]}}
        dmi = {
            "hourly": {
                "time": times,
                "wind_speed_10m": [4.0, 4.5],
                "wind_speed_100m": [6.0, 6.5],
                "visibility": [21000.0, 16000.0],
            }
        }

        forecast = build_site_forecast(SITES["hr1"], ensemble, marine, visibility, dmi, FETCHED)

        self.assertEqual(forecast.ensemble.members, 2)
        self.assertEqual(forecast.ensemble.variables["wind_speed_10m_ms"][1], [5.5, None])
        self.assertEqual(forecast.ensemble.variables["wave_height_m"][0], [None, 1.1])
        self.assertEqual(forecast.times[0], datetime(2026, 11, 10, tzinfo=UTC))
        self.assertIn("wave_height_m", forecast.ensemble.deterministic_variables)


class PlannerApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.client = TestClient(app)
        planner._forecasts["hr1"] = make_forecast(fetched_at=datetime.now(UTC))

    def tearDown(self) -> None:
        planner._forecasts.clear()
        planner._profiles.clear()

    def test_profile_then_windows(self) -> None:
        response = self.client.post(
            "/api/profiles",
            json={"site_id": "hr1", "vessel": "sov", "task": "lifting", "work_hours_per_day": 4},
        )
        self.assertEqual(response.status_code, 200)
        profile = response.json()
        self.assertEqual([limit["id"] for limit in profile["limits"]], ["wave_height", "wind_100m", "visibility"])

        windows = self.client.get(f"/api/profiles/{profile['profile_id']}/windows")

        self.assertEqual(windows.status_code, 200)
        payload = windows.json()
        self.assertEqual(len(payload["days"]), 21)
        self.assertEqual(payload["data"]["freshness"], "fresh")

    def test_rejects_ranges_over_21_days(self) -> None:
        response = self.client.post(
            "/api/profiles",
            json={
                "site_id": "hr1",
                "vessel": "ctv",
                "task": "nacelle",
                "work_hours_per_day": 4,
                "start_date": "2026-11-01",
                "end_date": "2026-11-30",
            },
        )

        self.assertEqual(response.status_code, 422)


if __name__ == "__main__":
    unittest.main()
