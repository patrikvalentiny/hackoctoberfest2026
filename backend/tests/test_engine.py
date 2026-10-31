import unittest
from datetime import UTC, date, datetime, timedelta

from support import (
    DAY,
    FETCHED,
    make_forecast,
    make_profile,
    provider_payloads,
    series_with,
)

from backend.engine.forecast import WeeklyOutlook
from backend.engine.profiles import SITES, build_limits, vessel_hs_limit
from backend.engine.windows import (
    LOCAL_TZ,
    check_task_fits,
    current_hour,
    daylight,
    evaluate_day,
    explain_day,
    find_windows,
)
from backend.ingest.open_meteo import build_site_forecast


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
        self.assertEqual(result.window.start.minute % 15, 0)

    def test_probability_is_share_of_members_with_window(self) -> None:
        windy = [25.0] * len(make_forecast().times)
        forecast = make_forecast(overrides={("wind_speed_100m_ms", 0): windy})

        result = evaluate_day(make_profile(), forecast, DAY)

        self.assertEqual(result.probability, 0.75)
        self.assertEqual(result.limiting_parameter, "wind_100m")
        self.assertEqual(result.limit_failures["wind_100m"], 1)

    def test_wave_limit_depends_on_vessel(self) -> None:
        forecast = make_forecast(wave=2.0)

        ctv = evaluate_day(make_profile("ctv"), forecast, DAY)
        self.assertEqual(ctv.probability, 0.0)
        self.assertEqual(ctv.limiting_parameter, "wave_height")
        self.assertEqual(evaluate_day(make_profile("sov"), forecast, DAY).probability, 1.0)

    def test_limit_values_are_inclusive(self) -> None:
        # Exactly at the limit is within it (Hs 1.5 m for a CTV, 20 m/s for nacelle work).
        forecast = make_forecast(wave=1.5, wind_100m=20.0)

        self.assertEqual(evaluate_day(make_profile(), forecast, DAY).probability, 1.0)

    def test_task_wind_limit_applies_only_during_work(self) -> None:
        forecast = make_forecast()
        rise, _ = daylight(SITES["hr1"], DAY)
        first_hour = rise.replace(minute=0, second=0, microsecond=0)
        # Strong wind only in the first hour after sunrise: a CTV still sails,
        # and lifting can start once it arrives.
        gust = series_with(forecast, 12.0, first_hour, first_hour + timedelta(hours=1), 8.0)
        forecast = make_forecast(overrides={("wind_speed_100m_ms", m): gust for m in range(4)})

        self.assertEqual(evaluate_day(make_profile(task="lifting"), forecast, DAY).probability, 1.0)

    def test_sov_has_no_transit(self) -> None:
        result = evaluate_day(make_profile("sov", hours=4), make_forecast(), DAY)

        assert result.window
        self.assertEqual(result.window.end - result.window.start, timedelta(hours=4))

    def test_missing_values_count_as_failures(self) -> None:
        result = evaluate_day(make_profile(), make_forecast(visibility=None), DAY)

        self.assertEqual(result.probability, 0.0)
        self.assertEqual(result.limiting_parameter, "visibility")

    def test_job_longer_than_daylight_reports_daylight(self) -> None:
        result = evaluate_day(make_profile(hours=7), make_forecast(), DAY)  # 1 + 7 + 1 h in November

        self.assertEqual(result.probability, 0.0)
        self.assertEqual(result.limiting_parameter, "daylight")
        self.assertIn("daylight left", result.note or "")

    def test_day_already_over_says_so(self) -> None:
        fetched = datetime(2026, 11, 16, 18, tzinfo=UTC)

        result = evaluate_day(make_profile(), make_forecast(fetched_at=fetched), DAY)

        self.assertEqual(result.probability, 0.0)
        self.assertEqual(result.limiting_parameter, "daylight")
        self.assertIn("already ended", result.note or "")

    def test_confidence_tiers_by_lead_time(self) -> None:
        forecast = make_forecast(days=10)
        profile = make_profile()

        self.assertEqual(evaluate_day(profile, forecast, date(2026, 11, 11)).confidence, "high")
        self.assertEqual(evaluate_day(profile, forecast, date(2026, 11, 14)).confidence, "medium")
        self.assertEqual(evaluate_day(profile, forecast, date(2026, 11, 18)).confidence, "low")
        outlook = evaluate_day(profile, forecast, date(2026, 11, 25))
        self.assertEqual(outlook.confidence, "outlook")
        self.assertIsNone(outlook.probability)
        self.assertIsNone(outlook.weekly_outlook)
        self.assertIn("no outlook data", outlook.note or "")

    def test_outlook_day_carries_weekly_signal(self) -> None:
        forecast = make_forecast(days=10)
        forecast = forecast.__class__(
            **{**forecast.__dict__, "weekly_outlook": (WeeklyOutlook(date(2026, 11, 23), 9.1, 1.4),)}
        )

        result = evaluate_day(make_profile(), forecast, date(2026, 11, 25))

        assert result.weekly_outlook
        self.assertEqual(result.weekly_outlook.wind_speed_10m_mean_ms, 9.1)
        self.assertIsNone(result.window)

    def test_recompute_date_is_sunset_minus_60_hours(self) -> None:
        result = evaluate_day(make_profile(), make_forecast(), DAY)

        self.assertEqual(result.recompute_at, result.sunset - timedelta(hours=60))
        # Already inside the horizon: nothing to recompute.
        self.assertIsNone(evaluate_day(make_profile(), make_forecast(), date(2026, 11, 11)).recompute_at)

    def test_windows_never_start_before_data_time(self) -> None:
        fetched = datetime(2026, 11, 16, 8, 10, tzinfo=UTC)

        result = evaluate_day(make_profile(), make_forecast(fetched_at=fetched), DAY)

        assert result.window
        self.assertGreaterEqual(result.window.start, fetched)

    def test_failures_before_data_time_do_not_set_limiting_parameter(self) -> None:
        forecast = make_forecast()
        fetched = datetime(2026, 11, 16, 9, tzinfo=UTC)
        rise, _ = daylight(SITES["hr1"], DAY)
        # Rough waves only before the data time, then too much wind afterwards.
        rough = series_with(forecast, 3.0, rise - timedelta(hours=1), fetched, 1.0)
        windy = series_with(forecast, 25.0, fetched, fetched + timedelta(hours=12), 8.0)
        forecast = make_forecast(
            overrides={
                **{("wave_height_m", m): rough for m in range(4)},
                **{("wind_speed_100m_ms", m): windy for m in range(4)},
            },
            fetched_at=fetched,
        )

        result = evaluate_day(make_profile(hours=2), forecast, DAY)

        self.assertEqual(result.limiting_parameter, "wind_100m")
        self.assertEqual(result.limit_failures["wave_height"], 0)

    def test_deterministic_window_on_high_confidence_day(self) -> None:
        hours = 10 * 24
        calm = make_forecast(deterministic={})
        rough = make_forecast(deterministic={"wave_height_m": [3.0] * hours})
        day = date(2026, 11, 11)

        calm_result = evaluate_day(make_profile(), calm, day)
        rough_result = evaluate_day(make_profile(), rough, day)

        self.assertTrue(calm_result.deterministic_evaluated)
        self.assertIsNotNone(calm_result.deterministic_window)
        self.assertTrue(rough_result.deterministic_evaluated)
        self.assertIsNone(rough_result.deterministic_window)
        # Not evaluated beyond the high-confidence tier.
        self.assertFalse(evaluate_day(make_profile(), calm, DAY).deterministic_evaluated)

    def test_margin_is_relative_distance_to_closest_limit(self) -> None:
        # Hs 1.2 of 1.5 m = 0.2; wind 8 of 20 m/s = 0.6; visibility far above 1 km.
        result = evaluate_day(make_profile(), make_forecast(wave=1.2), DAY)

        self.assertEqual(result.margin, 0.2)

    def test_daylight_handles_dst_change(self) -> None:
        before = daylight(SITES["hr1"], date(2026, 10, 24))
        after = daylight(SITES["hr1"], date(2026, 10, 25))

        self.assertEqual(before[0].astimezone(LOCAL_TZ).utcoffset(), timedelta(hours=2))
        self.assertEqual(after[0].astimezone(LOCAL_TZ).utcoffset(), timedelta(hours=1))
        # Sunrise moves by minutes in UTC, not by the one-hour clock change.
        self.assertLess(abs((after[0] - before[0]) - timedelta(days=1)), timedelta(minutes=5))

    def test_winter_daylight_matches_plan(self) -> None:
        # docs/PLAN.md: about 7.1 h on 21 Dec in Esbjerg.
        rise, set_ = daylight(SITES["hr1"], date(2026, 12, 21))

        self.assertAlmostEqual((set_ - rise).total_seconds() / 3600, 7.1, delta=0.2)


