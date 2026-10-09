# Nova development status

## Current module: 12.12A — Raspberry Pi deployment preparation

Added a separate Linux ARM64 profile, explicit provisioning scripts, local
foreground Ollama startup, metadata-only preflight and guarded assistant launcher.
Windows default executable paths and unset resource limits are preserved.
Linux terminal mute uses M + Enter and forces mute when console controls are lost.
The Pi profile starts muted, uses tiny.en / Llama 3.2 1B / the existing lessac
voice, bounds threads/context/queues, and disables passive extraction,
interruption and online tools initially. Model downloads require explicit
provisioning; no GPIO wiring or systemd auto-start was implemented.

See [Pi setup, compatibility matrix and hardware checklist](../deployment/raspberry-pi/README.md).
Preparation checks on Windows do not validate Linux ARM64 installation or Pi
audio/inference/resource capacity. Windows physical tests remain reported as
passed; multi-hour physical reliability remains **deferred, not completed**.

Verification on Windows:

- New deployment regression cases: **70** (isolated temporary fixtures, mocked
  Linux ownership/devices/network; no production memory writes).
- Focused deployment/model/mute/audio regressions: **182 passed in 4.55 seconds**.
- Six Bash scripts passed individual `bash -n` syntax checks; provisioning was
  not executed on Windows or Pi.
- Full regression suite: **1,194 passed in 89.43 seconds**. All 1,124 baseline
  tests are preserved.

### Configuration-independent pytest verification

A subsequent run with live experimental interruption enabled exposed five
configuration-dependent integration failures. Test collection previously loaded
the developer's runtime .env/exported settings. `tests/conftest.py` now selects
an empty, temporary test environment before configuration imports, removes
inherited Nova settings for the test process, and directs default SQLite storage
to a temporary `companion.db`. Individual tests still explicitly enable features
under test. Live .env files and application startup behavior are unchanged.

Four new fresh-process regressions cover inherited interruption, platform/resource
settings, online/credential settings, and the originally failing mute scenario.
Existing assertions are preserved. Focused voice/mute/interruption/isolation
checks: **77 passed**. Final full suite with both interruption flags deliberately
exported as enabled: **1,198 passed in 50.43 seconds**.

## Previous modules: 12.10 and 12.11

Module 12.10 adds bounded SQLite candidate retrieval and in-process concept
ranking for paraphrases, grounded historical event review and multi-topic recall.
Exact answers and confirmed-fact priority remain. No embedding model, automatic
download, semantic network access, cloud memory service or dependency was added.
Strict relation qualifiers prevent occupation from answering a work-address
question and preferences from answering unrelated activity questions. Recall
queries and selected-record reads use short lock waits; locked authoritative
facts do not fall back to potentially conflicting passive observations.

Module 12.11 adds optional Open-Meteo modeled current weather/daily forecasts and
NewsAPI headlines. `NOVA_ONLINE_TOOLS_ENABLED=false` is the default. Providers
must be explicitly configured; their fixed HTTPS endpoints reject redirects and
environment proxies. Only explicit/configured locations and configured news
topics leave Nova. Memory/history and credentials never enter provider response
prompts. Provider content bypasses Ollama, is sanitized, and is not saved as memory.
No audio architecture or local-only Ollama enforcement was changed.

Verification checkpoints:

- Baseline: **992 passing tests**.
- Module 12.10 focused memory regressions: **114 passed**.
- Module 12.10 complete regression checkpoint before online implementation:
  **1,024 passed in 88.94 seconds** (32 additional tests).
- Module 12.11 isolated provider-policy suite: **82 passed in 0.23 seconds**.
- Combined mocked voice workflows: **8 passed in 1.09 seconds**.
- Final focused memory, provider, assistant and voice regressions: **198 passed
  in 7.08 seconds**. These include further relation/lock/privacy hardening.
- Final complete regression suite after both modules: **1,124 passed in
  82.86 seconds**. All 992 baseline tests are preserved; 132 new cases cover
  semantic grounding, provider safety and combined voice flows.

Synthetic local retrieval benchmark on Windows: 100 queries over 303 temporary
SQLite records, median **3.409 ms**, p95 **6.585 ms**, maximum **9.551 ms**. These
are retrieval-only timings from a small synthetic database, not speech/model
latency, a large-archive profile or future Pi measurements.

See [SEMANTIC_MEMORY.md](SEMANTIC_MEMORY.md) for architecture and grounding limits,
and [ONLINE_TOOLS.md](ONLINE_TOOLS.md) for official provider contracts, setup,
configuration variables, voice examples, network/privacy policy and manual tests.

