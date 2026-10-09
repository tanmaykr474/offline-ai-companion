# Long-running reliability and performance — Module 12.9

## Scope and configuration

Runtime diagnostics are disabled by default. Enable fixed numeric snapshots:

```powershell
$env:NOVA_RUNTIME_DIAGNOSTICS = "true"
$env:NOVA_RUNTIME_INTERVAL = "30"
python .\scripts\always_on_assistant.py
```

The interval accepts finite values from 0.1 to 3600 seconds; 30 seconds is the
recommended normal-use setting. Disable with `NOVA_RUNTIME_DIAGNOSTICS=false`.
No additional dependency, external service or telemetry destination is required.
Snapshots go to the `nova.runtime` console logger. If redirecting logs to disk,
use rotation/size limits; the application does not retain snapshot history.

Metrics include current Python-process RSS, process CPU percent, Python thread
count, in-flight owned audio subprocess operations, audio/stop-monitor/passive/
notification queue depths, passive processing age, worker/scheduler liveness,
overflow/rejection/failure/recovery counters and stage count/total/max latency.
Reminder measurements separate delivery duration from lateness since its due time.
`errors` in timing aggregates means any non-success, including deliberate interruption.
Absent counters mean zero observations, not an unmeasured failure estimate.

CPU percent uses one logical core as 100% and can exceed 100%. RSS and CPU measure
the Nova Python process, not external Ollama or Whisper/Piper process resources.
Thread count includes Python-managed threads, not every native library thread.
Owned subprocess activity includes spawn/cleanup time and excludes external Ollama.
Unsupported resource samples are null, not fabricated zero values. Resource sampling
failure does not prevent application work. Labels are fixed and values numeric;
no transcripts, prompts, answers, SQL, memory content, credentials, raw audio,
process command lines or exception messages are collected.

## Hardware-free soak

```powershell
# Short CI-style check (about eight seconds on the development machine).
python .\scripts\soak_runtime.py --cycles 2 --report soak-smoke.json

# One hour with synthetic devices/models and an isolated temporary SQLite database.
python .\scripts\soak_runtime.py --duration-seconds 3600 --report soak-hour.json

# Fixed number of complete shutdown/restart cycles.
python .\scripts\soak_runtime.py --cycles 1000 --report soak-cycles.json
```

The runner executes at least one cycle and finishes the current cycle after a time
budget expires. If both limits are supplied, the first reached ends the run after
that cycle. Its report retains at most 120 recent snapshots and fixed-size aggregates.
Ordinary synthetic console output is discarded, not accumulated in a string buffer.
Only the report persists; the temporary database and WAV directory are removed.
Deletion is normal filesystem cleanup, **not secure erasure**.

Each cycle exercises real capture/VAD with generated samples, idle silence, wake and
follow-up routing, failed then successful passive work, duplicate-safe retrieval,
task creation/listing, reminder creation/delivery, mute/unmute, cancelled playback,
device failure/recovery, Ollama-adapter timeout/recovery and graceful shutdown.
The same temporary SQLite file is reopened between cycles. Assertions check committed
facts, bounded synthetic row counts, task isolation from mute, correct reminder
completion, stream/thread cleanup, balanced queue completion, removed WAVs and
SQLite integrity. Synthetic tasks/reminders are removed between cycles to keep the
test workload bounded. Real user databases are never selected by this runner.

STT/TTS/player and the HTTP transport are synthetic. Their latency numbers validate
instrumentation and orchestration, **not actual Whisper/Ollama/Piper throughput**.
Subprocess timeout/reaping and abrupt SQLite process exit are separate automated
tests, not simulated physical power loss. To diagnose a failed invariant locally,
run `python -c "from scripts.soak_runtime import run_soak; run_soak(2)"`; use only
the synthetic test profile and review the traceback before sharing it.

## Physical extended-run checklist

The ten prior interruption checks were reported passed by the user. New multi-hour
physical reliability testing is **NOT RUN**. Begin with half-duplex, then repeat
separately with the existing experimental interruption settings if desired.

1. Run 30 minutes, then 2–8 hours with runtime snapshots enabled. Use nonsensitive
   sample speech and review RSS after model/cache warmup, CPU, queue depths and
   thread/subprocess counts. Compare after repeated idle periods, not just peaks.
2. Leave the microphone in genuine silence for several minutes: it must continue
   delivering silent blocks without a stall warning. Wake and recall afterward.
3. Mix passive speech, recall, tasks and due reminders. Check that queue pressure
   yields explicit rejections, accepted work drains, and stored rows stay correct.
4. Disconnect/reconnect input/output. Missing input blocks should trigger a safe
   recovery failure after about five seconds; recovery retries wait between attempts.
5. Stop/restart local Ollama, trigger long responses, and test mute/interruption.
   Verify recovery, no stale response dispatch, and no growth in owned child count.
6. Shut down during capture, processing and playback. Check that accepted passive
   work finishes, temporary owned files disappear and the next startup opens devices.
7. Review counters and record any failures with stage names, counts and durations
   only. Do not share production databases, audio, transcripts or credentials.

## Policies and limits

- Audio queues remain 100 blocks normally and 10 for the stop monitor. Overflow
  invalidates the clip. Sample retention is also capped independently of wall time,
  so an unexpectedly fast backend cannot grow an utterance indefinitely.
- Passive queues reject new work when full and reject text over 16,000 characters
  before admission. Accepted work drains; a failed extraction is reported and is
  not automatically replayed, because partial commits could otherwise duplicate data.
- Notifications allow ten total queued plus active requests. Excess requests fail
  explicitly; committed reminders remain in SQLite for later delivery.
- SQLite retains its ten-second default busy wait (constructor configurable 0–60
  seconds), rollback and per-operation connection closure. Failed transactions are
  not blindly replayed. No journal-mode or retention migration was introduced.
- Scheduler polling remains paced and completion retries bounded. Reminder audio
  is not exactly-once across a crash between playback and its completion commit.
- Native driver calls, stuck third-party code and server inference cannot be
  forcibly recovered safely by killing shared threads. Passive busy age and liveness
  expose stalls; accepted-work draining can wait if a dependency never returns.
- Existing mute, local-only Ollama, grounding and privacy rules remain in force.
  There is still no acoustic echo cancellation or claim of hardware-enforced mute.
- SQLite rollback/integrity tests do not prove resistance to power loss, disk failure,
  or secure deletion from journals, backups, filesystems or storage media.
