# Windows experimental interruption validation — Module 12.8B

Status: **not physically executed**. The user-reported 12.8A physical results
validate the previous half-duplex baseline, not this experimental mode.

## Setup

Use a test profile/database and nonsensitive sample speech. Start with headphones
and a quiet room. Record the revision, Windows version, numeric device IDs and flags.

```powershell
.\.venv\Scripts\Activate.ps1
$env:NOVA_EXPERIMENTAL_INTERRUPTION = "true"
$env:NOVA_SPOKEN_INTERRUPTION = "false"
$env:NOVA_AUDIO_DIAGNOSTICS = "true"
python .\scripts\audio_diagnostics.py
python .\scripts\always_on_assistant.py
```

S interrupts the current response, M toggles software microphone mute, Ctrl+C
shuts down. Console keys require focus. Test S first. Then stop, set
`$env:NOVA_SPOKEN_INTERRUPTION = "true"`, and restart for spoken tests.
Say **“Nova, stop”** as a separate utterance. Wait for LISTENING before giving
a fresh command. Every other command heard by the stop monitor is discarded.

Both flags default to false; spoken monitoring requires experimental mode.
`NOVA_INTERRUPT_LLM_TIMEOUT=30` bounds individual active HTTP operations with no
retries, not total wall-clock latency or server inference. `NOVA_INTERRUPT_STT_TIMEOUT=5`
bounds each stop-monitor Whisper job. Timeouts must be positive, finite seconds
up to 120. Main Whisper/Piper retain 120-second deadlines and gain cancellation
of owned subprocesses. No shared worker thread is forcibly killed.

The stop monitor alternates capture and transcription; it has blind intervals
during its own Whisper job. Spoken monitoring starts after main transcription,
during command processing or announcements. S also works during main transcription.

## Physical checklist

Mark each PASS/FAIL/NOT RUN and measure observed stop/recovery latency.

| Check | Procedure | Expected behavior |
|---|---|---|
| Fallback | Restart with both flags false; repeat 12.8A basic checks. | Original half-duplex; no stop monitor or S cancellation. |
| Conversation | Ask consecutive questions and give passive speech while idle. | One response at a time; listening resumes; only idle normal capture stores passive speech. |
| Console stop | Ask for a long response; press S during processing, synthesis and playback separately. | Output suppressed/stopped; fresh commands work after cleanup. Blocking Ollama may delay listening. |
| Spoken stop | With headphones and both flags enabled, say “Nova, stop” during speech. | INTERRUPTED, playback closes, LISTENING returns. Record latency. |
| Long playback | Stop near beginning, middle and end of long responses. | No residual playback after cleanup or overlap with a later response. |
| Echo | Test speakers at several volumes without speaking; include output quoting “Nova, stop”. | No tasks or memories from playback. Quoted stop disables spoken stop acceptance; S remains available. Record false stops. |
| Repeated wakes | Say repeated wakes, unrelated commands and repeated stops during speech. | Only separate exact wake+stop can cancel; no monitored command is executed or saved; stale stops never affect the next turn. |
| Mute | M during synthesis, playback and stop transcription; immediately unmute. | Response cancelled, input closes, muted/stale audio discarded; fresh capture opens after cleanup. |
| Reminder | Interrupt a due reminder via S and spoken stop. | Still pending, deferred 60 seconds, not immediately repeated; later full delivery completes once. |
| Side effects | Add a test task, note or reminder and interrupt its acknowledgment. | Already saved operation remains exactly once; no rollback. |
| Devices | Disconnect/reconnect input during monitoring and output during playback. | Sanitized failure category, streams close, next command recovers; S works if monitor fails. |
| Shutdown | Ctrl+C during playback/stop transcription; repeat start/stop five times. | Owned streams/children close, no stale capture/orphan monitor, accepted passive work drains. |

## Limits and sanitized reporting

There is **no acoustic echo cancellation**, speaker verification or general
full-duplex conversation. VAD/Whisper may misrecognize echo as stop. Text matching
only guards known stop phrases in output. Captures spanning processing-to-speaking
boundaries are rejected. Recognition needs an utterance boundary and may time out.
Monitor queue capacity is ten blocks; overflowed clips are discarded.

Twenty-millisecond playback blocks are not a guaranteed physical stop latency:
driver writes/closure can block. Cancelled Ollama inference may continue server-side.
The main loop waits for request completion and monitor closure before normal capture.
Generated conversation text may already exist before playback interruption; this
does not mean it was heard. Committed SQLite operations remain intact. Interrupted
reminder deferral changes its next due time; crash recovery is not exactly-once audio.

Share only scenario ID, flags, numeric device IDs, state sequence, sanitized stage/
error categories, counts and durations. Do not share audio, transcripts, responses,
credentials or databases. Inspect logs before sharing; device names may be personal.
If speakers cause false stops, disable spoken monitoring and retain console stop
or half-duplex. Reset both flags to false to restore the previous mode.