class FindWindowsTests(unittest.TestCase):
    def test_evaluates_every_day_in_range(self) -> None:
        profile = make_profile(start_date=date(2026, 11, 11), end_date=date(2026, 11, 21))

        days, _ = find_windows(profile, make_forecast())

        self.assertEqual(days[0].date, date(2026, 11, 11))
        self.assertEqual(days[-1].date, date(2026, 11, 21))
        self.assertEqual(len(days), 11)

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
        self.assertEqual(suggested, [date(2026, 11, 14), date(2026, 11, 15), date(2026, 11, 16)])

    def test_consecutive_without_a_full_block_suggests_nothing(self) -> None:
        forecast = make_forecast()
        first_rough = datetime(2026, 11, 12, tzinfo=LOCAL_TZ).astimezone(UTC)
        # Every other local day from 12 Nov has rough seas all day.
        rough = [
            3.0 if time >= first_rough and (time - first_rough).days % 2 == 0 else 1.0 for time in forecast.times
        ]
        forecast = make_forecast(overrides={("wave_height_m", m): rough for m in range(4)})
        profile = make_profile(
            days_needed=2, start_date=date(2026, 11, 12), end_date=date(2026, 11, 17), consecutive=True
        )

        days, suggested = find_windows(profile, forecast)

        self.assertEqual([day.probability for day in days], [0.0, 1.0, 0.0, 1.0, 0.0, 1.0])
        self.assertEqual(suggested, [])

    def test_equal_probability_ranks_larger_margin_first(self) -> None:
        windier_day = datetime(2026, 11, 14, tzinfo=UTC)
        start = datetime(2026, 11, 10, tzinfo=UTC)
        windier = [
            15.0 if windier_day <= start + timedelta(hours=h) < windier_day + timedelta(days=1) else 8.0
            for h in range(240)
        ]
        forecast = make_forecast(overrides={("wind_speed_100m_ms", m): windier for m in range(4)})
        profile = make_profile(start_date=date(2026, 11, 13), end_date=date(2026, 11, 14))

        days, suggested = find_windows(profile, forecast)

        self.assertEqual([day.probability for day in days], [1.0, 1.0])
        assert days[0].margin is not None and days[1].margin is not None
        self.assertGreater(days[0].margin, days[1].margin)
        self.assertEqual(suggested, [date(2026, 11, 13)])

    def test_outlook_and_zero_probability_days_are_never_suggested(self) -> None:
        profile = make_profile(days_needed=21, start_date=date(2026, 11, 10), end_date=date(2026, 11, 30))

        days, suggested = find_windows(profile, make_forecast(days=10))

        outlook = {day.date for day in days if day.confidence == "outlook"}
        self.assertTrue(outlook)
        self.assertFalse(outlook & set(suggested))
        self.assertTrue(all(day.probability for day in days if day.date in suggested))


