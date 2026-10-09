# Module 12.8B — proposed interruption architecture

This design was recorded before implementation. Half-duplex remains the default.
The user reports all ten 12.8A Windows physical scenarios passed. That establishes
the prior baseline; the new experimental mode still requires physical validation.

## Ownership and boundaries

The main voice thread continues to own normal capture, command dispatch and SQLite
operations. A response token has a latched cancellation event and identity. Stop,
mute and shutdown cancel that token. A cancelled/stale token cannot complete audio
or cancel a later response. Committed facts, notes, tasks and reminders are never
rolled back when output is interrupted. Existing accepted passive work drains.

`NOVA_EXPERIMENTAL_INTERRUPTION=false` preserves existing half-duplex behavior.
When true, S in the Windows console interrupts the current operation. Cooperative
checks surround model calls and side-effect admission. Owned Whisper/Piper child
processes can be terminated and reaped on cancellation; no shared thread is killed.
Playback writes short blocks through one owned output stream and aborts that stream
on cancellation. The main loop then resumes listening after cleanup/settling.

The synchronous Ollama request cannot safely be forcibly stopped. Experimental
active model calls use a configurable bounded timeout with no retry; stop suppresses
their result and prevents subsequent output. A fresh voice command waits for that
call to return. Server inference may continue; no shared client/worker is closed.

## Optional spoken stop monitor

`NOVA_SPOKEN_INTERRUPTION=false` is a separate opt-in, requiring experimental mode.
One bounded monitor runs only during an active command or announcement. It owns a
separate input stream while the normal capture loop is paused, uses VAD, transient
WAVs and local Whisper, and accepts only an exact wake-prefixed stop command.
All other monitor audio is discarded. No monitor transcript reaches Assistant,
passive extraction, SQLite or conversation history. Overflowed clips are rejected.
Session identity, mute generation and cancellation are checked before acceptance.
The monitor rejects spoken stop when the current Piper text itself contains the
stop phrase. That is a conservative text guard, not acoustic echo cancellation.

Use headphones to validate first. Echo, recognition hallucinations and delayed
device buffers can still trigger false stops. Speaker-mode spoken interruption is
experimental, not a claim of reliable full duplex or general barge-in. No new
commands are executed from monitoring audio, including commands after “stop”.

## State and reminders

Experimental transitions cover listening, processing, speaking, interrupted, muted
and shutting down, plus idle cleanup. Output/capture ownership remains serialized
except for the explicitly authorized stop-only monitor. Interrupted speech raises
a distinct cancellation result, never a successful delivery acknowledgment.
An interrupted reminder remains pending and is deferred by 60 seconds under its
existing delivery claim, preventing immediate re-announcement. Normal failure and
shutdown claim recovery preserve their existing behavior. Delivery is still not
exactly-once across a playback/SQLite-commit crash.

## Verification plan

Temporary SQLite and fake audio/model components cover stop during playback/TTS/
model boundaries, stale tokens/audio, repeated stop, mute/shutdown, feedback
rejection, reminders, persistence, recovery and disabled-mode compatibility.
Physical Windows checks will separately cover conversation, long playback, exact
spoken stop, echo, repeated wakes, mute, reminders, devices and shutdown. No new
physical pass will be claimed from automated tests.

## Implemented scope and configuration

The described console cancellation and optional exact spoken stop monitor are
implemented. There is one main voice dispatcher, one optional monitor and one
owned output stream. Response cancellation does not stop the passive worker.
The monitor closes before normal capture resumes; WAVs are removed after each
clip. Monitor capture is sequential with its own Whisper transcription, so there
are recognition blind intervals rather than uninterrupted full-duplex capture.
Spoken monitoring begins after the main recording's transcription, during active
processing or an announcement. S can also cancel that initial transcription.

`NOVA_EXPERIMENTAL_INTERRUPTION=false`, `NOVA_SPOKEN_INTERRUPTION=false`,
`NOVA_INTERRUPT_LLM_TIMEOUT=30`, `NOVA_INTERRUPT_STT_TIMEOUT=5` are documented in
`config/.env.example`. Valid timeout values are finite, positive seconds up to 120.
Default mode retains existing device call interfaces and playback exclusion.

Cancellation before command admission prevents processing; once an admitted
operation is executing it may finish a commit. No SQLite rollback is attempted
because spoken acknowledgment was interrupted. Model cancellation propagates as
interruption, without an ordinary model-error answer. Generated conversation text
can remain if cancellation happens after generation and history insertion.

## Files changed for this module

- `config/.env.example`
- `scripts/always_on_assistant.py`
- `src/offline_ai_companion/config.py`
- `src/offline_ai_companion/audio/cancellable_subprocess.py` (new)
- `src/offline_ai_companion/audio/stop_monitor.py` (new)
- `src/offline_ai_companion/audio/player.py`
- `src/offline_ai_companion/audio/diagnostics.py`
- `src/offline_ai_companion/core/cancellation.py` (new)
- `src/offline_ai_companion/core/assistant.py`
- `src/offline_ai_companion/core/privacy.py`
- `src/offline_ai_companion/core/state.py`
- `src/offline_ai_companion/llm/ollama.py`
- `src/offline_ai_companion/memory/repository.py`
- `src/offline_ai_companion/scheduler/reminder_scheduler.py`
- `src/offline_ai_companion/stt/whisper.py`
- `src/offline_ai_companion/tts/piper.py`
- `tests/unit/test_response_interruption.py` (new)
- `tests/integration/test_experimental_interruption.py` (new)
- `docs/MODULE_128B_INTERRUPTION.md` (new)
- `docs/WINDOWS_INTERRUPTION_VALIDATION.md` (new)
- `docs/PRIVACY.md`
- `docs/DEVELOPMENT_STATUS.md`

Preexisting workspace changes from earlier modules were preserved.
Physical checks are in [WINDOWS_INTERRUPTION_VALIDATION.md](WINDOWS_INTERRUPTION_VALIDATION.md).

## Regression coverage

The new unit/integration cases cover cancellation latching and stale tokens,
legal/illegal state transitions, exact stop matching and quoted-output rejection,
bounded monitor capture, monitor restart and sanitized device failures, stale/muted
and cross-phase clips, owned stream abort, child-process cancellation/timeout/reaping,
Whisper/Piper boundaries, partial WAV cleanup and user-file preservation, Ollama
request/result/error boundaries, valid configuration requirements, console opt-in,
repeated stops and new commands, committed task consistency, reminder failure
acknowledgment/deferral/retry and claim fencing, default fallback, mute/unmute,
shutdown/accepted passive draining, and the shutdown/mute hotkey race.

Temporary SQLite and owned temporary directories are used throughout. One helper
test cancels a real owned Python child process; no physical audio is exercised.

## Final verification — 2026-10-10

- Existing baseline after initial implementation: **885 passed**.
- Focused final interruption regressions: **66 passed in 2.51 seconds**.
- Complete final suite: **951 passed in 70.42 seconds**, preserving all 885
  baseline tests and adding 66 cases. No existing tests were rewritten.
- New physical Windows interruption checklist: **NOT RUN**.

Stopped after Module 12.8B verification. Module 12.9 and Raspberry Pi deployment
were not started. The feature remains opt-in; reliable speaker-mode barge-in,
acoustic echo cancellation and hard interruption latency are not claimed.
