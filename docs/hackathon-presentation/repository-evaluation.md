# Nova repository evaluation

Audit date: 10 October 2026. Scope: first-party Python source, tests, configuration examples,
deployment scripts, service templates and documentation. The inventory records hashes,
line counts and Python symbols for reproducibility. Private `.env`, personal SQLite
records and recordings were deliberately excluded. Bundled binaries/model assets were
inventoried by role and presence, not reverse-engineered or treated as proof of execution.

## Evaluation position

Nova is a substantial local voice-assistant prototype with persistent personal memory,
deterministic task/reminder tools, guarded passive observations and privacy controls.
Its strongest claim is integration and evidence-aware memory on a local device.
There is no evidence of a newly trained foundation model or novel acoustic wake engine.
Raspberry Pi 5 is the documented deployment target, not a demonstrated working device
in this audit. Do not equate passing mocked tests with hardware readiness.

## Implemented, partial and future capabilities

Package-relative paths below are under `src/offline_ai_companion/`, except explicit paths.

| Capability | Status | Evidence | Qualification |
| --- | --- | --- | --- |
| Continuous speech capture | Implemented | `audio/continuous_recorder.py` | Repeated utterance capture, not uninterrupted recording during inference/playback. |
| VAD | Implemented | `audio/vad.py` | RMS energy threshold, not a neural VAD. |
| Whisper STT | Implemented | `stt/whisper.py` | Local whisper.cpp executable and pre-provisioned model. |
| Nova wake activation | Implemented | `core/wake_detector.py; core/activation_controller.py` | Transcript-prefix matching after STT, one 8-second follow-up after wake-only speech. |
| Local Llama chat | Implemented | `llm/ollama.py; llm/local_endpoint.py` | Llama 3.2 1B default, non-streaming loopback HTTP, not a bundled trained model. |
| SQLite facts, notes, tasks, reminders | Implemented | `memory/database.py; memory/repository.py; tools/memory_tools.py` | Plaintext local persistence, transactional operations. |
| Passive memory | Implemented / opt-in | `memory/passive_worker.py; memory/passive_processor.py` | Bounded asynchronous queue and grounded observations. Disabled by default. |
| Semantic recall | Implemented / limited | `memory/hybrid_retriever.py` | Small concept lexicon and cosine ranking. No embeddings or unrestricted semantic search. |
| Review, correction, deletion | Implemented | `memory/management.py; tools/lifecycle.py` | Scoped confirmations, typed IDs, transaction rechecks. No speaker authentication. |
| Reminder notifications | Implemented | `scheduler/reminder_scheduler.py; scheduler/reminder_notifications.py` | Leases, acknowledgment, retries. Crash window can duplicate audible delivery. |
| Piper TTS and playback | Implemented | `tts/piper.py; audio/player.py` | Local synthesis and sounddevice output. Normal capture pauses for playback. |
| Software mute and privacy gates | Implemented | `core/privacy.py; core/privacy_policy.py; audio/temporary.py` | Generation guards, secret heuristics, owned WAV cleanup. No encryption/secure erasure. |
| RGB LED and physical switch | Implemented / hardware unverified | `core/hardware.py` | gpiozero/LGPIOFactory backend, mock/no-op backends. GPIO switch is a software permission input. |
| Pi 5 Linux ARM64 and systemd | Implemented preparation / target unverified | `core/pi_deployment.py; core/systemd_units.py; deployment/raspberry-pi/` | Provisioning, guarded launch, non-root service templates. No proven physical Pi run. |
| Weather and news | Implemented / opt-in / live unverified | `tools/online_tools.py; tools/online_requests.py` | Open-Meteo and NewsAPI only. Internet and provider setup required. |
| Spoken interruption | Partial / experimental | `audio/stop_monitor.py; core/cancellation.py` | Exact wake+stop monitor, recognition gaps, no AEC or general full duplex. |
| Packaged voice entry point | Partial | `main.py; pyproject.toml` | Installed CLI prints startup text. Voice loop lives in scripts/always_on_assistant.py. |
| Multi-hour reliability | Deferred validation | `docs/LONG_RUNNING_VALIDATION.md` | Short synthetic soak exists. Multi-hour physical soak remains deferred. |
| Encryption, voice identity, electrical mic cutoff | Future improvement / absent | `No corresponding implementation found` | Do not present these as existing capabilities. |
| Cloud sync, mobile app, unrestricted agents | Absent | `No corresponding implementation found` | No arbitrary shell/IoT/calendar/email tool execution layer found. |

## Actual architecture

### Runtime and entry points

