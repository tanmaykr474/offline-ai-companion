# Final evaluation readiness checklist

Unchecked items require presenter action. This audit does not certify live hardware.

## Content and claims

- [x] Architecture source and exported PNG created, with online/control/privacy boundaries.
- [x] 12-slide PPTX created with notes and source references.
- [x] At least30 jury questions answered using repository evidence.
- [x] Demo script and feature-status audit created.
- [ ] Read verification.md for the new test result and runtime limitations.
- [ ] Rehearse notes and keep the pitch within the event's allocated time.
- [ ] Remove unsupported claims of model invention, encrypted memory or electrical mute.
- [ ] Call the Pi a deployment target until physical evidence exists.
- [ ] Label Windows manual checks as reported, benchmarks as historical and mocks as mocks.
- [ ] Open the final PPTX on the presentation machine and check fonts/notes/projector output.

## Reproducible environment

- [ ] Restore a working supported Python 3.13 environment and run its full test suite.
- [ ] Confirm project audio/HTTP/timezone dependencies and local binaries/models.
- [ ] Use scripts/always_on_assistant.py rather than the placeholder packaged CLI.
- [ ] Confirm local Ollama API serves llama3.2:1b with no external model forwarding.
- [ ] Record model versions/digests and actual device specs in the final event evidence.
- [ ] Verify Whisper tiny.en and matching Piper ONNX/config pair before the event.
- [ ] Keep the demo SQLite database separate from production personal memories.
- [ ] Do not publish .env, API keys, private DBs, audio, prompts or terminal content.

## Physical voice demo

- [ ] Check mic input/speaker output and 16 kHz mono input on the actual device.
- [ ] Rehearse venue noise, mic distance and VAD threshold with synthetic speech.
- [ ] Test wake+command, wake-only follow-up and expired eight-second follow-up.
- [ ] Verify unprefixed speech causes no active spoken response.
- [ ] Verify basic general chat, Piper speech and return to LISTENING.
- [ ] Save and recall a confirmed fact, note and task after restart.
- [ ] Show a declined/expired confirmation leaves data unchanged.
- [ ] Verify unknown memory gives an honest unavailable response.
- [ ] Verify task completion uses the displayed ID and scoped confirmation.
- [ ] Verify one-minute reminder playback, completion and restart recovery.
- [ ] Test input mute during idle/capture/STT/output and rejection of stale input.
- [ ] Verify owned WAV cleanup on normal shutdown and explain abrupt-exit limits.
- [ ] Keep experimental interruption disabled for the core pitch unless separately rehearsed.
- [ ] Keep online tools disabled and demonstrate external-network disconnection.
- [ ] Prepare clearly labeled text-mode and prior-recording fallbacks.

## Optional passive/online demonstration

- [ ] Obtain consent for passive collection and explicitly enable it for synthetic data.
- [ ] Wait for extraction completion before recall and show unidentified-speaker wording.
- [ ] Test duplicates, negation, conflicting observations and confirmed-fact priority.
- [ ] Disable passive collection afterward and allow accepted work to drain.
- [ ] If showing weather/news, configure actual providers and keys privately.
- [ ] Verify live provider quota/key/network failure behavior before the event.
- [ ] Clearly state provider queries cross the Internet boundary.

## Raspberry Pi 5 hardware and deployment gate

- [ ] Verify Linux 64-bit ARM, Python 3.13 and actual ARM64 package/wheel compatibility.
- [ ] Provision explicitly, verify trusted Ollama digest and local model presence.
- [ ] Verify ALSA/PortAudio devices as the non-root service user.
- [ ] Inspect gpiozero 2/lgpio API compatibility, RP1 chip index and audio/gpio group access.
- [ ] Verify BCM pin mapping, LED polarity, per-color resistors and switch wiring.
- [ ] Test red mute, green listening, blue processing/speaking and shutdown off.
- [ ] Verify every restart starts muted even if the switch already indicates listen.
- [ ] Verify stable mute-to-listen cycle, bounce handling and physical mute priority.
- [ ] Simulate supported GPIO read/write errors: latch mute until explicit restart.
- [ ] Explain software mute does not electrically disconnect microphone power/data.
- [ ] Run target systemd-analyze verify before service installation.
- [ ] Enable units only after the manual physical checklist passes.
- [ ] Test reboot/start ordering, exit 75 retry, exit 78 stop and failure rate limit.
- [ ] Test SIGTERM during capture/STT/LLM/playback and accepted passive drain.
- [ ] Verify LED/pin/child/audio cleanup and SQLite consistency after shutdown.
- [ ] Verify service stop can be investigated if infinite draining stalls.
- [ ] Run the deferred multi-hour physical soak with CPU/RSS/temperature and latency logs.

## Unfinished and unverified scope to disclose

- [ ] Physical Pi GPIO, headless audio, ARM64 inference and boot recovery remain unverified.
- [ ] Multi-hour physical reliability and target thermal/resource capacity remain unverified.
- [ ] Live online-provider/key/quota tests remain unperformed in recorded evidence.
- [ ] No acoustic wake engine, AEC, general full-duplex or authenticated speaker identity.
- [ ] No encrypted SQLite, secure erasure or electrically enforced mic cutoff.
- [ ] Whole-model-context token budgeting and large/multi-user archive performance incomplete.
- [ ] Root README/security/license/setup docs and portable packaging need follow-up.