class ExplainDayTests(unittest.TestCase):
    def test_hours_cover_local_day_with_spread_and_failures(self) -> None:
        times = len(make_forecast().times)
        overrides = {("wind_speed_100m_ms", m): [10.0 + m] * times for m in range(4)}
        forecast = make_forecast(overrides=overrides)

        result, hours = explain_day(make_profile(task="lifting"), forecast, DAY)

        self.assertEqual(len(hours), 24)
        self.assertEqual(hours[0]["time"], datetime(2026, 11, 16, tzinfo=LOCAL_TZ).astimezone(UTC))
        wind = hours[12]["variables"]["wind_speed_100m_ms"]
        self.assertEqual((wind["min"], wind["median"], wind["max"]), (10.0, 11.5, 13.0))
        # Lifting limit is 10 m/s inclusive: three of four members exceed it.
        self.assertEqual(hours[12]["members_failing"]["wind_100m"], 3)
        self.assertFalse(hours[2]["daylight"])
        self.assertTrue(hours[12]["daylight"])
        self.assertEqual(result.date, DAY)

    def test_real_shaped_forecast_reports_shared_and_missing_values(self) -> None:
        payloads = provider_payloads(hours=10 * 24)
        payloads["swell"] = None
        forecast = build_site_forecast(SITES["hr1"], payloads, FETCHED)

        _, hours = explain_day(make_profile(), forecast, date(2026, 11, 12))

        hour = hours[12]
        self.assertEqual(hour["variables"]["wave_height_m"], {"value": 1.0})
        self.assertIsNone(hour["variables"]["swell_wave_height_m"])
        self.assertEqual(hour["variables"]["wind_speed_100m_ms"]["max"], 9.0)
        self.assertEqual(hour["deterministic"]["wind_speed_100m_ms"], 6.0)

    def test_dst_day_has_25_hours(self) -> None:
        start = datetime(2026, 10, 23, tzinfo=UTC)
        forecast = make_forecast(start=start, fetched_at=start)

        _, hours = explain_day(make_profile(), forecast, date(2026, 10, 25))

        self.assertEqual(len(hours), 25)


