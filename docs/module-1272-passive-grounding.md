# Module 12.7.2 — Passive memory grounding

All model candidates still pass the processor's validation before SQLite writes.
The repository remains a storage API, not an extraction or assertion validator.
Existing confirmed facts, recall, privacy controls and local model policy are unchanged.

## Assertion rules

- Evidence must identify a complete affirmative statement in the original
  caption-filtered transcript. A substring cannot remove a question prefix,
  negation, conditional clause, reported speaker or qualifier.
- Question marks are preserved during validation. Negation, conditionality,
  uncertainty, reported speech and quotation are rejected conservatively.
  Apostrophes inside words are distinguished from quotation marks.
- Quoted sentence endings do not swallow subsequent ordinary statements.
  Candidates in mixed transcripts are checked individually. Favorites after
  an invalid favorite statement can still be extracted.
- Personal observations must exactly match the existing deterministic extractor.
  Arbitrary model-proposed facts and preferences remain disabled.
- Tasks require an explicit first-person intention or obligation. Events require
  an explicit first-person event assertion and an existing event/date cue.
  Content must preserve the asserted action's ordered words and qualifiers;
  articles and incidental punctuation may differ. Word overlap is no longer the
  task/event grounding criterion. Unsupported paraphrases are rejected.
- Malformed candidate categories and fields fail closed. Sensitive transcript
  filtering, caption filtering, item limits and duplicate prevention are retained.

## Time rules

- Only explicit ISO calendar dates (`YYYY-MM-DD`) and today, tomorrow, yesterday
  or tonight are resolved. Relative days use the original aware capture timestamp
  in its original timezone. A date remains a date, never an invented midnight.
- Exact instants require an explicit `at HH:MM` or `at HH:MM:SS` clock, with an
  optional `Z` or numeric UTC offset, at the end of the statement. Without an
  explicit offset, the capture timezone supplies the context. Model timestamps
  must match the resolved instant; equivalent UTC representations are accepted.
- Invalid calendar/clock values, mismatched timestamps and ambiguous or
  nonexistent times in supplied DST-aware zones are rejected.
- Weekdays, named-month dates, slash dates, multiple date references, AM/PM,
  noon, named timezone abbreviations and other ambiguous expressions are not
  converted into timestamps. An event may retain that wording with null
  `event_time`; a model-proposed exact timestamp for it is rejected.
- The voice loop records completion time before STT and passes it to the real
  passive worker. The worker carries it through queued extraction. Direct worker
  submissions default to acceptance time in the local timezone, or accept an
  explicit aware `captured_at`. One-argument injected processors remain supported;
  such adapters must arrange their own timestamp forwarding if they wrap extraction.
  Direct processor calls without `captured_at` retain their existing UTC default;
  callers with speech-local context should supply its aware timestamp.

## Deliberate limits

These are conservative English grammar checks, not a general semantic entailment
engine. Unrecognized phrasing and complex clauses may be rejected, and unusual
idioms, irony or cross-sentence retractions can require stronger future handling.
Negative facts are not stored by this module. Quoted titles and reported personal
statements are intentionally excluded. The existing deterministic-first path
remains: when recognized personal statements exist, model extraction is skipped,
so additional tasks/events in that transcript are not extracted.

Recording completion is an approximation of speech capture time; utterances
crossing midnight and incorrect OS clocks/timezone settings remain limitations.
Previously saved records are not rewritten or deleted. No scheduler, new
extraction category, physical-device validation or Module 12.7.3 is included.

Regression tests use temporary SQLite databases and mocked models/audio. They
cover supported and rejected personal statements, tasks/events, questions,
conditionals, uncertainty, quotes, mixed statements, reordered/omitted content,
dates, timezones, malformed model responses, duplicate prevention and queue/STT
delays. See `tests/unit/test_passive_grounding_safety.py` and
`tests/integration/test_passive_capture_timestamp.py`.

Verification: the final focused run passed 252 tests. The full Python 3.13 suite
passed **613 tests in 63.60 seconds**, preserving the 503 existing tests and adding
110 regression cases. Existing test files were not changed.
