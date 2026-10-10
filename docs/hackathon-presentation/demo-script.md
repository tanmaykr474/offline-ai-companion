# Nova jury demonstration script

Target duration: 6 minutes. Rehearse on the actual presentation machine. This script is
a proposed demonstration, not evidence that the physical run happened in this audit.

## Before the jury enters

Use synthetic speech only. Keep the same isolated database for restart demonstration.
Models and voice must already exist, Ollama must already serve llama3.2:1b on loopback,
and the supported Python 3.13 interpreter must work. The current project Store/venv
launcher is inaccessible in the audit sandbox, so resolve that before presentation.
Use the metadata-only scripts/audio_diagnostics.py for format/device preflight.
Do not run an unreviewed health check against the default personal database: some
health-check paths initialize/write SQLite. Any database check must use the demo path.

In a NEW PowerShell terminal from the repository root, after fixing the interpreter:

```powershell
$env:DATABASE_PATH = Join-Path $PWD 'docs/hackathon-presentation/.build/demo-companion.db'
$env:PASSIVE_MEMORY_ENABLED = 'false'
$env:NOVA_ONLINE_TOOLS_ENABLED = 'false'
$env:NOVA_EXPERIMENTAL_INTERRUPTION = 'false'
$env:NOVA_SPOKEN_INTERRUPTION = 'false'
$env:NOVA_PRIVATE_DEBUG = 'false'
$env:MIC_ENABLED = 'true'
$env:NOVA_GPIO_BACKEND = 'none'
$env:NOVA_HEADLESS = 'false'
$env:NOVA_PERFORMANCE_LOG = 'true'
.\.venv\Scripts\python.exe .\scriptslways_on_assistant.py
```

Do not use the installed offline-ai-companion command for the voice demo: it currently
only prints startup text. Use the actual script above. A separate shell keeps overrides
out of ordinary use. Close it afterward. The demo database is retained intentionally.
For a Pi, use its separate env/profile and guarded launcher after target preflight.
Never copy the Windows .env to Pi or enable a service before hardware validation.

## 0:00–0:35 Problem and honest scope

Presenter: “Nova keeps speech processing and personal memory on this machine. It combines
local voice models with deterministic tasks and reminders. The Pi deployment and GPIO
modules exist, but physical Pi validation remains a separate milestone.”
Show online tools disabled, then disconnect external network access. Keep loopback
available. Do not change network settings for another person's machine without consent.

## 0:35–1:15 Wake activation and local answer

Wait for LISTENING. Say “Nova, explain what a solar eclipse is in one sentence.”
Expected: local Ollama answer, Piper speech, then LISTENING resumes. Wording varies.
Say “Nova” alone, then “What is my name?” promptly within eight seconds.
Expected on a new database: unavailable name response. The window permits one command.
Explain: Whisper transcribes before transcript wake filtering. This is not an acoustic
keyword engine. Wait for LISTENING before each new sentence.

## 1:15–2:15 Explicit memory and a one-minute reminder

Say “Nova, my name is Alex.” Expected: direct saved name acknowledgment (no confirmation).
Say “Nova, my favorite food is pizza.” Expected: a save proposal.
Say “Nova, yes.” Expected: confirmed favorite food.
Say “Nova, remind me to drink water in 1 minute.” Expected: explicit scheduling acknowledgment.
Say “Nova, remember that the project demo is in room seven.” Expected: saved note.
Make clear that explicit creation and legacy name updates can save directly.

## 2:15–3:15 Persistence, tasks and audible reminder

Press Ctrl+C and wait for cleanup. Relaunch with the SAME DATABASE_PATH.
Say “Nova, what is my name?” and “Nova, what is my favorite food?”
Expected: Alex and pizza persist. Say “Nova, show my notes.” Expected: synthetic room note.
Say “Nova, add a task to finish my project.” Then “Nova, show my pending tasks.”
Expected: saved task and its typed ID. Complete the displayed ID, then “Nova, yes.”
Do not assume the ID will be1. Await the water reminder and audible playback.
If timing is delayed by inference/restart, wait rather than asserting delivery occurred.

## 3:15–4:00 Mute and privacy boundary

Press M in the focused Windows console. Show MUTED and speak “Nova, add a task to buy a car.”
Press M to unmute, wait for LISTENING, then ask for pending tasks.
Expected: muted speech created no new task. Microphone mute does not promise silent
reminders. Explain accepted earlier work can finish and SQLite is plaintext.
On a validated Pi, instead cycle the switch and show red/green/blue states. A mock
demonstration must be labeled mock. Explain GPIO does not electrically cut mic power.

## 4:00–5:00 Optional passive observation, only if rehearsed

If the venue/participants consent and the feature passed rehearsal: stop gracefully,
set PASSIVE_MEMORY_ENABLED=true in the same isolated session and relaunch. Say without
wake word “I enjoy listening to music.” Wait for the worker's completion count.
Say “Nova, what do I enjoy doing?” Expected: music observation with unidentified-speaker
qualification, not a confirmed owner fact. Background speech must cause no spoken answer.
If this optional feature is omitted, show its code/diagram path and label it opt-in.
Do not stage a response as if it came from the live microphone.

## 5:00–6:00 Limits and conclusion

Ask “Nova, what is the weather in Delhi?” With online tools disabled expect the explicit
offline-unavailable response. Do not claim a fresh offline forecast. Point to the
architecture boundary and explain external tools are optional. Close with physical Pi
validation, sustained testing and acoustic wake detection as next milestones.
Press Ctrl+C, wait for accepted work to drain, and verify ordinary temporary WAV cleanup.

## Fallbacks and recovery

- If voice fails, switch to scripts/assistant_test.py using the isolated database and
  label the demonstration text mode. It demonstrates routing/persistence, not STT/TTS.
- If the LLM is unavailable, show deterministic recall/tasks. Admit general chat is
  unavailable until local Ollama is healthy. Do not expose raw private logs.
- If a reminder has not spoken, show the pending record and state delivery remains
  unverified. Saved scheduling is different from audible success.
- If GPIO fails, retain mute and repair/restart. Do not bypass fail-closed behavior.
- Keep a rehearsed recording with synthetic data only as a labeled prior recording.
  This audit does not create or claim a physical demo video.
- Skip spoken interruption, live online providers and unvalidated Pi boot behavior
  in the core jury sequence. Present them with their actual status.