class TaskFitTests(unittest.TestCase):
    @staticmethod
    def rough_after(local_hour: int, now: datetime):
        forecast = make_forecast(fetched_at=now)
        rise_at = datetime(2026, 11, 16, local_hour, tzinfo=LOCAL_TZ).astimezone(UTC)
        rough = series_with(forecast, 2.0, rise_at, rise_at + timedelta(hours=6), 1.0)
        return make_forecast(overrides={("wave_height_m", m): rough for m in range(4)}, fetched_at=now)

    def test_last_transfer_respects_wave_rise_and_transit(self) -> None:
        now = datetime(2026, 11, 16, 9, tzinfo=LOCAL_TZ).astimezone(UTC)
        forecast = self.rough_after(13, now)
        start = datetime(2026, 11, 16, 10, tzinfo=LOCAL_TZ)

        fit = check_task_fits(make_profile(), forecast, start, timedelta(minutes=90), now)

        assert fit.last_transfer_back and fit.latest_start
        # Waves exceed 1.5 m from 13:00, and the CTV needs 1 h back.
        self.assertEqual(fit.last_transfer_back.astimezone(LOCAL_TZ).strftime("%H:%M"), "12:00")
        self.assertEqual(fit.latest_start, fit.last_transfer_back - timedelta(minutes=90))
        self.assertTrue(fit.fits)
        self.assertEqual(fit.ensemble_fraction, 1.0)
        self.assertEqual(fit.reference, "ensemble median")
        self.assertEqual(fit.blocking_limits, ())

        late = check_task_fits(make_profile(), forecast, start + timedelta(hours=1), timedelta(minutes=90), now)
        self.assertFalse(late.fits)
        self.assertIn("wave_height", late.blocking_limits)
        self.assertEqual(late.ensemble_fraction, 0.0)

    def test_task_wind_limit_blocks_and_sets_latest_start(self) -> None:
        now = datetime(2026, 11, 16, 9, tzinfo=LOCAL_TZ).astimezone(UTC)
        forecast = make_forecast(fetched_at=now)
        gust_at = datetime(2026, 11, 16, 11, tzinfo=LOCAL_TZ).astimezone(UTC)
        windy = series_with(forecast, 12.0, gust_at, gust_at + timedelta(hours=1), 8.0)
        forecast = make_forecast(overrides={("wind_speed_100m_ms", m): windy for m in range(4)}, fetched_at=now)
        start = datetime(2026, 11, 16, 10, 30, tzinfo=LOCAL_TZ)

        fit = check_task_fits(make_profile(task="lifting"), forecast, start, timedelta(minutes=60), now)

        self.assertFalse(fit.fits)
        self.assertEqual(fit.blocking_limits, ("wind_100m",))
        assert fit.latest_start and fit.last_transfer_back
        # The latest start is after the gusty hour and still ends by the last transfer.
        self.assertGreaterEqual(fit.latest_start, gust_at + timedelta(hours=1))
        self.assertLessEqual(fit.latest_start + timedelta(minutes=60), fit.last_transfer_back)

    def test_after_sunset_reports_daylight_only(self) -> None:
        now = datetime(2026, 11, 16, 9, tzinfo=LOCAL_TZ).astimezone(UTC)
        start = datetime(2026, 11, 16, 17, tzinfo=LOCAL_TZ)

        fit = check_task_fits(make_profile(), make_forecast(fetched_at=now), start, timedelta(minutes=30), now)

        self.assertFalse(fit.fits)
        self.assertEqual(fit.blocking_limits, ("daylight",))
        self.assertIsNone(fit.last_transfer_back)

    def test_task_ending_after_last_transfer_reports_daylight(self) -> None:
        now = datetime(2026, 11, 16, 9, tzinfo=LOCAL_TZ).astimezone(UTC)
        start = datetime(2026, 11, 16, 14, tzinfo=LOCAL_TZ)

        fit = check_task_fits(make_profile(), make_forecast(fetched_at=now), start, timedelta(hours=2), now)

        self.assertFalse(fit.fits)
        self.assertEqual(fit.blocking_limits, ("daylight",))
        self.assertEqual(fit.ensemble_fraction, 0.0)
        assert fit.last_transfer_back
        _, set_ = daylight(SITES["hr1"], DAY)
        self.assertLessEqual(fit.last_transfer_back + timedelta(hours=1), set_)

    def test_no_forecast_data_gives_no_answer(self) -> None:
        now = FETCHED + timedelta(hours=1)
        start = datetime(2026, 11, 25, 10, tzinfo=LOCAL_TZ)  # beyond the 10-day forecast

        fit = check_task_fits(make_profile(), make_forecast(fetched_at=now), start, timedelta(minutes=90), now)

        self.assertIsNone(fit.fits)
        self.assertIn("no data", fit.note or "")

    def test_prefers_dmi_when_it_covers_the_period(self) -> None:
        now = datetime(2026, 11, 16, 9, tzinfo=LOCAL_TZ).astimezone(UTC)
        forecast = make_forecast(fetched_at=now, deterministic={})
        start = datetime(2026, 11, 16, 10, tzinfo=LOCAL_TZ)

        fit = check_task_fits(make_profile(), forecast, start, timedelta(minutes=90), now)

        self.assertEqual(fit.reference, "DMI HARMONIE deterministic")

    def test_rough_seas_at_start_block_the_trip_back(self) -> None:
        now = datetime(2026, 11, 16, 9, tzinfo=LOCAL_TZ).astimezone(UTC)
        start = datetime(2026, 11, 16, 10, tzinfo=LOCAL_TZ)

        fit = check_task_fits(make_profile(), make_forecast(wave=2.0, fetched_at=now), start, timedelta(minutes=30), now)

        self.assertFalse(fit.fits)
        self.assertEqual(fit.blocking_limits, ("wave_height",))
        self.assertIsNone(fit.last_transfer_back)

    def test_start_before_sunrise_is_noted(self) -> None:
        now = datetime(2026, 11, 16, 5, tzinfo=LOCAL_TZ).astimezone(UTC)
        start = datetime(2026, 11, 16, 6, tzinfo=LOCAL_TZ)

        fit = check_task_fits(make_profile(), make_forecast(fetched_at=now), start, timedelta(minutes=30), now)

        self.assertIn("before sunrise", fit.note or "")

    def test_stale_data_withholds_timing(self) -> None:
        start = datetime(2026, 11, 16, 10, tzinfo=LOCAL_TZ)
        now = FETCHED + timedelta(hours=13)

        fit = check_task_fits(make_profile(), make_forecast(), start, timedelta(minutes=90), now)

        self.assertIsNone(fit.fits)
        self.assertIsNone(fit.latest_start)
        self.assertIsNone(fit.last_transfer_back)
        self.assertEqual(fit.data_age_hours, 13.0)
        self.assertIn("older than 12 hours", fit.note or "")


