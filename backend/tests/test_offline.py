import json
import unittest
from datetime import UTC, datetime

from support import DAY, make_forecast, make_profile, provider_payloads, wave_ensemble

from backend.engine.briefing import MAX_BYTES, BriefingPackError, build_pack, load_pack
from backend.engine.forecast import forecast_from_dict, forecast_to_dict
from backend.engine.profiles import SITES, profile_from_dict, profile_to_dict
from backend.engine.windows import evaluate_day, find_windows
from backend.ingest.open_meteo import build_site_forecast

RUN = datetime(2026, 11, 10, tzinfo=UTC)


def through_json(value: dict) -> dict:
    return json.loads(json.dumps(value, default=str))


class SerializationTests(unittest.TestCase):
    def test_forecast_round_trip(self) -> None:
        forecast = build_site_forecast(SITES["hr1"], provider_payloads(), RUN, wave_ensemble())

        restored = forecast_from_dict(through_json(forecast_to_dict(forecast)))

        self.assertEqual(restored.times, forecast.times)
        self.assertEqual(restored.fetched_at, forecast.fetched_at)
        self.assertEqual(restored.ensemble.variables, forecast.ensemble.variables)
        self.assertEqual(restored.ensemble.deterministic_variables, forecast.ensemble.deterministic_variables)
        assert restored.deterministic and forecast.deterministic
        self.assertEqual(restored.deterministic.variables, forecast.deterministic.variables)
        self.assertEqual(restored.sources, forecast.sources)
        self.assertEqual(restored.notes, forecast.notes)
        self.assertEqual(restored.weekly_outlook, forecast.weekly_outlook)

    def test_shared_series_are_stored_once(self) -> None:
        forecast = build_site_forecast(SITES["hr1"], provider_payloads(), RUN)

        variables = forecast_to_dict(forecast)["ensemble"]["variables"]

        self.assertIn("shared", variables["wave_height_m"])
        self.assertIn("members", variables["wind_speed_100m_ms"])

    def test_values_are_rounded_to_two_decimals(self) -> None:
        forecast = make_forecast(wave=1.23456)

        restored = forecast_from_dict(through_json(forecast_to_dict(forecast)))

        self.assertEqual(restored.ensemble.variables["wave_height_m"][0][0], 1.23)

    def test_profile_round_trip_keeps_limits(self) -> None:
        profile = make_profile("sov", "lifting")

        self.assertEqual(profile_from_dict(through_json(profile_to_dict(profile))), profile)


class BriefingPackTests(unittest.TestCase):
    def test_full_size_pack_fits_under_limit_and_gives_same_results(self) -> None:
        # 50 paired members over 15 days with per-member waves is the real shape.
        forecast = make_forecast(members=50, days=15)
        profile = make_profile()

        pack = build_pack(profile, forecast, {"days": []}, datetime.now(UTC))
        size = len(json.dumps(pack, separators=(",", ":"), default=str).encode())
        loaded_profile, loaded_forecast = load_pack(through_json(pack))

        self.assertLess(size, MAX_BYTES)
        self.assertEqual(loaded_profile, profile)
        self.assertEqual(find_windows(loaded_profile, loaded_forecast), find_windows(profile, forecast))
        self.assertEqual(pack["format"], "harbour-pulse-briefing-pack")
        self.assertIn("lightning", pack["disclaimer"])

    def test_pack_from_real_shaped_forecast_keeps_attribution(self) -> None:
        forecast = build_site_forecast(SITES["hr1"], provider_payloads(), RUN, wave_ensemble())

        pack = build_pack(make_profile(), forecast, {}, RUN)

        self.assertTrue(any("ECMWF" in credit for credit in pack["attribution"]))
        self.assertTrue(any("DMI" in credit for credit in pack["attribution"]))
        self.assertTrue(any("Open-Meteo" in credit for credit in pack["attribution"]))

    def test_oversized_pack_is_refused(self) -> None:
        forecast = make_forecast(members=200, days=15)

        with self.assertRaises(BriefingPackError):
            build_pack(make_profile(), forecast, {}, RUN)

    def test_rejects_invalid_packs(self) -> None:
        good = through_json(build_pack(make_profile(), make_forecast(), {}, RUN))
        other_site = through_json(good)
        other_site["forecast"]["site_id"] = "hr2"
        damaged = through_json(good)
        del damaged["forecast"]["times"]
        cases = {
            "not a dict": [],
            "other format": {"format": "something-else"},
            "other version": {**good, "version": 2},
            "site mismatch": other_site,
            "damaged": damaged,
        }
        for name, pack in cases.items():
            with self.subTest(name), self.assertRaises(BriefingPackError):
                load_pack(pack)

    def test_loaded_pack_evaluates_like_original(self) -> None:
        forecast = make_forecast()
        profile = make_profile()

        loaded_profile, loaded_forecast = load_pack(through_json(build_pack(profile, forecast, {}, RUN)))

        self.assertEqual(evaluate_day(loaded_profile, loaded_forecast, DAY), evaluate_day(profile, forecast, DAY))


if __name__ == "__main__":
    unittest.main()
