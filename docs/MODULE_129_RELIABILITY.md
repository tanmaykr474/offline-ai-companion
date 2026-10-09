# Module 12.9 — lifecycle inspection and reliability plan

Inspection recorded before implementation, 2026-10-10. Baseline: 951 passing
automated tests. The user reports ten Windows interruption checks passed; those
basic checks do not establish multi-hour stability.

## Findings

- The main voice loop owns ordinary capture and dispatch. Playback exclusion,
  cancellation tokens, mute generations and temporary WAV ownership are present.
  Stop monitoring is experimental and joins before ordinary capture resumes.
- Audio blocks use bounded queues (100 normal, 10 stop-monitor), bounded pre-roll
  and a 15/3-second utterance limit. Overflow invalidates the entire clip. A stream
  which stops producing callbacks can nevertheless wait forever in queue.get;
  ordinary silence produces blocks and must remain valid indefinitely.
- Whisper and Piper have 120-second timeouts. Experimental children are terminated
  and reaped on cancellation. Default subprocess.run also kills/waits on timeout.
  Device open/write/close calls and OS process termination are not hard real-time.
- Ollama is loopback-only, with finite per-operation timeouts and bounded retries.
  Cancellation suppresses results but cannot abort server inference. Passive model
  extraction has its separate 30-second/no-retry configuration.
- Passive work has a bounded queue, nonblocking admission, exception isolation and
  accepted-work draining. Queue length alone does not bound arbitrary injected text
  size. A failed extraction is reported and the worker proceeds; it is not a durable
  job queue and must not blindly replay possibly partially committed work.
- Reminder notifications use an unbounded queue. The normal scheduler sends one at
  a time and waits for acknowledgment, but concurrent external callers can grow it.
  Delivery uses SQLite claims, renewal and bounded completion retries. A crash
  between audible playback and completion can still cause repeat delivery.
- SQLite connections normally commit/rollback/close and wait up to ten seconds for
  locks. Connection setup (row factory/PRAGMA) precedes the cleanup try block and
  can leak a connection on setup failure. No automatic transaction replay should
  be added: commands may have side effects. Schema/data retention stay unchanged.
- Scheduler due queries materialize the current due backlog. Very large persistent
  archives/backlogs can increase transient query memory; these short tests do not
  establish performance for arbitrarily large archives.
- Conversation history is count-bounded. Stored facts/tasks/reminders/observations
  intentionally persist; database growth is user data, not evidence of a RAM leak.
- Existing stage timings omit resource usage, queue pressure, failure counters and
  reminder lateness. Diagnostics must use fixed labels/numbers, never SQL, text,
  prompts, audio, record contents, exception messages or process command lines.

## Planned changes

Add opt-in constant-space counters/timing aggregates and periodic native process
resource samples, queue depth/worker health, owned audio subprocess activity,
SQLite failures, recovery attempts and reminder delay. Keep diagnostics disabled
by default. Add a missing-block watchdog, bounded notification admission and a
passive text-size limit. Repair SQLite cleanup and expose a bounded busy timeout
for deterministic tests without retries or transaction replay.

Provide an isolated synthetic soak runner using real orchestration, workers and
SQLite with fake devices/models. It must bound its report/log accumulation, exercise
faults and restarts, assert invariants, and support iterations or elapsed duration.
Test rollback after process exit, concurrency, locks, subprocess cleanup, failures,
backpressure and existing interruption boundaries. Document what shorter runs can
establish and leave multi-hour physical validation explicitly unverified.

## Implemented changes

Added `core/runtime_metrics.py` with opt-in bounded aggregates and native resource
sampling. Hooks cover existing timings, capture/playback, audio subprocess helpers,
SQLite, passive work, recovery and reminder delivery. The runtime monitor is scoped
to the voice loop, samples fixed numeric health fields, and tolerates startup or
sampling failures. Windows resource API setup is cached rather than recreated per
sample. Defaults are `NOVA_RUNTIME_DIAGNOSTICS=false`, `NOVA_RUNTIME_INTERVAL=30`.