`scripts/always_on_assistant.py` constructs recorder, player, STT, Assistant, Piper,
activation controller, privacy gate, optional passive worker and reminder scheduler.
Its main path delegates to `core/service_runtime.py` for console/GPIO controls and
SIGTERM handling. `main.py` only prints startup messages, despite the packaged
`offline-ai-companion` entry point. Use the script or guarded Pi launcher for a demo.

### Audio ingestion and voice activation

The recorder opens sounddevice/PortAudio mono float32 capture at 16 kHz in 100 ms
blocks. The RMS threshold defaults to 0.018, adjustable through `VAD_THRESHOLD`.
Defaults include 0.7 seconds of pre-roll, 0.2 seconds of consecutive speech to start,
1 second of silence to finish and a 15-second utterance maximum with a sample-count
bound. A bounded queue avoids unlimited audio accumulation. Dropped blocks or input
overflow discard the utterance. Five seconds without blocks raises a recoverable error.

Utterances become PCM16 WAVs in an owned session directory. WhisperSTT invokes a local
whisper.cpp CLI with the local tiny.en model by platform default and an English Nova
prompt. It validates files and bounds subprocess lifetime. Caption/invalid-transcript
filters run before dispatch. WakeDetector matches `Nova` or `hey Nova` at the beginning
of the transcript using regex boundaries. STT runs BEFORE wake filtering. Nova therefore
transcribes VAD-triggered speech even with passive storage disabled. This is not a low
power acoustic keyword detector.

A wake+command utterance routes immediately. A wake-only utterance opens an eight-second
window for one subsequent utterance, using timezone-aware capture timestamps, then
resets. Other speech never receives an active spoken answer. If passive memory is
enabled, eligible transcripts enter its bounded worker queue, otherwise they are dropped.
Always-on means a repeating listening loop while available: the normal path serially
records, transcribes, processes and speaks. It cannot capture every utterance during
ordinary processing or output. Half-duplex playback invalidates old recordings and
waits for capture closure, with a 0.3-second acoustic settling delay.

### Routing, local model and memory

Assistant first enforces credential policy and pending management/confirmation workflows.
Grounded exact/hybrid recall can answer without model generation. QueryRouter classifies
supported deterministic tools and general chat. Personal fact parsing proposes changes
and typically asks for confirmation. The legacy name update, explicit note/task creation
and reminder creation are direct writes, so “every write requires confirmation” is false.
LLM-assisted fact extraction creates proposals rather than trusting arbitrary output.

OllamaLLM posts to `/api/generate` using loopback-only HTTP(S), default model
`llama3.2:1b`, `stream=false`, temperature 0.4 and 160 predicted tokens. It validates
response format and limits retries (normally one retry, 120-second timeout). Runtime
policy rejects remote endpoints, redirects and environment proxies. In experimental
interruption mode, active requests use a 30-second timeout and zero retries. Cancellation
can suppress results but cannot guarantee that Ollama's server-side inference stops.

SQLite tables hold facts, notes, tasks, reminders and passive memories. Passive records
carry category, subject, content, evidence, capture time, optional event time and unique
fingerprint. Connections enable foreign keys, commit on success, roll back on failure
and close. Lifecycle migrations add revision and delivery-lease fields without resetting
IDs. Conversation history is RAM-only, bounded to ten turns and 4,000 context characters.
The constructed general-chat memory context includes all confirmed facts and capped
notes/tasks/reminders/passive rows, so large confirmed-fact sets can exceed a small model
context. This is a remaining scaling risk, not an implemented full token-budget manager.

Passive extraction first uses supported deterministic assertion patterns, otherwise local
LLM JSON candidates. Validation checks verbatim evidence, assertion/negation, supported
subject/category/content and grounded times before saving. Inputs above 1,500 characters
are rejected by the processor, with at most five items of up to 300 content characters.
The worker is asynchronous and non-daemon, rejects full queues and drains accepted work
on shutdown. Optional collection defaults OFF. Observations belong to an unidentified
speaker, never automatically to the owner. They never become actionable tasks/reminders.

Hybrid recall uses exact relations first and a small synonym/concept lexicon plus sparse
cosine ranking. It examines at most 32 of 33 fetched candidates, returns at most three
ranked observations, and uses short SQLite lock/progress budgets. Confirmed facts take
priority. Evidence and selected-record rechecks prevent similarity alone from establishing
truth. There is no embedding/vector database, arbitrary semantic reasoning, speaker
diarization or authentication. Unknown concepts and date relations have conservative limits.

### Tools and scheduling

Local tools add/review notes, tasks and reminders, review/correct/delete facts/passive
records and complete/rename/delete tasks or cancel/snooze/reschedule reminders. Management
uses typed IDs, expiring RAM-only confirmations (120 seconds by default), transaction
rechecks and revisions to resist concurrent changes. Creation has the direct-write
exceptions noted above. Reminder date parsing uses an IANA timezone, defaults to
Asia/Kolkata, persists UTC and rejects unsupported/ambiguous or past calendar times.

