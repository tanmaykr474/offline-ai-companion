"""Opt-in, fixed-provider live information. Never sends assistant memory/history."""
import html
import json
import logging
import math
import os
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
import httpx

from offline_ai_companion.core.cancellation import check_cancel
from offline_ai_companion.core.privacy_policy import contains_secret, allows_storage
from offline_ai_companion.tools.online_requests import parse_online_request

logger = logging.getLogger("nova.online")
OFFLINE = "Live weather and news are unavailable offline. Online tools are disabled."
ENDPOINTS = {
    "geocoding": "https://geocoding-api.open-meteo.com/v1/search",
    "weather": "https://api.open-meteo.com/v1/forecast",
    "news_top": "https://newsapi.org/v2/top-headlines",
    "news_search": "https://newsapi.org/v2/everything",
}


class ProviderError(RuntimeError):
    """Only a fixed error category is retained; never a URL, body or credentials."""
    CODES = {"offline", "configuration", "timeout", "network", "http", "credentials",
             "rate_limit", "redirect", "format", "size", "empty", "stale", "location"}

    def __init__(self, code):
        self.code = code if code in self.CODES else "format"
        super().__init__(self.code)


@dataclass(frozen=True)
class OnlineConfig:
    enabled: bool = False
    weather_provider: str = ""
    news_provider: str = ""
    news_key: str = field(default="", repr=False)
    default_location: str = ""
    timeout: float = 5.0
    news_limit: int = 3
    news_country: str = "us"
    news_topics: tuple = ("general", "technology", "ai", "cybersecurity", "science", "business", "sports", "health")
    news_max_age_hours: int = 48

    def __post_init__(self):
        if not isinstance(self.enabled, bool):
            raise ValueError("Online enablement must be boolean.")
        if self.weather_provider not in {"", "open-meteo"} or self.news_provider not in {"", "newsapi"}:
            raise ValueError("Unsupported online provider; use open-meteo or newsapi.")
        if not math.isfinite(self.timeout) or not 0 < self.timeout <= 15:
            raise ValueError("Online timeout must be positive and at most 15 seconds.")
        if not 1 <= self.news_limit <= 5 or not 1 <= self.news_max_age_hours <= 168:
            raise ValueError("Invalid news result or age limit.")
        if not re.fullmatch(r"[a-z]{2}", self.news_country):
            raise ValueError("News country must be a two-letter code.")
        if len(self.news_topics) > 20 or any(not re.fullmatch(r"[a-z][a-z -]{0,40}", t) or not allows_storage(t) for t in self.news_topics):
            raise ValueError("Invalid configured news topics.")
        if self.default_location and (not re.fullmatch(r"[^\W\d_][\w ,'-]{1,79}", self.default_location) or not allows_storage(self.default_location)):
            raise ValueError("Invalid default weather location.")
        if re.search(r"\b(?:my|your|our|i|we|and|but|because|remember)\b", self.default_location, re.I):
            raise ValueError("Default weather location must contain only a location.")
        if len(self.news_key) > 256 or re.search(r"[\x00-\x20\x7f]", self.news_key):
            raise ValueError("Invalid news credential format.")

    @classmethod
    def from_env(cls):
        # config has already loaded the project's .env before Assistant creates us.
        flag = os.getenv("NOVA_ONLINE_TOOLS_ENABLED", "false").strip().lower()
        if flag not in {"false", "true", "0", "1", "yes", "no", "on", "off"}:
            raise ValueError("NOVA_ONLINE_TOOLS_ENABLED must be a boolean.")
        try:
            return cls(enabled=flag in {"true", "1", "yes", "on"},
                       weather_provider=os.getenv("NOVA_WEATHER_PROVIDER", "").strip(),
                       news_provider=os.getenv("NOVA_NEWS_PROVIDER", "").strip(),
                       news_key=os.getenv("NEWS_API_KEY", "").strip(),
                       default_location=os.getenv("NOVA_WEATHER_LOCATION", "").strip(),
                       timeout=float(os.getenv("NOVA_ONLINE_TIMEOUT", "5")),
                       news_limit=int(os.getenv("NOVA_NEWS_LIMIT", "3")),
                       news_country=os.getenv("NOVA_NEWS_COUNTRY", "us").strip().lower(),
                       news_topics=tuple(t.strip().lower() for t in os.getenv("NOVA_NEWS_TOPICS", "general,technology,ai,cybersecurity,science,business,sports,health").split(",") if t.strip()),
                       news_max_age_hours=int(os.getenv("NOVA_NEWS_MAX_AGE_HOURS", "48")))
        except (ValueError, OverflowError):
            raise ValueError("Invalid online tool configuration; check documented settings.") from None