Files created in these modules:

- `src/offline_ai_companion/memory/hybrid_retriever.py`
- `src/offline_ai_companion/tools/online_requests.py`
- `src/offline_ai_companion/tools/online_tools.py`
- `tests/integration/test_hybrid_memory_retrieval.py`
- `tests/integration/test_semantic_online_voice.py`
- `tests/unit/test_online_tools.py`
- `docs/SEMANTIC_MEMORY.md`
- `docs/ONLINE_TOOLS.md`

Files modified in these modules:

- `src/offline_ai_companion/core/assistant.py`
- `src/offline_ai_companion/memory/passive_retriever.py`
- `src/offline_ai_companion/memory/passive_repository.py`
- `src/offline_ai_companion/memory/repository.py`
- `src/offline_ai_companion/router/query_router.py`
- `config/.env.example`
- `docs/DEVELOPMENT_STATUS.md`

Remaining limits: concept vocabulary limits unrestricted paraphrases; temporal
inference is conservative; passive speakers are unauthenticated. NewsAPI may
delay articles and its development plan is unsuitable for production use.
Forecasts are daily, not hourly. Live provider/key/quota testing and physical
weather/news playback tests remain unperformed. Previously reported basic Windows
audio and interruption validation passed. **Multi-hour physical reliability
testing remains deferred, not completed.** No Raspberry Pi deployment or later
module was started.

## Previous module: 12.9 — Long-running reliability and performance

Inspected and documented lifecycle findings before implementation. Added opt-in
numeric resource/health monitoring, fixed-size timing aggregates, missing-block
recovery, sample-count capture bounds, notification capacity, passive text limits,
worker self-stop safety and SQLite setup/rollback/close protection. Defaults remain
`NOVA_RUNTIME_DIAGNOSTICS=false` and `NOVA_RUNTIME_INTERVAL=30`.

The hardware-free soak uses real orchestration, VAD, workers and temporary SQLite
with generated samples and fake models. It passed 17 restart cycles in 61.34 seconds:
187 streams opened/closed, one Python thread before/after and zero owned audio
subprocess operations remaining. RSS increased about 0.57 MiB after the first cycle;
this short test does not prove multi-hour stability. The user reports all ten prior
physical interruption checks passed; new multi-hour physical validation is NOT RUN.

See [inspection, changes and results](MODULE_129_RELIABILITY.md),
[runtime/soak instructions](LONG_RUNNING_VALIDATION.md), and the
[numeric soak report](module-129-soak-results.json). Existing privacy, local-only
model access and committed data are preserved. No secure-erasure or power-loss
guarantee is claimed. Raspberry Pi deployment has not started.

Final verification: **992 tests passed in 79.14 seconds**, preserving all 951
baseline tests and adding 41 cases. Focused final verification passed 50 tests.
A reminder-metric compatibility regression found by the first full run was fixed
in the implementation; existing tests were preserved.

## Previous module: 12.8B — Experimental voice interruption

Half-duplex remains the default. `NOVA_EXPERIMENTAL_INTERRUPTION=true` enables
console S cancellation and cooperative response boundaries; the separate
`NOVA_SPOKEN_INTERRUPTION=true` enables an isolated exact wake+stop monitor.
Whisper/Piper owned children are reaped on cancellation and owned output streams
abort between short writes. No shared threads are killed. Active Ollama requests
use a configurable 30-second timeout without retries; cancellation suppresses
results but cannot abort server inference or immediately release a blocked request.

Stop/mute/shutdown preserve committed SQLite operations and accepted passive
queue draining. Interrupted reminder speech is not completed delivery: its claimed
record stays pending and is deferred 60 seconds atomically. State checks cover
listening, processing, speaking, interrupted, muted and shutting down. Stale stop
tokens, mute generations and processing-to-speaking clips are rejected.

No acoustic echo cancellation or general full-duplex conversation is implemented.
Stop monitoring alternates recording and local transcription, with recognition gaps.
It discards all other speech without dispatching to tools or memory. The user
reports all ten 12.8A physical checks passed; **12.8B physical checks are not run**.
The [new Windows checklist](WINDOWS_INTERRUPTION_VALIDATION.md) covers echo, long
responses, repeated stops, mute, reminders, devices and shutdown. Keep spoken
interruption experimental until those checks pass. Module 12.9 and Pi deployment
have not started.

Implementation design, configuration, modified-file list and verification details:
[MODULE_128B_INTERRUPTION.md](MODULE_128B_INTERRUPTION.md).