The scheduler polls every second by default, atomically claims due rows with renewable
leases and requests playback through the main loop. Notifications interrupt capture.
Successful playback acknowledgment precedes completion persistence. Playback or commit
failure leaves recovery work, and interruption defers a reminder by 60 seconds. A crash
after audible playback and before durable completion can cause repeat playback: delivery
is not exactly once. Reminder speech can still occur while microphone input is muted.

Optional weather/news intents use fixed HTTPS Open-Meteo geocoding/forecast and NewsAPI
endpoints. Global enablement defaults false. Only explicit/configured locations and
configured news topics go to providers, with the NewsAPI key for authentication.
Memory/history do not enter provider requests. Sanitized provider answers bypass Ollama
and persistent memory. Weather is modeled current/daily information, not a local sensor
or offline forecast. These are the only external application integrations found.

### Output, hardware and operating system

PiperTTS sends text to a local executable using an argument list and stdin, producing a
WAV from `en_US-lessac-medium.onnx` by default. soundfile/sounddevice perform playback.
Experimental playback checks cancellation between 20 ms writes. The normal path has
no acoustic echo cancellation or full duplex. The optional exact wake+stop monitor
alternates recording/STT and discards other speech, leaving recognition gaps.

The GPIO module explicitly uses local gpiozero DigitalInput/OutputDevice with LGPIOFactory,
plus pure-Python mock and fail-closed no-op backends. Defaults are BCM17 red, BCM27 green,
BCM22 blue and BCM23 switch, chip 0, active-high LED and muted-high switch. Red means muted,
green listening, blue processing/speaking, off idle/interrupted/shutdown. It polls at
20 ms and debounces release for 100 ms. Every GPIO-controlled restart starts muted and
requires a stable muted-to-listen switch cycle. Any GPIO read/write fault latches mute
until restart. The switch asserts software permission; it does not electrically remove
microphone power or guarantee zero-latency isolation.

The Pi profile requires Linux ARM64 and Python 3.13. Its conservative defaults are tiny.en,
Llama 3.2 1B, two Whisper/Ollama threads, 1,024 model context, audio queue 50 and passive
queue 2. It starts muted and disables passive extraction, interruption and online tools.
Provisioning scripts install OS/Python dependencies, build pinned whisper.cpp v1.7.6,
download voices/models explicitly and install a specified Ollama archive with a supplied
SHA256. They do not establish target compatibility by themselves. Generated model hashes
aid reproduction but are not independent trusted pre-download digests for every model.

The hardware script exposes distro gpiozero/lgpio in the venv and adds audio/gpio groups.
The service installer renders units, mandates target `systemd-analyze verify`, installs
without enabling/starting and uses a non-root service user. Nova uses umask 0077,
NoNewPrivileges and ProtectSystem=full. SIGTERM follows graceful cleanup, rejects new
work and drains accepted passive items. Restart policy limits three failures per five
minutes, delays ten seconds and suppresses restart for configuration exit 78. Transient
preflight readiness uses exit 75. Nova's infinite stop timeout preserves draining but
can leave a stalled service requiring operator intervention. Physical boot, GPIO,
headless ALSA, ARM64 inference and thermal capacity remain unverified.

## Offline boundary and privacy

Core STT, model inference, memory, tools and TTS can operate without Internet after
local dependencies/models are provisioned. Offline capability is configuration-dependent:
online tools explicitly cross the boundary when enabled, and provisioning needs Internet.
Runtime local-model enforcement is an application policy, not a firewall or a guarantee
about independently configured Ollama/binary logs, telemetry or forwarding.

Software/physical mute combine with OR semantics. Generation/cancellation guards invalidate
stale input and stop new capture/dispatch. Work admitted earlier can finish and accepted
passive work drains. Routine runtime logs use fixed labels, counts and error categories.
Private debug/manual scripts can expose content and retain recordings. Owned runtime WAVs
are cleaned on normal/error shutdown, but power loss/SIGKILL can leave files and there
is no automatic crash sweep. SQLite is plaintext. Retention defaults to zero (no age
expiry), passive expiry hides records during reads, and explicit purging removes rows.
Deletion is not secure erasure. Regex credential detection is useful but incomplete.
No account authorization or speaker identity protects voice operations from nearby people.

## Evidence and performance claims

The latest DEVELOPMENT_STATUS checkpoint reports 1,278 tests passing in 114.53 seconds.
This is historical evidence, not automatically a result of this audit. See verification.md
and test-results.xml for the new attempt and runtime qualification.

