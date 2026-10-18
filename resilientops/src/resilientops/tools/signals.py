"""Public signal collection is explicit; it never overwrites a demo incident."""

import httpx

from resilientops.models import utcnow


async def fetch_signals(latitude: float, longitude: float) -> dict:
    if not -90 <= latitude <= 90 or not -180 <= longitude <= 180:
        raise ValueError("Invalid coordinates")
    sources = {}
    async with httpx.AsyncClient(timeout=15, follow_redirects=False) as client:
        requests = {
            "eonet": (
                "https://eonet.gsfc.nasa.gov/api/v3/events",
                {"status": "open", "limit": 30, "days": 7},
            ),
            "weather": (
                "https://api.open-meteo.com/v1/forecast",
                {
                    "latitude": latitude,
                    "longitude": longitude,
                    "hourly": "precipitation,wind_speed_10m",
                    "forecast_days": 3,
                    "timezone": "UTC",
                },
            ),
        }
        for source, (url, params) in requests.items():
            try:
                response = await client.get(url, params=params)
                response.raise_for_status()
                sources[source] = {"status": "ok", "source_url": url, "data": response.json()}
            except (httpx.HTTPError, ValueError) as exc:
                sources[source] = {"status": "unavailable", "error_type": type(exc).__name__}
    return {
        "retrieved_at": utcnow().isoformat(),
        "sources": sources,
        "note": "Raw public signals. Geographic exposure requires corroboration before a delay is asserted.",
    }
