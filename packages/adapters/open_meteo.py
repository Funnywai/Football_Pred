from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from packages.adapters.base import (
    AdapterSchemaError,
    BaseAdapter,
    FetchResult,
    MinIntervalRateLimiter,
)
from packages.shared.time import ensure_utc, parse_iso_utc


@dataclass(frozen=True)
class WeatherPoint:
    time_utc: datetime
    temperature_c: Decimal
    precipitation_mm: Decimal
    wind_speed_kmh: Decimal


@dataclass(frozen=True)
class WeatherSummary:
    point: WeatherPoint
    delta_hours: float


def _decimal_required(value: object, field: str, index: int) -> Decimal:
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise AdapterSchemaError(
            f"invalid hourly.{field} value {value!r} at index {index}"
        ) from exc
    if not parsed.is_finite():
        raise AdapterSchemaError(
            f"non-finite hourly.{field} value {value!r} at index {index}"
        )
    return parsed


class OpenMeteoAdapter(BaseAdapter):
    name = "open-meteo"
    tos_risk = "low"
    schema_version = "v1"

    def __init__(
        self,
        base_url: str = "https://api.open-meteo.com/v1/forecast",
        client=None,
        limiter: MinIntervalRateLimiter | None = None,
    ) -> None:
        super().__init__(client=client, limiter=limiter)
        self._base_url = base_url

    def fetch_hourly(
        self,
        latitude: float,
        longitude: float,
        start_date: date,
        end_date: date,
    ) -> FetchResult:
        params = {
            "latitude": latitude,
            "longitude": longitude,
            "hourly": "temperature_2m,precipitation,wind_speed_10m",
            "timezone": "UTC",
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
        }
        return self._get_json(self._base_url, params=params)

    @staticmethod
    def parse_hourly(payload: object) -> list[WeatherPoint]:
        if not isinstance(payload, dict):
            raise AdapterSchemaError(
                f"payload must be an object, got {type(payload).__name__}"
            )
        hourly = payload.get("hourly")
        if hourly is None:
            return []
        if not isinstance(hourly, dict):
            raise AdapterSchemaError(
                f"hourly must be an object, got {type(hourly).__name__}"
            )
        times = hourly.get("time", [])
        temperatures = hourly.get("temperature_2m", [])
        precipitation = hourly.get("precipitation", [])
        wind_speeds = hourly.get("wind_speed_10m", [])
        arrays = (
            ("time", times),
            ("temperature_2m", temperatures),
            ("precipitation", precipitation),
            ("wind_speed_10m", wind_speeds),
        )
        for field, values in arrays:
            if not isinstance(values, list):
                raise AdapterSchemaError(
                    f"hourly.{field} must be a list, got {type(values).__name__}"
                )
        if not (
            len(times)
            == len(temperatures)
            == len(precipitation)
            == len(wind_speeds)
        ):
            raise AdapterSchemaError("hourly arrays have different lengths")

        rows: list[WeatherPoint] = []
        for index, (raw_time, temp, rain, speed) in enumerate(
            zip(times, temperatures, precipitation, wind_speeds)
        ):
            if not isinstance(raw_time, str):
                raise AdapterSchemaError(f"missing hourly timestamp at index {index}")
            try:
                time_utc = parse_iso_utc(raw_time)
            except (TypeError, ValueError) as exc:
                raise AdapterSchemaError(
                    f"invalid hourly timestamp {raw_time!r} at index {index}"
                ) from exc
            if time_utc is None:
                raise AdapterSchemaError(f"missing hourly timestamp at index {index}")
            rows.append(
                WeatherPoint(
                    time_utc=time_utc,
                    temperature_c=_decimal_required(temp, "temperature_2m", index),
                    precipitation_mm=_decimal_required(rain, "precipitation", index),
                    wind_speed_kmh=_decimal_required(speed, "wind_speed_10m", index),
                )
            )
        return rows

    @staticmethod
    def nearest_to_kickoff(
        points: list[WeatherPoint],
        kickoff_at: datetime,
        max_delta_hours: float = 3.0,
    ) -> WeatherSummary | None:
        kickoff = ensure_utc(kickoff_at)
        best: WeatherPoint | None = None
        best_delta: float | None = None
        for point in points:
            point_time = ensure_utc(point.time_utc)
            delta = abs((point_time - kickoff).total_seconds()) / 3600.0
            if best_delta is None or delta < best_delta:
                best = point
                best_delta = delta
        if best is None or best_delta is None or best_delta > max_delta_hours:
            return None
        return WeatherSummary(point=best, delta_hours=best_delta)