The 9 October file-input benchmark in module-1266-validation-results.md reports Whisper
median 1,133.163 ms/p95 1,278.519 ms (10 samples), Piper median 871.319 ms/p95 1,968.337 ms
(15 mixed samples), and a file-response median 2,481.135 ms/p95 3,132.096 ms (5 samples).
The file-response benchmark excludes microphone/VAD, physical playback and settling.
Its single Ollama probe was 2,738.603 ms. Do not add these medians or advertise them as a
Pi end-to-end latency or accuracy distribution. Expanded retrieval's synthetic benchmark
reports median 3.409 ms/p95 6.585 ms over 100 queries and 303 records, not an archive-scale test.
The synthetic soak JSON reports 17 cycles in 61.34 seconds, 187 stream opens/closes and
one thread before/after, with fake models and no physical devices. None proves months
of uptime, thermal safety or multi-hour capture.

The newest status document says the user later reported Windows physical audio and
interruption checks passed. Older module checklists still say NOT RUN. Treat this as
reported manual evidence with stale snapshots, not a new independently observed run.

## Evaluation gaps and demo risks

1. **High: inaccessible project Python in this environment.** The Store Python 3.13/venv
   launcher fails to execute here. Restore/verify a supported interpreter before the
   live demonstration. Bundled Python 3.12 can author files and offers a qualified test
   attempt using existing packages, but is outside the declared >=3.13,<3.14 runtime.
2. **High: Pi hardware success unproven.** Keep the working Windows device as the primary
   demo unless the target Pi passes physical checks. Label mock GPIO honestly.
3. **High: privacy is software enforced.** No voice identity, encryption or electrical
   microphone cutoff. Obtain participant consent for any passive collection demo.
4. **Medium: STT/VAD venue noise and sequential capture.** A loud hall can trigger false
   utterances. Rehearse mic placement and threshold, use short sentences and wait for
   LISTENING. A dedicated acoustic wake engine is future work.
5. **Medium: performance/resource uncertainty.** LLM cold starts, background inference,
   1,024-token Pi context, CPU contention and thermal throttling need target measurement.
6. **Medium: service/audio dependencies.** Python 3.13 requirement, ARM64 wheel availability,
   RP1 chip mapping and headless audio devices must be checked on the target.
7. **Medium: reminders and interruption.** Verify audible delivery and restart recovery.
   Explain the duplicate crash window. Keep experimental spoken stop out of the core demo.
8. **Medium: public reproducibility.** Root requirements.txt embeds an absolute Windows
   editable path. pyproject omits audio extras. Use platform setup guides rather than
   treating root pip freeze as portable. No CI workflow or general release packaging found.
9. **Medium: documentation completeness.** README.md, SECURITY.md, LICENSE.md and
   docs/architecture.md, development.md, setup.md and raspberry-pi.md are empty files.
   The actual Pi guide is deployment/raspberry-pi/README.md. Historical docs conflict.
   Complete public setup, licensing and security documentation before distribution.

## Recommended next work (not implemented claims)

First validate a real Pi install, GPIO fail-closed behavior, boot/restart and multi-hour
audio/model workload with temperature, RSS, CPU and p50/p95 end-to-end timing. Then improve
deployment reproducibility and package the real voice launcher. Add a dedicated acoustic
wake detector and better VAD after measuring missed/false activation rates. Define consent,
retention and threat-model policy, consider encrypted storage and a true physical mic
disconnect. Add authentication before privileged integrations. Bound the entire memory
prompt by tokens, benchmark larger archives, and evaluate embedding retrieval only if
memory/CPU budgets allow it. AEC/full-duplex, cloud sync and mobile interfaces remain future
projects requiring separate implementation and validation.

## Source navigation

The exported source-inventory.json lists all scanned first-party files and symbols.
Key anchors are generated below from this exact checkout. Source hashes allow reviewers
to distinguish this audit snapshot from later source changes.
- `scripts/always_on_assistant.py:70`
- `src/offline_ai_companion/audio/continuous_recorder.py:23`
- `src/offline_ai_companion/audio/vad.py:5`
- `src/offline_ai_companion/stt/whisper.py:15`
- `src/offline_ai_companion/core/wake_detector.py:20`
- `src/offline_ai_companion/core/assistant.py:31`
- `src/offline_ai_companion/core/hardware.py:164`
- `src/offline_ai_companion/core/pi_deployment.py:50`
- `src/offline_ai_companion/core/systemd_units.py:1`
- `src/offline_ai_companion/tools/online_tools.py:1`
- `src/offline_ai_companion/memory/hybrid_retriever.py:1`
- `src/offline_ai_companion/core/privacy_policy.py:1`
- `src/offline_ai_companion/main.py:7`
