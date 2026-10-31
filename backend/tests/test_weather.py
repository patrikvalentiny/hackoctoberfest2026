import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from fastapi.testclient import TestClient

from backend.main import app


class FixtureResponse:
    def __init__(self, hourly: dict[str, list[str | float | None]]) -> None:
        self._hourly = hourly

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, dict[str, list[str | float | None]]]:
        return {"hourly": self._hourly}


class FixtureClient:
    def __init__(self, **_kwargs: object) -> None:
        first_hour = (datetime.now(timezone.utc) + timedelta(days=1)).replace(
            minute=0, second=0, microsecond=0
        )
        self.times = [
            (first_hour + timedelta(hours=offset))
            .replace(tzinfo=None)
            .isoformat(timespec="minutes")
            for offset in range(2)
        ]

    async def __aenter__(self) -> "FixtureClient":
        return self

    async def __aexit__(self, *_args: object) -> None:
        return None

    async def get(self, url: str, **_kwargs: object) -> FixtureResponse:
        if "marine-api" in url:
            return FixtureResponse(
                {
                    "time": self.times,
                    "wave_height": [1.2, 1.4],
                    "wave_period": [6.0, 6.5],
                    "wave_direction": [220.0, 225.0],
                    "swell_wave_height": [0.8, 0.9],
                    "swell_wave_period": [8.0, 8.5],
                }
            )
        return FixtureResponse(
            {
                "time": self.times,
                "wind_speed_10m": [14.0, 15.0],
                "wind_gusts_10m": [20.0, 21.0],
                "wind_direction_10m": [180.0, 185.0],
                "precipitation_probability": [10.0, 20.0],
                "visibility": [30000.0, 25000.0],
            }
        )


class ForecastEndpointTests(unittest.TestCase):
    def setUp(self) -> None:
        self.client = TestClient(app)

    def test_combines_weather_and_marine_forecasts(self) -> None:
        with patch("backend.main.httpx.AsyncClient", FixtureClient):
            response = self.client.get(
                "/api/forecast", params={"latitude": 56.0, "longitude": 2.0}
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["source"], "Open-Meteo weather and marine models")
        self.assertEqual(len(payload["hours"]), 2)
        self.assertEqual(payload["hours"][0]["wave_height_m"], 1.2)
        self.assertEqual(payload["hours"][0]["wind_speed_kn"], 14.0)
        self.assertTrue(payload["hours"][0]["time"].endswith("Z"))

    def test_rejects_coordinates_outside_valid_ranges(self) -> None:
        response = self.client.get(
            "/api/forecast", params={"latitude": 91, "longitude": 2}
        )

        self.assertEqual(response.status_code, 422)


if __name__ == "__main__":
    unittest.main()
