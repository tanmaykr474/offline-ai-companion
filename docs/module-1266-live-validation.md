# Module 12.6.6 — Windows live voice validation

Status: **physical microphone and speaker checks have not been executed**.
Automated device mocks and synthetic speech files do not satisfy this checklist.
Do not begin Raspberry Pi deployment until the Windows checks have passed.

## Safe test setup

Use a new validation database so test speech cannot modify personal memories.
From the project directory in PowerShell:

```powershell
$env:DATABASE_PATH = Join-Path $PWD ("sample-data\memory\voice-validation-" + (Get-Date -Format "yyyyMMdd-HHmmss") + ".db")
$env:PASSIVE_MEMORY_ENABLED = "true"
$env:PASSIVE_MEMORY_LLM_TIMEOUT = "30"
$env:NOVA_PERFORMANCE_LOG = "true"
.\.venv\Scripts\python.exe .\scripts\always_on_assistant.py
```

Keep the same `DATABASE_PATH` for restart tests. Use synthetic information only.
The normal console displays transcripts and answers; do not record or share it
with private speech. `[PERF]` records contain only stage, duration and status.
Before returning to normal use, close this PowerShell session or remove the four
environment variables; the validation database will remain separate.

## Microphone, routing, memory and playback

- [ ] Confirm the correct microphone and speaker are selected in Windows.
- [ ] Start Nova and check `[PRIVACY] Passive memory: ENABLED` and `LISTENING`.
- [ ] Speak each passive statement below **without** “Nova”. Wait for the
  background worker's processing-completed message before asking its question.
- [ ] Check that background speech produces no spoken response.
- [ ] Say the corresponding wake question and hear an intelligible answer.
- [ ] Check that passive answers acknowledge the unidentified speaker rather
  than claiming the observation is an established fact about you.
- [ ] After each answer, check that `LISTENING` returns and another utterance
  can be captured.

| Passive speech | Wake question | Required answer content |
| --- | --- | --- |
| I love playing cricket. | Nova, what sport do I love playing? | cricket |
| I was born in Bihar. | Nova, where was I born? | Bihar |
| I enjoy listening to music. | Nova, what do I enjoy doing? | listening to music |
| My favorite food is biryani. | Nova, what is my favorite food? | biryani |
| I work as a software developer. | Nova, what do I do for work? | software developer |

- [ ] Repeat one passive statement and several recall questions. Confirm the
  validation database still has one copy of that observation. SQLite inspection
  must use the validation database path, never the default personal database.
- [ ] Say “I wasn't born in Kerala.” It must not create “Birthplace is Kerala”.
- [ ] Ask “Nova, what is my favorite color?” before saving one. Hear an honest
  unavailable-information response.
- [ ] Say “I was born in Kerala.” Ask where you were born. Hear uncertainty
  about conflicting observations, rather than an arbitrary current birthplace.
- [ ] Say “Nova, my favorite food is Pizza”, then “Nova, yes”. Ask for favorite
  food. Confirm that the confirmed fact Pizza overrides passive biryani.
- [ ] Test “Nova” alone followed promptly by a question; test again after more
  than eight seconds. The expired follow-up must not be answered as active speech.
- [ ] Test TV/music noise, including caption-only Whisper output. Verify that
  `[XBOX SOUND] [MUSIC]` is not queued and ordinary speech beside captions survives.

## Reminders, model delay, shutdown and recovery

- [ ] Say “Nova, remind me to drink water in 1 minute”. Confirm reminder playback,
  successful acknowledgment, and listening resumption after the interruption.
- [ ] Queue a statement requiring local LLM extraction, then immediately ask a
  supported recall question. Verify that background extraction does not block
  the active question. Ollama may still serialize concurrent model requests.
- [ ] Stop the local Ollama server and ask a general question. Verify the honest
  model-error response. Restart Ollama and verify a later general question works.
- [ ] Disconnect the microphone, observe recovery, reconnect it, and verify a
  later utterance. Repeat for the speaker and confirm a later answer can play.
- [ ] Press Ctrl+C during idle listening, then restart in the same session.
- [ ] Press Ctrl+C during Whisper transcription; confirm cleanup and restart.
- [ ] Press Ctrl+C while passive extraction is running. Verify that accepted
  observations drain and `Nova stopped.` appears only after shutdown completes.
  A full queue can require multiple extraction timeouts; do not force-kill it.
- [ ] Restart as a **new process** with the same validation database and recall
  an earlier observation. Repeat three start/stop cycles.
- [ ] Check for unintended retention of `data/audio/latest_*.wav` files. These
  files are currently retained by the application and may contain private audio.

## Timing records

Enable `NOVA_PERFORMANCE_LOG` as above. Record numeric values without transcripts:

| Stage | What is measured |
| --- | --- |
| transcription | Whisper call, including local process startup |
| passive_extraction | Extract, validate, deduplicate and SQLite write; excludes queue wait |
| memory_retrieval | Retriever classification, fact lookup and passive scan |
| ollama_response | Local model request, including configured retry delays |
| tts_generation | Piper generation including process startup and output verification |
| voice_dispatch | Transcript routing through active playback or passive queue submission |
| voice_response | Completed recording through STT, dispatch and active playback/settling |

The voice-response clock excludes microphone recording, VAD silence hangover and
time waiting for the person to speak. For passive speech it ends after queue
submission, not after extraction. Stage records overlap and must not be summed.
`status=ok` means that the instrumented callable returned normally, not that a
memory was saved or audio delivery was successful: handled errors can return
normally. Nested adapter records expose exceptions as `status=error` without
including exception details. Metrics are disabled at the console by default.

The synthetic benchmark is reproducible:

```powershell
.\.venv\Scripts\python.exe .\scripts\benchmark_voice_pipeline.py --iterations 20 --local-audio --ollama --output docs/module-1266-performance.json
```

It uses temporary SQLite databases, deterministic sample observations and local
Piper speech files resampled to 16 kHz for Whisper. An independent empty database
receives the transcribed passive statements before their transcribed questions
are answered. It never opens a microphone
or plays audio. The Ollama probe sends a fixed synthetic prompt only to a loopback
host. The resulting JSON contains numeric metrics and scenario success flags.

## Remaining integration risks and gate

- Module 12.7.1 adds console software mute. See
  [mute-boundary policy and physical checklist](module-1271-software-privacy.md).
  Passive-memory disablement alone still does not disable microphone capture.
  Hardware-enforced privacy is not provided by software mute.
- Audio capture pauses during STT, active processing and playback. Nova resumes
  afterward, but simultaneous continuous capture and interruption of responses
  are not implemented. Wake phrases are detected from completed transcriptions.
- RMS VAD detects energy rather than distinguishing human speech from music.
  Caption filtering cannot reject a fluent hallucinated Whisper transcript.
- Passive speaker identity remains unknown. Stored timestamps reflect processing
  time because capture timestamps are not passed through the background queue.
- Deterministic recall covers supported relations; other personal questions can
  still reach LLM answering. Automated mocks do not prove semantic accuracy of
  those responses or real model extraction.
- Queue draining protects ordinary shutdown, not forced termination or power loss.
  Extraction failures are reported but failed transcripts are not persisted for retry.
- Fresh-process restart is supported. Reusing the same `AlwaysOnAssistant.run()`
  instance after shutdown is not supported because stop/notification events stay closed.
- Hardware performance, acoustic echo, TV false activations, dropped audio and
  long-duration stability remain to be measured on Windows.

Windows acceptance requires the five live scenarios, privacy requirements,
recovery and shutdown checks to pass with measured latency acceptable to the
user. Until then, Raspberry Pi deployment remains deferred.