Final verification (2026-10-10): **951 passed in 70.42 seconds**, including all
885 baseline tests and 66 new interruption cases. Focused final tests: **66 passed
in 2.51 seconds**. New physical interruption validation remains NOT RUN.

## Previous module: 12.8A — Windows audio validation diagnostics

The following is the implementation-time report. The user subsequently reported
all ten physical Windows validation scenarios passed before Module 12.8B began.

Inspected capture/VAD, Whisper, wake/follow-up routing, Piper/playback, mute and
recovery. Added opt-in fixed-label stage diagnostics, device metadata/format checks,
optional device indices, counted overflow/underrun warnings and stream retirement.
Overflowed utterances are discarded, not transcribed incompletely. A half-duplex
guard cancels capture and waits for closure before playback, preserves the settling
interval and invalidates older recordings. Shutdown rejects stale submissions;
previously accepted work retains graceful-drain semantics.

Windows metadata preflight succeeded: 33 PortAudio entries, default input 1/output
4, supported 16 kHz mono input and checked 22.05 kHz mono output. Whisper/Piper
executable/model/config presence checks passed. **No physical capture, recognition
or playback was performed.** Device names and private paths are omitted.

Full verification: **885 tests passed in 110.25 seconds**, preserving all 837
baseline tests and adding 48 diagnostic/lifecycle cases. The final compatibility
run passed 62 tests in 2.89 seconds, including all 14 existing wake-dispatch tests.
A shutdown-guard compatibility regression for transcript-only injected instances
was fixed without modifying existing tests. Tests use isolated temporary storage,
synthetic samples and mocked hardware/model boundaries.
See [WINDOWS_AUDIO_VALIDATION.md](WINDOWS_AUDIO_VALIDATION.md) for reproducible
manual checks, expected event order and sanitized failure collection. Long acoustic
tails/loopback input, driver behavior and real recognition/playback still require
hands-on validation. Full duplex, user barge-in and Raspberry Pi deployment have
not started.

### Files changed in 12.8A

- `config/.env.example`
- `src/offline_ai_companion/config.py`
- `src/offline_ai_companion/audio/continuous_recorder.py`
- `src/offline_ai_companion/audio/player.py`
- `src/offline_ai_companion/audio/diagnostics.py` (new)
- `src/offline_ai_companion/audio/half_duplex.py` (new)
- `scripts/always_on_assistant.py`
- `scripts/audio_diagnostics.py` (new)
- `tests/unit/test_audio_diagnostics.py` (new)
- `tests/integration/test_audio_diagnostic_lifecycle.py` (new)
- `docs/WINDOWS_AUDIO_VALIDATION.md` (new)
- `docs/module-128a-device-report.json` (new, metadata only)
- `docs/DEVELOPMENT_STATUS.md`
- `docs/PRIVACY.md`

## Previous module: 12.7.5 — Task and reminder lifecycle management

Implemented deterministic task creation/review/completion/rename/deletion and
reminder creation/review/cancellation/deletion/snooze/reschedule. Review uses typed
IDs and three-result pages. Mutations require expiring RAM-only confirmations and
compare versioned rows under a SQLite transaction. Fact and memory confirmations
remain mutually exclusive with task/reminder changes. Passive observations never
become actionable tasks/reminders automatically.

Calendar reminders use configurable IANA `REMINDER_TIMEZONE` (default
`Asia/Kolkata`), strict date/time parsing, injected clocks, UTC persistence and
daylight-saving gap/fold rejection. Additive schema migration preserves records
and IDs. Atomic delivery claims with renewable leases prevent competing scheduler
notifications and user changes during active delivery. Crash recovery retains the
documented playback-versus-commit duplication limitation.

Verification: **837 tests passed in 106.83 seconds**, preserving all 742 baseline
tests and adding 95 lifecycle/voice regression cases. The broad focused run passed
244 tests in 32.07 seconds; the final dedicated lifecycle/voice run passed all
95 new cases in 7.71 seconds. Tests use isolated SQLite databases and mocked
microphone, STT and TTS boundaries. Physical playback is not verified.

See [TASKS_AND_REMINDERS.md](TASKS_AND_REMINDERS.md) for voice commands, timezone
assumptions, confirmation rules, delivery recovery and manual Windows checks.
Module 12.8A diagnostics are documented above; Raspberry Pi deployment has not started.

### Files changed in 12.7.5