class CurrentHourTests(unittest.TestCase):
    def test_uses_dmi_when_available_and_compares_limits(self) -> None:
        forecast = make_forecast(deterministic={"wave_height_m": [1.8] * 240})
        now = datetime(2026, 11, 12, 10, 40, tzinfo=UTC)

        hour = current_hour(build_limits("ctv", "nacelle"), forecast, now)

        assert hour
        self.assertEqual(hour["time"], datetime(2026, 11, 12, 10, tzinfo=UTC))
        self.assertEqual(hour["reference"], "DMI HARMONIE deterministic")
        waves = next(limit for limit in hour["limits"] if limit["id"] == "wave_height")
        self.assertEqual((waves["value"], waves["within_limit"]), (1.8, False))

    def test_falls_back_to_median_and_handles_no_data(self) -> None:
        forecast = make_forecast()
        limits = build_limits("sov", "lifting")

        hour = current_hour(limits, forecast, datetime(2026, 11, 12, 10, tzinfo=UTC))

        assert hour
        self.assertEqual(hour["reference"], "ensemble median")
        self.assertTrue(all(limit["within_limit"] for limit in hour["limits"]))
        self.assertIsNone(current_hour(limits, forecast, datetime(2027, 1, 1, tzinfo=UTC)))


class CheckerTests(unittest.TestCase):
    def test_forecast_missing_a_limit_variable_is_an_error(self) -> None:
        forecast = make_forecast()
        del forecast.ensemble.variables["visibility_m"]

        with self.assertRaisesRegex(ValueError, "visibility_m"):
            evaluate_day(make_profile(), forecast, DAY)


class LimitTests(unittest.TestCase):
    def test_sov_limit_is_bounded_and_ctv_is_fixed(self) -> None:
        self.assertEqual(build_limits("sov", "nacelle", 3.0)[0].value, 3.0)
        self.assertEqual(vessel_hs_limit("sov", None), 2.5)
        self.assertEqual(vessel_hs_limit("ctv", None), 1.5)
        for vessel, value in (("sov", 4.0), ("sov", 2.0), ("ctv", 2.5)):
            with self.assertRaises(ValueError):
                build_limits(vessel, "nacelle", value)  # type: ignore[arg-type]

    def test_task_limits_use_100m_wind_during_work(self) -> None:
        for task, value in (("nacelle", 20.0), ("hub_locked_rotor", 15.0), ("lifting", 10.0)):
            wind = next(limit for limit in build_limits("ctv", task) if limit.id == "wind_100m")  # type: ignore[arg-type]
            self.assertEqual((wind.variable, wind.value, wind.segment), ("wind_speed_100m_ms", value, "work"))


if __name__ == "__main__":
    unittest.main()
