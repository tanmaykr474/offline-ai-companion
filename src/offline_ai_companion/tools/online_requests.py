"""Narrow live-tool intents; no execution and no personal-data inference."""
import re
from dataclasses import dataclass


@dataclass(frozen=True)
class OnlineRequest:
    kind: str
    location: str = ""
    period: str = "current"
    topic: str = "general"


def parse_online_request(query):
    text = re.sub(r"^(?:hey\s+)?nova[,\s]+", "", query.strip(), flags=re.I).rstrip(" .!?")
    text = " ".join(text.casefold().replace("’", "'").split())
    weather = re.fullmatch(
        r"(?:what(?:'s| is) (?:the )?(?:weather|temperature)|"
        r"tell me (?:the )?weather|(?:give|show) me (?:the )?(?:weather|forecast)|"
        r"will it rain)(?: (.+))?", text)
    if weather:
        tail = weather[1] or ""
        period = "tomorrow" if "tomorrow" in tail else "today" if any(w in tail for w in ("evening", "tonight", "forecast")) or "forecast" in text else "current"
        # Only explicitly stated cities, with optional country/admin qualifier.
        location = re.search(r"\bin ([a-z][a-z ,'-]{1,79}?)(?= (?:today|tomorrow|this evening|tonight|now)$|$)", tail)
        if location:
            city = location[1].strip()
            remainder = tail[:location.start()] + tail[location.end():]
        else:
            city, remainder = "", tail
        if city and re.search(r"\b(?:my|your|our|his|her|their|i|we|and|but|because|remember|password|token|key)\b", city):
            # A location field cannot be used to smuggle an adjacent personal
            # statement into an external query.
            return None
        if remainder.strip() not in {"", "today", "tomorrow", "this evening", "tonight", "now"}:
            return None
        return OnlineRequest("weather", city, period)
    general = {"tell me today's top news", "what's the news", "what is the news",
               "tell me the news", "give me today's news", "give me top news", "tell me today's news"}
    if text in general:
        return OnlineRequest("news")
    topic = re.fullmatch(r"(?:what(?:'s| is) happening in|give me|tell me|any recent) ([a-z][a-z -]{0,40}?)(?: news| headlines)?", text)
    if topic and ("happening in" in text or text.endswith((" news", " headlines"))):
        return OnlineRequest("news", topic=topic[1])
    return None