Added a missing-block watchdog and a sample-count cap to capture, explicit queued+
active notification capacity with balanced task accounting, passive admission size
limits, and safe self-stop handling for the passive worker. SQLite setup now shares
the rollback/close scope, including interruptions; lock waiting remains bounded
without transaction replay. No schema, persistent-data retention or network-policy
changes were made.

The synthetic soak runner and durability tests exercise normal operation, expected
faults and restart invariants with temporary data. Instructions, metric definitions,
queue policies and physical testing limits are in
[LONG_RUNNING_VALIDATION.md](LONG_RUNNING_VALIDATION.md).

## Files changed

- `src/offline_ai_companion/core/runtime_metrics.py` (new)
- `src/offline_ai_companion/core/performance.py`
- `src/offline_ai_companion/config.py`
- `src/offline_ai_companion/audio/continuous_recorder.py`
- `src/offline_ai_companion/audio/cancellable_subprocess.py`
- `src/offline_ai_companion/audio/diagnostics.py`
- `src/offline_ai_companion/audio/recovery.py`
- `src/offline_ai_companion/stt/whisper.py`
- `src/offline_ai_companion/tts/piper.py`
- `src/offline_ai_companion/memory/database.py`
- `src/offline_ai_companion/memory/passive_worker.py`
- `src/offline_ai_companion/scheduler/reminder_notifications.py`
- `src/offline_ai_companion/scheduler/reminder_scheduler.py`
- `scripts/always_on_assistant.py`
- `scripts/soak_runtime.py` (new)
- `config/.env.example`
- `tests/unit/test_runtime_reliability.py` (new)
- `tests/integration/test_runtime_durability.py` (new)
- `docs/MODULE_129_RELIABILITY.md` (new)
- `docs/LONG_RUNNING_VALIDATION.md` (new)
- `docs/module-129-soak-results.json` (generated numeric measurements)
- `docs/module-129-soak-smoke.json` (initial smoke measurements)
- `docs/PRIVACY.md`
- `docs/DEVELOPMENT_STATUS.md`

Preexisting work from earlier modules was preserved.

## Executed synthetic measurements

The [numeric report](module-129-soak-results.json) completed **17 shutdown/restart
cycles in 61.34 seconds**, with **187 input streams opened and 187 closed**.
Python thread count returned from 1 to 1; owned audio subprocess activity ended
at zero. RSS was 58.34 MiB initially, 59.80 MiB after the first cycle and 60.38 MiB
at completion (about 0.57 MiB increase after the first cycle). Sampled peak was
60.43 MiB; parent-process CPU averaged 14.14% using one core as 100%.

The 17 passive failures, 17 device recovery attempts and model timeout errors
were injected intentionally. All restart/storage/cleanup invariants passed.
Snapshots are taken between cycles, so sampled peaks can miss within-cycle peaks.
Stage latency data is in the JSON report; fake model/device durations are not
measurements of real Whisper/Ollama/Piper performance.

This one-minute result establishes exercised invariants, not absence of a leak
over hours. The additional sample cap and self-stop guards were verified afterward
by targeted regression tests and the final suite. Multi-hour physical runs,
power-loss durability, secure erasure and hard native-driver deadlines are not
claimed. No Raspberry Pi deployment was performed.

## Verification notes

Focused final recovery/reliability tests: **50 passed in 10.67 seconds**. This
includes the new cases and the existing scheduler recovery tests. The first full
run exposed four compatibility failures: optional reminder-lateness calculation
assumed injected reminder objects had timestamps. The metric now runs only when
enabled and when usable timestamp metadata exists; metric failures cannot prevent
delivery. Existing tests were not changed to accommodate the regression.

Final complete verification: **992 passed in 79.14 seconds**, preserving all 951
baseline tests and adding 41 regression/integration cases. Tests cover native
numeric sampling, bounded aggregates, optional-metadata/failing-monitor isolation,
queue and sample budgets, silence versus stalled input, worker failure/draining,
self-stop, subprocess timeout/reaping, paced scheduler recovery, concurrent SQLite
access, lock timeout/recovery, graceful restart and abrupt-process rollback.

Implementation and automated verification are complete for Module 12.9. The
multi-hour physical checklist remains unexecuted; subsequent modules were not started.
