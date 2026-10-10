## 1. Nova

Opening, 25 seconds: Introduce Nova as a local voice companion with persistent personal memory. Explain that the implementation combines established models rather than training a new one. The Windows prototype and automated policies have evidence. Pi 5 is a deployment target with implemented preparation and GPIO code, but its physical operation remains unverified. Do not use always-on to imply uninterrupted full-duplex recording.

Repository evidence: scripts/always_on_assistant.py; config.py; docs/DEVELOPMENT_STATUS.md
Cover artwork is an AI-generated abstract illustration, not a photo of prototype hardware.

## 2. The problem

35 seconds: Frame these as design motivations, not validated market statistics. Personal assistants should remain useful when the external network is unavailable. Repeatedly restating personal information is inconvenient. Continuous sensing needs understandable controls. Nova attempts to address these needs locally. The repository does not provide user research or quantified market validation.

Repository evidence: project description in pyproject.toml; core/privacy.py; memory/database.py

## 3. The Nova solution

40 seconds: Explain the complete local integration. Emphasize confirmed facts versus unidentified passive observations, deterministic tools, transactional memory changes and shared privacy gates. Optional passive extraction defaults off. This is integration innovation rather than a new foundation model. Online weather/news are a clearly separate opt-in branch.

Repository evidence: core/assistant.py; memory/passive_processor.py; memory/management.py; tools/lifecycle.py

## 4. System architecture

60 seconds: Walk the top row from mic through RMS VAD to whisper.cpp and transcript activation. Follow active commands to Assistant, local memory or loopback Ollama, then Piper and speaker. Background speech enters only the optional passive worker. Explain reminders route through the main output loop. The amber boundary is explicit weather/news, not cloud inference. Navy dashed arrows are control. GPIO supplies software permission and reflects state. Plaintext storage and unverified Pi hardware are visible limitations.

Repository evidence: scripts/always_on_assistant.py:70; src/offline_ai_companion/audio/continuous_recorder.py:23; src/offline_ai_companion/audio/vad.py:5; src/offline_ai_companion/stt/whisper.py:15; src/offline_ai_companion/core/wake_detector.py:20; src/offline_ai_companion/core/assistant.py:31; src/offline_ai_companion/core/hardware.py:164; src/offline_ai_companion/core/pi_deployment.py:50; src/offline_ai_companion/core/systemd_units.py:1; src/offline_ai_companion/tools/online_tools.py:1; src/offline_ai_companion/memory/hybrid_retriever.py:1; src/offline_ai_companion/core/privacy_policy.py:1; src/offline_ai_companion/main.py:7
The compact diagram groups routing, memory tools and scheduler output inside the main loop. Local model traffic is loopback. The optional passive worker can use local Ollama for extraction and writes grounded observations to SQLite. GPIO state is software permission, not electrical cutoff. Physical Pi operation is not verified.

## 5. The technology stack

35 seconds: All stack choices come from adapters and configuration. Clarify that the declared application runtime is Python 3.13, while bundled Python 3.12 is used only for artifact authoring and qualified audit checks. tiny.en and lessac are platform defaults. GPIO uses local gpiozero/LGPIOFactory rather than remote pins. No embeddings are in this implementation.

Repository evidence: pyproject.toml; config.py; core/platform_config.py; core/hardware.py; deployment/raspberry-pi/nova.env.example

## 6. Working flow

40 seconds: A typical utterance ends after one second of silence. STT precedes wake handling. Wake+command activates directly, and wake-only permits a single eight-second follow-up. Most tool/recall paths avoid general model generation. Capture resumes after output and0.3-second settling. Background speech does not receive an answer. The flow is half-duplex, so users should wait for listening before speaking again.

Repository evidence: audio/continuous_recorder.py; stt/whisper.py; core/activation_controller.py; scripts/always_on_assistant.py

## 7. Memory with provenance

