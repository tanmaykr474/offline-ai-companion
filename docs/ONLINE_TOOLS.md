# Optional weather and news — Module 12.11

External requests are **disabled by default**. Local memory retrieval, Ollama,
Whisper, Piper and SQLite do not require these tools. No dependencies were added;
the existing httpx package supplies HTTPS. No live provider calls were made during
automated verification.

## Setup

Add these settings to your local `.env`, using `config/.env.example` as reference:

```dotenv
NOVA_ONLINE_TOOLS_ENABLED=false
NOVA_WEATHER_PROVIDER=open-meteo
NOVA_NEWS_PROVIDER=newsapi
NOVA_WEATHER_LOCATION=Pune, India
NOVA_ONLINE_TIMEOUT=5
NOVA_NEWS_LIMIT=3
NOVA_NEWS_COUNTRY=us
NOVA_NEWS_TOPICS=general,technology,ai,cybersecurity,science,business,sports,health
NOVA_NEWS_MAX_AGE_HOURS=48
NEWS_API_KEY=
```

Set enablement to `true` only when you intend to permit external calls. Restart
Nova after configuration changes. Weather/news providers can be independently
omitted; unspecified provider settings fail clearly. Credentials remain local
configuration and are never committed. WEATHER_API_KEY remains a legacy unused
setting: the implemented non-commercial Open-Meteo adapter requires no API key.
Paid/custom endpoints are not supported.

`NOVA_ONLINE_TIMEOUT` must be positive and at most 15 seconds. Each weather
request uses at most two calls (geocoding and forecast); news uses one. No retries
occur. Transport read/connect timeouts plus a streaming deadline bound normal
requests. Native DNS/socket operations and synchronous HTTP reads cannot be
forcibly cancelled; cancellation is checked before/after I/O and between chunks.
Interruption discards late responses and preserves committed SQLite changes.
News limits are 1–5 headlines, with at most 15 candidate articles; age is 1–168
hours, default 48. Configured topic labels permit letters, spaces and hyphens.
Only a configured label is transmitted, not the rest of the user's speech.

## Commands and behavior

- “Nova, what's the weather today?” — modeled current conditions; asks for city
  unless a default is explicitly configured.
- “Nova, what's the temperature in Pune, India?” — explicit city geocoding.
- “Nova, will it rain tomorrow?” — tomorrow's daily precipitation probability.
- “Nova, what's the weather in Mumbai this evening?” — explicitly labeled daily
  forecast, with a warning that exact evening/hourly conditions are unavailable.
- “Nova, tell me today's top news.” — configured country's provider headlines;
  each story includes its actual publication time and may precede today.
- “Nova, what's happening in AI?”
- “Nova, give me technology headlines.”
- “Nova, any recent cybersecurity news?”

These are narrow live-info intents. Notes, reminders, tasks and personal memory
queries keep their existing routing. No provider is contacted while disabled,
when location is missing, when topics are unconfigured, or when credentials are
missing. Offline responses bypass Ollama rather than inventing live information.
Multiple geocoding results require city/country or region clarification; no
population-based or stored-memory location guessing occurs. Spoken city syntax
currently supports Latin letters and an optional comma qualifier. Other date
expressions, arbitrary time ranges, free-form topic searches and news follow-up
conversation are unsupported.

## Provider contracts verified against official documentation

- [Open-Meteo forecast](https://open-meteo.com/en/docs): `/v1/forecast`, current
  temperature/weather code and two daily forecasts with Celsius and probability
  units; provider timezone and date/time are validated. Current conditions are
  **modeled**, not represented as direct station observations. Data older than
  two hours is refused. Weather code mapping uses the documented WMO codes.
- [Open-Meteo geocoding](https://open-meteo.com/en/docs/geocoding-api):
  `/v1/search`, city name, count, language, JSON; supports comma qualifiers.
  Location data attribution: GeoNames, via Open-Meteo.
- [Open-Meteo terms](https://open-meteo.com/en/terms): free API is for
  non-commercial use and requires CC-BY attribution. Commercial endpoints/plans
  need a separately reviewed adapter. Providers can retain IP/query/coordinate
  logs under their own policies.
- [NewsAPI top headlines](https://newsapi.org/docs/endpoints/top-headlines) and
  [Everything](https://newsapi.org/docs/endpoints/everything): country headlines
  or configured topic search, bounded page size, UTC publication timestamps.
  [Authentication](https://newsapi.org/docs/authentication) uses `X-Api-Key`,
  never a key in the URL. Source, title and publication time are returned;
  article bodies/descriptions are not summarized or spoken.
- [NewsAPI plans](https://newsapi.org/pricing): the developer plan is for
  development/testing and can delay articles by 24 hours. A production companion
  may require another plan. Nova does not label stories “breaking”; publication
  timestamps and the delay warning are spoken. Older/future/undated stories are
  skipped. No usable recent results produces an honest response.

## Privacy and network boundaries

Only fixed HTTPS hosts/paths are allowed: `geocoding-api.open-meteo.com/v1/search`,
`api.open-meteo.com/v1/forecast`, `newsapi.org/v2/top-headlines`, and
`newsapi.org/v2/everything`. Redirects are rejected, environment proxies disabled,
TLS verification retained, and clients closed after every call. JSON responses
are capped at 256 KiB; unsupported content types/encodings are rejected. Provider
selection accepts adapter names, never arbitrary URLs. DNS/TLS and provider
availability remain external dependencies; this is not a machine-wide firewall.

Weather transmits explicit/configured city and provider-resolved coordinates.
News transmits configured topic/country and its API credential. No raw audio,
personal facts, notes, reminders, conversation history or unrelated query text is
sent. Providers see connection metadata such as IP address. Results bypass LLM
prompts entirely and are treated as data: HTML/URLs/control characters are
removed, recognized secrets and obvious instruction-bearing fields rejected.
This prevents instructions from controlling Nova but cannot certify headline
truth or classify every malicious sentence. Provider content is not persisted as
personal memory or appended to conversation history. Routine Nova logs contain
fixed error categories only; enabling third-party httpx/httpcore debug tracing
can expose request details and is outside the privacy-safe diagnostics mode.

## Manual validation still required

1. Confirm offline requests produce the offline response with no provider traffic.
2. Enable one provider, supply explicit city or development key, and compare actual
   units, timestamps, source attribution and malformed/error handling with its API.
3. Test city ambiguity, unavailable network and provider rate limits.
4. Speak weather/news requests, interrupt playback, then recall an existing fact
   and verify it remains intact. Check mute blocks requests and unmute recovers.
5. Capture only sanitized error categories, durations and state changes.

New online workflows have mocked integration coverage, not physical/live-provider
verification. Basic Windows audio/interruption validation was previously reported
passed; multi-hour physical reliability testing remains deferred. No Pi deployment
is included.
