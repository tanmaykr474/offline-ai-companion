# Module 12.8A — Windows physical audio validation

Status: automated lifecycle checks and a real Windows metadata/format preflight
are available. **Physical microphone-to-speaker validation is still pending.**
No microphone samples were recorded and no speech was played for the repository
verification reported here. Mocked tests cannot certify acoustic behavior.

Automated verification: **885 tests passed in 110.25 seconds** (837 preserved
baseline tests plus 48 new diagnostic/lifecycle cases). The final focused
compatibility run passed 62 tests in 2.89 seconds. Existing tests were not altered.

## Inspection and current behavior

The recorder opens a new 16 kHz mono float32 PortAudio input stream per utterance.
RMS-energy VAD confirms at least 0.2 seconds of speech, includes 0.7 seconds of
pre-roll, ends after 1 second of silence, and limits a started utterance to 15
seconds. Noise/music can exceed an energy threshold; VAD is not speaker identity
or semantic speech recognition. Whisper runs locally with a 120-second subprocess
timeout. Wake detection recognizes the configured phrase at the beginning of the
transcript. A wake-only utterance allows one follow-up within eight seconds.
Active processing uses the existing Assistant, memory tools and loopback Ollama.
Piper runs locally; playback blocks until completion and calls `sounddevice.stop()`.

The loop remains half-duplex. A shared guard serializes runtime capture and speech
output, including reminders. Playback cancels any current capture and waits for
its context to close. Capture remains closed through synthesis, playback and the
existing 0.3-second settling interval, including partial playback failures.
Playback invalidates recordings/transcriptions from the preceding audio generation.
This is interruption of capture for output, **not user barge-in or full duplex**.
Speech spoken while Nova answers is not captured.

Mute generations cancel existing capture and invalidate STT results even after
fast mute/unmute. Each stream has a retired flag so late callbacks cannot repopulate
its queue. New capture uses fresh pre-roll and a new queue. Application shutdown
rejects later recording/transcript submissions. Stop during transcription rejects
its result. The existing completed-recording graceful-drain contract remains:
the loop can finish an already accepted completed recording before closing, and
already accepted passive work drains. A real recording cancelled by stop/mute
returns no WAV and is not newly accepted. Mute does not kill an ongoing Whisper
subprocess; its result is discarded and its existing timeout still applies.

These software boundaries do not prove physical microphone disconnection. They
also do not cancel arbitrary third-party recordings or authenticate speakers.

## Device and dependency preflight (no audio capture/playback)

From the project root in PowerShell:

```powershell
.\.venv\Scripts\Activate.ps1
python .\scripts\audio_diagnostics.py --output .\docs\my-audio-preflight.json
```

The report lists device indices, host API indices, input/output channel counts,
default sample rates and default devices. It checks format support without opening
streams: 16 kHz mono input and a representative 22.05 kHz mono Piper output.
Piper may produce another sample rate; live playback uses the actual WAV rate.
Local executable/model/config checks report booleans, not private paths. They
prove file presence, not that the model/executable runs successfully. Device/format
errors contain only exception types. Exit status is nonzero for failed enumeration
or format checks.

For local device identification, explicitly opt in:

```powershell
python .\scripts\audio_diagnostics.py --include-device-names
python .\scripts\audio_diagnostics.py --input-device 1 --output-device 4
```

Names may contain personal labels; review them locally and omit them from shared
reports. Set `NOVA_INPUT_DEVICE` and `NOVA_OUTPUT_DEVICE` to the chosen nonnegative
indices in `.env`, or leave them empty for current Windows defaults. Re-enumerate
after unplugging devices/restarting; indices and defaults can change. Multiple
PortAudio entries can describe the same physical device through different APIs.
Choose a real microphone, not Stereo Mix/loopback/virtual output capture.

The checked report [module-128a-device-report.json](module-128a-device-report.json)
was generated on Windows using Python 3.13.14. It found 33 PortAudio entries,
default input index 1 and output index 4. Both checked formats were supported and
all five local file-presence checks passed. Device names are omitted. **These
results do not establish live recording, STT quality or audible playback.**

## Isolated manual session

Use a fresh PowerShell session so test environment overrides do not accidentally
affect later production runs. This creates a separate persistent validation database;
it does not change or delete your existing memories.

```powershell
.\.venv\Scripts\Activate.ps1
New-Item -ItemType Directory -Force .\data\validation-128a | Out-Null
$env:DATABASE_PATH = Join-Path (Get-Location) 'data\validation-128a\memory.db'
$env:PASSIVE_MEMORY_ENABLED = 'true'
$env:MIC_ENABLED = 'true'
$env:NOVA_AUDIO_DIAGNOSTICS = 'true'
$env:NOVA_PERFORMANCE_LOG = 'true'
$env:NOVA_PRIVATE_DEBUG = 'false'
python .\scripts\always_on_assistant.py 2>&1 | Tee-Object -FilePath .\data\validation-128a\audio.log
```

Use only synthetic/non-sensitive example speech below. Keep system volume moderate
and use the same device placement/settings for repeat runs. Record selected device
indices and whether Windows microphone permissions permit desktop apps. Press `M`
in the focused console to toggle software mute; Ctrl+C stops the application.
If a terminal/pipeline prevents hotkey input, run directly without `Tee-Object`
and copy only the operational lines after the test. Close this PowerShell session
when finished. The validation database/log intentionally remain for review.

## Hands-on checklist and expected results