class ProviderHTTP:
    MAX_BYTES = 256 * 1024

    def __init__(self, config, transport=None, clock=time.monotonic):
        self.config, self.transport, self.clock = config, transport, clock

    def get_json(self, endpoint, params, headers=None):
        if not self.config.enabled:
            raise ProviderError("offline")
        provider = self.config.news_provider if endpoint.startswith("news_") else self.config.weather_provider
        expected = "newsapi" if endpoint.startswith("news_") else "open-meteo"
        if endpoint not in ENDPOINTS or provider != expected:
            raise ProviderError("configuration")
        check_cancel()
        deadline = self.clock() + self.config.timeout
        try:
            # Per-request client closes sockets on every success/error/cancellation.
            with httpx.Client(timeout=self.config.timeout, follow_redirects=False,
                              trust_env=False, transport=self.transport) as client:
                with client.stream("GET", ENDPOINTS[endpoint], params=params,
                                   headers={"Accept": "application/json", "Accept-Encoding": "identity", **(headers or {})}) as response:
                    if 300 <= response.status_code < 400:
                        raise ProviderError("redirect")
                    if response.status_code in {401, 403}:
                        raise ProviderError("credentials")
                    if response.status_code == 429:
                        raise ProviderError("rate_limit")
                    if response.status_code != 200:
                        raise ProviderError("http")
                    if response.headers.get("content-type", "").split(";")[0].strip().lower() != "application/json":
                        raise ProviderError("format")
                    if response.headers.get("content-encoding", "identity").lower() != "identity":
                        raise ProviderError("format")
                    length = response.headers.get("content-length")
                    if length and int(length) > self.MAX_BYTES:
                        raise ProviderError("size")
                    data = bytearray()
                    for chunk in response.iter_bytes(chunk_size=8192):
                        check_cancel()
                        if self.clock() >= deadline:
                            raise ProviderError("timeout")
                        data.extend(chunk)
                        if len(data) > self.MAX_BYTES:
                            raise ProviderError("size")
                    check_cancel()
                    if self.clock() >= deadline:
                        raise ProviderError("timeout")
                    decoded = json.loads(data)
                    if not isinstance(decoded, dict):
                        raise ProviderError("format")
                    return decoded
        except httpx.TimeoutException:
            raise ProviderError("timeout") from None
        except httpx.HTTPError:
            raise ProviderError("network") from None
        except (ValueError, UnicodeError, RecursionError):
            raise ProviderError("format") from None


INSTRUCTIONS = re.compile(r"\b(?:ignore (?:all |previous |prior )?instructions|system prompt|"
                          r"you are (?:now |an? )|assistant:|execute|run (?:this|the) command|"
                          r"reveal|send (?:me|your)|api key|password|bearer)\b", re.I)


def public_text(value, limit=180):
    if not isinstance(value, str) or len(value) > 2000:
        return ""
    value = html.unescape(value)
    if contains_secret(value) or INSTRUCTIONS.search(value):
        return ""
    value = re.sub(r"<[^>]*>|https?://\S+|www\.\S+|[\x00-\x1f\x7f]", " ", value)
    return " ".join(value.split())[:limit]