- `config/.env.example`
- `pyproject.toml`
- `src/offline_ai_companion/config.py`
- `src/offline_ai_companion/core/assistant.py`
- `src/offline_ai_companion/memory/database.py`
- `src/offline_ai_companion/memory/models.py`
- `src/offline_ai_companion/memory/repository.py`
- `src/offline_ai_companion/router/query_router.py`
- `src/offline_ai_companion/scheduler/reminder_scheduler.py`
- `src/offline_ai_companion/scheduler/reminder_time.py` (new)
- `src/offline_ai_companion/tools/memory_tools.py`
- `src/offline_ai_companion/tools/lifecycle.py` (new)
- `tests/unit/test_lifecycle_management.py` (new)
- `tests/integration/test_lifecycle_voice.py` (new)
- `docs/TASKS_AND_REMINDERS.md` (new)
- `docs/PRIVACY.md`
- `docs/DEVELOPMENT_STATUS.md`

## Previous module: 12.7.4 — Memory review, correction and deletion

Implemented deterministic management of confirmed facts and passive observations.
The 12.7.3 baseline contained 687 passing tests. Full verification for 12.7.4:
**742 passed in 79.27 seconds**, including 55 new regression/integration cases.
The final dedicated memory-management run passed all 55 cases in 5.00 seconds.

- Review: confirmed facts, passive observations and preferences, with three-result
  pages, typed stable identifiers, provenance, bounded previews and credential
  filtering. Expired observations are excluded from review and ordinary recall.
- Deletion: explicit passive IDs, confirmed fact keys and uniquely resolved
  statements/labels. Ambiguous observations require a typed target. Numeric memory
  IDs belong only to the passive table; other table IDs can overlap.
- Correction: explicit fact/favorite updates and resolved preference replacements
  ask for confirmation. One confirmed value per key takes priority on recall.
  Historical passive content, evidence and timestamps are never rewritten.
- Bulk scopes: all confirmed facts, all passive observations, or both; confirmation
  names the scope and exclusions. Notes, tasks, reminders and conversation history
  remain outside these scopes. Explicit bulk deletion includes expired observations.
- Confirmation: operations are mutually exclusive with ordinary fact proposals,
  expire after 120 seconds by default and are not persisted. Exact replies are
  required; cancellation, unrelated questions and repeated commands cannot execute
  stale operations. Ordinary fact confirmations retain their existing reply
  vocabulary and now have an expiry deadline.
- Atomicity: row snapshots are checked under `BEGIN IMMEDIATE` before changes.
  Changed records cancel the request; failures roll back multi-category changes.
  Repository CRUD methods accept an optional shared transaction connection.

See [PRIVACY.md](PRIVACY.md#memory-review-correction-and-deletion-module-1274)
for exact commands, voice confirmation instructions, retention and deletion limits.

## Verification scope

Tests use temporary SQLite databases and mocked audio/model boundaries. They
cover read-only review, filtering, pagination, overlapping table IDs, targeted and
bulk deletion, corrections, confirmed-fact priority, ambiguities, confirmation
expiry/cancellation/repetition/restart, privacy, expired observations, SQLite
persistence, rollback and background-worker races. Voice integration exercises
wake-word management commands, TTS responses and recall after deletion.

Physical Windows microphone/speaker behavior remains unverified by these mocked
tests. These physical validation limits also apply to Module 12.7.5.

## Modified files

- `src/offline_ai_companion/memory/management.py` (new command/confirmation service)
- `src/offline_ai_companion/core/assistant.py`
- `src/offline_ai_companion/router/query_router.py`
- `src/offline_ai_companion/memory/confirmation.py`
- `src/offline_ai_companion/memory/repository.py`
- `src/offline_ai_companion/memory/passive_repository.py`
- `src/offline_ai_companion/memory/passive_retriever.py`
- `tests/unit/test_memory_management.py` (new)
- `tests/integration/test_memory_management_voice.py` (new)
- `docs/PRIVACY.md`
- `docs/DEVELOPMENT_STATUS.md` (new)

## Remaining limits

Matching uses supported deterministic phrases, not unrestricted semantic deletion.
Unknown or multiple topics require explicit clarification. Review previews are
bounded; use individual typed-ID review for more evidence. Page contents can shift
when background records arrive, while record IDs remain stable. Large reviews and
bulk snapshots still scan stored memory; they avoid a vector database but have not
been stress-profiled against very large archives.

New and previously accepted speech may add observations after deletion; this is
not a collection opt-out. Speaker authentication is not provided. Explicit fact
deletion preserves historical observations and notes, so older information can
still appear if it remains in those separate categories. SQLite deletion cannot
guarantee secure erasure of pages, WAL/journals, backups or storage media.
