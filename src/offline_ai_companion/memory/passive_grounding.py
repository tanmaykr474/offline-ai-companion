"""Conservative assertion and time checks, independent of model suggestions."""

import re
from datetime import date, datetime, time, timedelta, timezone


def normalize(text):
    return " ".join(text.casefold().replace("’", "'").split()).strip(" .!?\n")


def statements(transcript):
    """Keep question marks and quoted sentence boundaries intact."""
    start = 0
    quote = None
    for index, char in enumerate(transcript):
        closed_quote = False
        if char in {'"', '“', '”', "'", '‘', '’'}:
            # Apostrophes inside words are contractions, not quotation marks.
            internal = (index > 0 and index + 1 < len(transcript)
                        and transcript[index - 1].isalnum()
                        and transcript[index + 1].isalnum())
            if not internal:
                if quote is None:
                    quote = char
                elif char == quote or (quote, char) in {('“', '”'), ('‘', '’')}:
                    quote = None
                    closed_quote = True
        boundary = char in "!?\n" or (char == "." and (
            index + 1 == len(transcript) or transcript[index + 1].isspace()))
        boundary = boundary or (closed_quote and index > 0
                                and transcript[index - 1] in ".!?"
                                and (index + 1 == len(transcript)
                                     or transcript[index + 1].isspace()))
        if boundary and quote is None:
            if transcript[start:index + 1].strip():
                yield transcript[start:index + 1].strip()
            start = index + 1
    if transcript[start:].strip():
        yield transcript[start:].strip()


UNASSERTED = re.compile(
    r"\b(?:not|never|neither|nor|no|cannot|can't|won't|don't|doesn't|didn't|"
    r"isn't|aren't|wasn't|weren't|haven't|hasn't|hadn't|shouldn't|wouldn't|"
    r"couldn't|mustn't|needn't|used to|if|unless|suppose|supposing|imagine|"
    r"hypothetically|would|could|might|may|maybe|perhaps|probably|possibly|"
    r"unsure|uncertain|guess|think|hope|wish|said|says|asked|asks|told|"
    r"quoted|quote|but|except|whether|either|or|cancelled|canceled|"
    r"unlikely|doubt|doubtful)\b", re.I,
)


def asserted_statement(evidence, transcript):
    """Evidence must be a whole affirmative speaker statement, not a substring."""
    if "?" in evidence:
        return None
    target = normalize(evidence)
    for statement in statements(transcript):
        if normalize(statement) != target:
            continue
        text = statement.replace("’", "'")
        if "?" in text or re.search(r'["“”‘’]|(?<!\w)\'|\'(?!\w)', text):
            continue
        if UNASSERTED.search(text):
            continue
        if re.match(r"\s*(?:do|does|did|am|is|are|was|were|can|will|should|"
                    r"what|where|when|why|how|who)\b", text, re.I):
            continue
        return statement
    return None


def supported_action(category, content, statement):
    """Keep action order and all qualifiers; word sets do not prove entailment."""
    text = normalize(statement)
    if category == "task":
        match = re.fullmatch(r"i (?:need to|have to|must|plan to|am going to|"
                             r"intend to|should|will) (.+)", text)
        if match is None:
            return False
        alternatives = {text, text.removeprefix("i "), match[1]}
    else:
        match = re.fullmatch(r"i (?:have|had|am attending|am scheduled for|"
                             r"will attend|attend) (.+)", text)
        if match is None:
            return False
        body = match[1]
        # Have a meeting -> meeting. Attendance actions retain their verb.
        if text.startswith(("i have ", "i had ", "i am scheduled for ")):
            alternatives = {text, text.removeprefix("i "), body}
        else:
            alternatives = {text, text.removeprefix("i ")}
            if text.startswith("i will attend "):
                alternatives.add("attend " + body)
    def tokens(value):
        # Articles and incidental punctuation do not change the asserted action.
        return tuple(word for word in re.findall(r"[+-]?\d+|[^\W\d_]+", value)
                     if word not in {"a", "an", "the"})
    return tokens(normalize(content)) in {tokens(value) for value in alternatives}


def grounded_event_time(evidence, captured_at, proposed):
    """Resolve only ISO dates, today/tomorrow/yesterday, and explicit 24h clocks.

    A date stays a date. No midnight or guessed weekday/month/day is introduced.
    Unknown time expressions remain in evidence when no timestamp is proposed.
    """
    if proposed is not None and not isinstance(proposed, str):
        return False, None
    iso_dates = re.findall(r"\b\d{4}-\d{2}-\d{2}\b", evidence)
    relative = re.findall(r"\b(today|tomorrow|yesterday|tonight)\b", evidence, re.I)
    if len(iso_dates) + len(relative) != 1:
        return proposed is None, None
    try:
        if iso_dates:
            day = date.fromisoformat(iso_dates[0])
        else:
            if captured_at is None or captured_at.utcoffset() is None:
                return proposed is None, None
            delta = {"today": 0, "tonight": 0, "tomorrow": 1, "yesterday": -1}
            day = captured_at.date() + timedelta(days=delta[relative[0].lower()])
        clocks = list(re.finditer(r"\bat\s+(\d{2}):(\d{2})(?::(\d{2}))?"
                                 r"(?:\s*(Z|[+-]\d{2}:\d{2}))?", evidence, re.I))
        # Other date/time expressions would make the resolution ambiguous.
        if re.search(r"\b(?:next|monday|tuesday|wednesday|thursday|friday|"
                     r"saturday|sunday|january|february|march|april|may|june|"
                     r"july|august|september|october|november|december)\b|"
                     r"\b\d{1,2}/\d{1,2}(?:/\d{2,4})?\b", evidence, re.I):
            return proposed is None, None
        if len(clocks) > 1:
            return proposed is None, None
        resolved = day.isoformat()
        if clocks:
            clock = clocks[0]
            if evidence[clock.end():].strip(" .!?\n"):
                return proposed is None, None
            zone = clock[4]
            if zone:
                offset = "+00:00" if zone.upper() == "Z" else zone
                if int(offset[1:3]) > 23 or int(offset[4:6]) > 59:
                    return False, None
                tz = datetime.fromisoformat("2000-01-01T00:00:00" + offset).tzinfo
            else:
                tz = captured_at.tzinfo if captured_at is not None else None
            if tz is None:
                return proposed is None, None
            instant = datetime.combine(day, time(int(clock[1]), int(clock[2]),
                                                int(clock[3] or 0)), tzinfo=tz)
            # Reject ambiguous/nonexistent local times at DST transitions.
            if (instant.replace(fold=0).utcoffset() != instant.replace(fold=1).utcoffset()
                    or instant.astimezone(timezone.utc).astimezone(tz) != instant):
                return False, None
            resolved = instant.isoformat()
        elif re.search(r"\bat\s+\d|\b(?:noon|midnight|morning|afternoon|evening)|"
                       r"\b\d{1,2}\s*(?:am|pm)\b", evidence, re.I):
            return proposed is None, None
        if proposed is None:
            return True, resolved
        if len(resolved) == 10:
            return proposed == resolved, resolved
        candidate = datetime.fromisoformat(proposed)
        return (candidate.utcoffset() is not None and
                candidate == datetime.fromisoformat(resolved)), resolved
    except (ValueError, OverflowError):
        return False, None
