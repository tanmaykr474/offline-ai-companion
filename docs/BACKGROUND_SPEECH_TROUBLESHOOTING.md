# Background speech and missed greeting activation

## What the console messages mean

Background speech queued means a transcription did not match an active wake
command and was accepted for optional passive processing. It does not mean a
memory was saved. Zero saves can be correct when the text contains no supported
observation or a model proposes claims that fail evidence checks. The message
alone cannot establish whether the microphone captured speech or background noise.

## Fixes

- When the configured bare assistant name is enabled, `Hello Nova` and `Hi Nova`
  activate a greeting. A command following either greeting routes normally.
  Custom wake-only configurations retain their configured phrases.
- Whisper acoustic-segment line breaks become spaces before routing and memory
  extraction. Questions, quotation marks and negation remain intact.
- Passive extraction reports bounded candidate/rejection/save counts, without
  printing transcripts or candidate contents. A rejection summary explains that
  no supported memory was stored. Hallucination safeguards remain enforced.

## Recheck on Windows

1. Stop any running Nova instance with Ctrl+C and wait for shutdown.
2. Restart with `scripts/start_clean_test.ps1` for isolated test data.
3. Say `Hello Nova`. Expect an active spoken greeting rather than a passive queue.
4. Say `Nova, what is my favorite food?`. Expect an honest missing-value answer
   in the fresh database, rather than a saved observation from the question.
5. Say `I love playing cricket` without a wake phrase. Wait for extraction to
   finish, then ask `Nova, what sport do I love playing?`.
6. Leave the room quiet briefly. Caption-only or empty transcriptions should be
   ignored. An intelligible-looking noise hallucination may still be queued,
   but unsupported memories must not be stored.

This patch does not implement acoustic noise cancellation or guarantee that
Whisper recognizes every live utterance. Physical microphone rechecking remains
necessary. Software tests use mocked transcription and isolated SQLite databases.

## A memory saves but recall reports insufficient evidence

First distinguish `saved=1` from a queued transcription. A saved cricket
observation supports `What sport do I love playing?`. Direct wrappers such as
`Do you remember what sport I love playing?`, `Can you tell me what sport I love
playing?`, and the spoken variant `What sport I love playing?` now use the same
grounded relation matcher. Recall creates no new memories and keeps unknown
speaker attribution. Love is not silently changed to like, and extra temporal
or negative qualifiers must still have supporting evidence.

If the exact question still fails, collect its wording and the sanitized MEMORY
status lines. A successful typed query alone cannot prove live STT heard the same
words. Each fresh clean-test launch starts a new database, so save and recall in
the same session when checking this behavior.

Run `python scripts/check_clean_test_recall.py` to query the most recently
modified clean-test database without using the microphone or models. For an
unambiguous session, pass `--database "FULL_PATH_FROM_THE_LAUNCHER"`. The tool
backs up the source through a read-only SQLite connection and runs retrieval on
a temporary snapshot. It displays the requested grounded answer, so use it in
a private terminal. The original database remains unchanged.

## Compare speech with Whisper output

Stop the current application and run
`./scripts/start_clean_test.ps1 -ShowTranscript` in PowerShell. Accepted input
is printed as `[STT TRANSCRIPT] '...'` before caption filtering and routing.
This lets you see missing wake words or changed question wording, including
caption-only results. Recognized credentials are omitted and control characters
are escaped, but ordinary personal speech is visible. Keep this mode local and
disable it after troubleshooting by exiting and restarting without the switch.
Muted or stale recordings do not produce transcript lines. This flag does not
change recognition, storage, or grounding behavior.