def number(value, low, high):
    if isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value) or not low <= value <= high:
        raise ProviderError("format")
    return value


class OpenMeteoWeather:
    def __init__(self, http, clock=None):
        self.http = http
        self.clock = clock or (lambda: datetime.now(timezone.utc))

    def answer(self, request):
        city = request.location or self.http.config.default_location
        if not city:
            return "Which city? Set a default weather location or name a city explicitly."
        if not allows_storage(city) or not re.fullmatch(r"[^\W\d_][\w ,'-]{1,79}", city):
            raise ProviderError("location")
        data = self.http.get_json("geocoding", {"name": city, "count": 5, "language": "en", "format": "json"})
        places = data.get("results", [])
        if not isinstance(places, list):
            raise ProviderError("format")
        if not places:
            return "I couldn't find that city. Please include its country or region."
        if len(places) > 1:
            options = [", ".join(filter(None, (public_text(p.get("name"), 40), public_text(p.get("admin1"), 40), public_text(p.get("country"), 40)))) for p in places[:3] if isinstance(p, dict)]
            return "That location is ambiguous. Specify city and country or region. Matches: " + "; ".join(options) + "."
        place = places[0]
        if not isinstance(place, dict):
            raise ProviderError("format")
        latitude = number(place.get("latitude"), -90, 90)
        longitude = number(place.get("longitude"), -180, 180)
        location = public_text(place.get("name"), 60)
        if not location:
            raise ProviderError("format")
        data = self.http.get_json("weather", {
            "latitude": latitude, "longitude": longitude, "current": "temperature_2m,weather_code",
            "daily": "temperature_2m_max,temperature_2m_min,precipitation_probability_max",
            "timezone": "auto", "forecast_days": 2, "temperature_unit": "celsius"})
        try:
            zone = ZoneInfo(data["timezone"])
            now = self.clock().astimezone(zone)
            if request.period == "current":
                current = data["current"]
                stamp = datetime.fromisoformat(current["time"])
                stamp = stamp.replace(tzinfo=zone) if stamp.utcoffset() is None else stamp.astimezone(zone)
                if abs((now-stamp).total_seconds()) > 7200:
                    raise ProviderError("stale")
                temperature = number(current["temperature_2m"], -100, 70)
                if data["current_units"]["temperature_2m"] != "°C":
                    raise ProviderError("format")
                code = number(current["weather_code"], 0, 99)
                condition = ("clear" if code == 0 else "partly cloudy" if code in {1,2} else "overcast" if code == 3
                             else "foggy" if code in {45,48} else "rain or drizzle" if code in {51,53,55,56,57,61,63,65,66,67,80,81,82}
                             else "snow" if code in {71,73,75,77,85,86} else "thunderstorms" if code in {95,96,99} else "conditions unspecified")
                return f"Open-Meteo modeled current conditions in {location}: {temperature:g} degrees Celsius, {condition}, at {stamp.strftime('%Y-%m-%d %H:%M')} {zone.key}."
            daily = data["daily"]
            day = (now + timedelta(days=1 if request.period == "tomorrow" else 0)).date().isoformat()
            index = daily["time"].index(day)
            high = number(daily["temperature_2m_max"][index], -100, 70)
            low = number(daily["temperature_2m_min"][index], -100, 70)
            rain = number(daily["precipitation_probability_max"][index], 0, 100)
            if data["daily_units"]["temperature_2m_max"] != "°C" or data["daily_units"]["temperature_2m_min"] != "°C" or data["daily_units"]["precipitation_probability_max"] != "%":
                raise ProviderError("format")
            return f"Open-Meteo daily forecast for {location} on {day} ({zone.key}): {low:g} to {high:g} degrees Celsius, up to {rain:g} percent precipitation probability. This is a daily forecast, not exact evening or hourly conditions."
        except (KeyError, TypeError, ValueError, IndexError, OverflowError):
            raise ProviderError("format") from None