45 seconds: SQLite holds separate facts, notes, tasks, reminders and evidence-bearing passive records. Conversation history stays in RAM with ten-turn and4,000-character bounds. Hybrid recall uses a bounded concept lexicon, not embeddings. Management confirmations expire and recheck rows within a transaction. Do not say every creation requires confirmation: legacy name, explicit note/task and reminder creation are direct-write exceptions. Historical1,278-pass checkpoint is not the new audit result. The saved qualified test run contains 1,272 passes and six subprocess environment failures.

Repository evidence: memory/database.py; memory/hybrid_retriever.py; core/conversation.py; memory/management.py; tools/lifecycle.py; docs/DEVELOPMENT_STATUS.md
Examples on this slide are synthetic explanatory examples, not stored personal data. Passive storage is opt-in and does not identify the owner or automatically create tasks. Most fact changes require confirmation, but direct note/task/reminder creation and the legacy name path are exceptions. Do not promise confirmation for every write.

## 8. Visible hardware controls

45 seconds: Explain intended wiring and fail-closed permission behavior, not a proven hardware demo. Default BCM17 / 27 / 22 drive RGB and BCM23 reads the switch. Listening green, processing/speaking blue and mute red. Restart starts muted and needs deliberate stable switch cycling. GPIO faults latch mute. Headless production requires LinuxARM64 with local lgpio. Provisioning/setup and systemd templates exist, but actual GPIO, ALSA, boot and model performance are unverified. The switch does not disconnect mic power.

Repository evidence: core/hardware.py; core/service_runtime.py; core/pi_deployment.py; deployment/raspberry-pi/README.md

## 9. The live demonstration

Demonstration, about two minutes within the pitch if time permits: Use a synthetic isolated SQLite path and preloaded models. Say Nova explain a solar eclipse in one sentence. Save Alex via name command and pizza via proposed favorite+yes. Add a one-minute water reminder. Restart with same DB and recall name/favorite. Show a task and its displayedID. Mute withM and verify muted speech creates no task. Explain exact wording can vary. Use the actual always_on_assistant script, not the startup-only packagedCLI. If the interpreter/device fails, label the text-mode fallback honestly.

Repository evidence: scripts/always_on_assistant.py; scripts/assistant_test.py; demo-script.md; tools/memory_tools.py

## 10. Challenges and limits

45 seconds: Disclose limits concretely. RMSVAD is susceptible to venue noise and transcript-based activation incursSTT cost before wake. Sequential processing has capture gaps. Small model context can constrain memory prompts. SQLite is plaintext, speaker identity is absent and electrical cutoff is absent. NoAEC/full-duplex exists. Pi, provider and multi-hour physical evidence need validation. The audit found StorePython/venv inaccessible in this environment, empty root docs and a nonportable Windows freeze. These must be addressed before claiming easy deployment.

Repository evidence: audio/vad.py; core/wake_detector.py; core/hardware.py; core/assistant.py; docs/DEVELOPMENT_STATUS.md; requirements.txt

## 11. The next milestones

35 seconds: These are recommendations, not completed features. Prioritize physical Pi validation and repeatable packaging before expanding scope. Measure thermal/resource/latency and long-running reliability. Then consider acoustic wake/VAD, authenticated voice commands, consent/retention controls, encrypted storage and true electrical mic disconnect. Full-duplex and broader integrations require their own implementation. No invented milestones, user metrics or promised model performance.

Repository evidence: repository-evaluation.md recommendations; docs/LONG_RUNNING_VALIDATION.md; deployment/raspberry-pi/README.md

## 12. Nova

Closing,25 seconds: Nova demonstrates a coherent local voice architecture with persistent memory, deterministic tools and software privacy gates. The repository contains substantial automated test coverage and bounded recovery policies. State clearly that target hardware and sustained physical reliability are next validation gates. Invite questions and keep jury-cross-questions.md nearby. Avoid promising encrypted, authenticated or uninterrupted listening behavior.

Repository evidence: scripts/always_on_assistant.py; docs/DEVELOPMENT_STATUS.md; repository-evaluation.md
Closing artwork is an AI-generated abstract illustration. Invite questions on the local voice path, privacy boundaries and deployment plan.