| Check | Procedure | Expected behavior / evidence |
| --- | --- | --- |
| Idle capture | Remain quiet for 30 seconds. | LISTENING; stream_open; no TTS, active command or stored silence. |
| VAD segmentation | Say a synthetic sentence, then pause over one second. | stream_closed precedes transcription; no missing beginning/end; one utterance dispatched. |
| Wake command | Say “Nova, what is my favorite food?” | PROCESSING → SPEAKING; one clear honest response; a fresh stream_open and LISTENING afterward. |
| Wake follow-up | Say “Nova”, then a command within eight seconds; repeat with a longer wait. | One timely follow-up is active; the expired follow-up is background speech, not an active command. |
| Passive memory | Say “I love playing cricket” without Nova; wait for background processing; ask “Nova, what sport do I love playing?” | No spoken response to passive speech; grounded, attributed recall later; one observation on review. |
| Generalized recall | Separately say birthplace, enjoyment, favorite food and occupation examples from earlier modules. | Background extraction and grounded recall work without production database changes. |
| Tasks | Add a synthetic task, review its ID, complete it, confirm Yes, then repeat completion. | Correct stable task ID; confirmation before mutation; repeated completion changes nothing. |
| Reminders | Schedule “Remind me to take a break in 1 minute.” | One reminder notification, followed by resumed listening; no duplicate notification on later polls. |
| Idle mute/unmute | Press M while LISTENING; talk while muted; press M again. | MUTED and stream_closed; no new stream_open, STT or storage while muted; new stream opens after unmute. |
| Mid-utterance mute | Begin an utterance, press M before its ending pause, unmute and speak a different sentence. | First capture discarded; no old pre-roll or command appears in the new capture. |
| Mid-STT mute | Mute while transcription is running, then quickly unmute. | STT can finish, but its old result is not dispatched/stored/spoken; next fresh utterance works. |
| Playback isolation | Stay silent while Nova answers; repeat several loud enough answers at normal volume. | No stream_open while playback guard is active; Nova's answer never creates a second command or passive memory. |
| Playback tail | After each answer, stay silent for several seconds and review observations/tasks. | No new self-echo records. Any delayed echo is a failed physical check, even if mocked tests passed. |
| Input recovery | Disconnect the selected USB mic or make it unavailable, then restore/re-enumerate it. | capture error category; retry without raw speech; fresh stream after device restoration. If its index changed, select it and restart. |
| Output recovery | Make the selected speaker unavailable; issue a command, restore it and repeat. | playback error distinct from synthesis; no retained response WAV; later output works. |
| Shutdown | Ctrl+C during idle, capture, STT and passive extraction in separate runs. | Streams retire, no stale post-shutdown dispatch; accepted passive work drains; runtime-owned WAVs are removed. |
| Repeated sessions | Start/stop three sessions using the same validation database. | No lingering/busy mic; memories persist; completed tasks and delivered reminders retain state. |
| Overflow monitoring | Run normal speech under realistic CPU load. | No overflow warnings. Any dropped/input-overflow blocks discard the whole utterance rather than transcribe incomplete audio. |

Model tests can take up to their existing timeout. No test requires disclosing
private speech or credentials. Do not deliberately overload the computer until
it becomes unresponsive just to force overflow.

## Sanitized failure collection

Opt-in diagnostics emit fixed stage/event labels, exception types and duration
numbers. Queue warnings report `dropped_blocks` and `input_overflows`; playback
underruns report `output_underflows`. Routine logs omit raw audio, transcripts,
responses, prompts, memory contents, subprocess stderr and private paths. Normal
stage success/stream event diagnostics are disabled by default. Errors and overflow
warnings remain privacy-safe when diagnostics are disabled.

For sharing, extract only known operational lines and inspect the result:

```powershell
Get-Content .\data\validation-128a\audio.log |
    Where-Object { $_ -match '^\[(STATE|PRIVACY|AUDIO DIAG|AUDIO ERROR|ASSISTANT ERROR|VOICE PIPELINE ERROR|REMINDER|REMINDER ERROR|MEMORY|STT|WAKE|RESPONSE|PERF|WARNING)\]' } |
    Set-Content .\data\validation-128a\sanitized-audio.log
```

Record a check number, selected indices, expected versus observed event order,
exception category, duration, overflow counts, and whether retry succeeded. Share
the names-omitted preflight JSON and reviewed operational lines. Do not share WAVs,
the validation/production SQLite database, `.env`, device names, raw traceback or
private debug output. Logger-generated overflow warnings may lack square-bracket
prefixes; manually copy only their numeric count line.

| Failure stage | First checks |
| --- | --- |
| capture / stream_close_failed | Device presence/index, Windows desktop-app mic permissions, another app's exclusive access, format support; stop/restart if driver closure fails. |
| transcription | Whisper executable/model presence, current WAV ownership/cleanup, timeout duration. |
| processing | Local Ollama availability and existing model, memory database permissions; preserve loopback-only enforcement. |
| synthesis | Piper executable/model and adjacent model `.json`, timeout, output generation. |
| playback / underrun | Output selection, volume, audio driver and supported actual WAV rate. |
| dropped blocks / input overflow | CPU load, audio driver/API, device compatibility; repeat the utterance after recovery. |

## Remaining physical risks and stopping point

The software guard prevents overlap and stale generations within Nova's current
runtime. It is not acoustic echo cancellation. Long room reverberation, OS/device
buffers or a loopback input can still carry output into a later fresh capture;
the 0.3-second settling interval is not a universal acoustic guarantee. Test this
with the actual mic/speaker setup. If it fails, stop and report the event sequence;
do not treat that setup as validated. Headphones/lower volume and a real mic input
help isolate the cause without introducing full duplex.

Driver-specific close/reopen behavior, actual speech quality, device reconnection,
physical sound level, recognition latency and long-running reliability remain
hands-on checks. No full-duplex listening, echo-cancellation algorithm, user barge-in
or Raspberry Pi deployment was implemented. Record each physical check as
PASS/FAIL/NOT RUN before moving beyond this module.