class NewsAPIHeadlines:
    def __init__(self, http, clock=None):
        self.http = http
        self.clock = clock or (lambda: datetime.now(timezone.utc))

    def answer(self, request):
        config = self.http.config
        if not config.news_key:
            raise ProviderError("configuration")
        aliases = {"artificial intelligence": "ai", "tech": "technology", "cyber security": "cybersecurity"}
        topic = aliases.get(request.topic, request.topic)
        if topic not in config.news_topics:
            return "Choose a configured news topic: " + ", ".join(config.news_topics) + "."
        now = self.clock()
        if now.utcoffset() is None:
            raise ProviderError("configuration")
        params = {"pageSize": min(config.news_limit * 3, 15), "page": 1}
        if topic == "general":
            endpoint = "news_top"
            params["country"] = config.news_country
        else:
            endpoint = "news_search"
            params.update(q="artificial intelligence" if topic == "ai" else topic,
                          language="en", sortBy="publishedAt",
                          **{"from": (now-timedelta(hours=config.news_max_age_hours)).isoformat()})
        data = self.http.get_json(endpoint, params, {"X-Api-Key": config.news_key})
        if data.get("status") != "ok":
            code = data.get("code")
            raise ProviderError("rate_limit" if code == "rateLimited" else "credentials" if code in {"apiKeyInvalid", "apiKeyMissing", "apiKeyDisabled"} else "http")
        articles = data.get("articles")
        if not isinstance(articles, list):
            raise ProviderError("format")
        lines, seen, stale = [], set(), False
        for article in articles[:15]:
            check_cancel()
            if not isinstance(article, dict):
                continue
            source_data = article.get("source")
            if config.news_key in str(article.get("title", "")) or config.news_key in str(source_data):
                continue
            title = public_text(article.get("title"))
            source = public_text(source_data.get("name") if isinstance(source_data, dict) else None, 60)
            if not title or not source or title in seen or title == "[Removed]":
                continue
            try:
                stamp = datetime.fromisoformat(article["publishedAt"].replace("Z", "+00:00"))
                if stamp.utcoffset() is None:
                    continue
                age = (now-stamp).total_seconds()
                if age < -300:
                    continue
                if age > config.news_max_age_hours * 3600:
                    stale = True
                    continue
            except (KeyError, ValueError, TypeError, AttributeError):
                continue
            seen.add(title)
            lines.append(f"{title}, from {source}, published {stamp.astimezone(timezone.utc).strftime('%Y-%m-%d %H:%M')} UTC.")
            if len(lines) == config.news_limit:
                break
        if not lines:
            return "No recent usable headlines were returned." + (" Older stories were excluded." if stale else "")
        return "NewsAPI headlines; publication times may be delayed by the provider: " + " ".join(lines)


class OnlineTools:
    def __init__(self, config=None, transport=None, clock=None):
        self.config = config if config is not None else OnlineConfig.from_env()
        self.http = ProviderHTTP(self.config, transport)
        self.weather = OpenMeteoWeather(self.http, clock)
        self.news = NewsAPIHeadlines(self.http, clock)

    def execute(self, query):
        request = parse_online_request(query)
        if request is None:
            raise ValueError("Unsupported online intent.")
        if not self.config.enabled:
            return OFFLINE
        if contains_secret(query):
            return "That request contains sensitive information and cannot be sent to an online provider."
        check_cancel()
        try:
            response = self.weather.answer(request) if request.kind == "weather" else self.news.answer(request)
            check_cancel()
            return response
        except ProviderError as exc:
            logger.warning("Online tool failure: %s", exc.code)
            messages = {"configuration": "The requested online provider or credentials are not configured.",
                        "timeout": "The online provider timed out. Please try again later.",
                        "rate_limit": "The online provider rate limit was reached. Please try again later.",
                        "credentials": "The online provider rejected its credentials.",
                        "stale": "The provider returned stale weather data; I can't report it as current."}
            return messages.get(exc.code, "Live information is unavailable because the provider request failed.")
