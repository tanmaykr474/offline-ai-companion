# Hackathon jury cross-questions

48 repository-grounded questions. Package paths below are under `src/offline_ai_companion/` unless explicit. Hardware and benchmark qualifications are deliberate.

## 1. [Innovation] What is actually new about Nova?

The integration of local speech, persistent memory, grounded passive observations and deterministic tools with shared mute controls. It reuses existing models. No new trained model or acoustic wake algorithm is claimed.

Evidence: `core/assistant.py; memory/passive_processor.py`.

## 2. [Innovation] Why use a small local model?

Llama 3.2:1b is the configured default and fits the project’s constrained-device intent. The repository provides thread/context bounds, but does not prove Pi latency or RAM sufficiency.

Evidence: `config.py; deployment/raspberry-pi/nova.env.example`.

## 3. [Architecture] Describe the complete voice path.

Mic capture and RMS VAD produce a WAV. whisper.cpp transcribes it. Activation routes the text to tools/recall/chat or optional passive storage. Piper synthesizes an active answer and sounddevice plays it.

Evidence: `scripts/always_on_assistant.py`.

## 4. [Architecture] Is Nova a real acoustic wake-word detector?

No. WakeDetector regex-matches the beginning of Whisper’s transcript. The recorder and STT precede wake filtering, so it is not a low-power keyword engine.

Evidence: `core/wake_detector.py; stt/whisper.py`.

## 5. [Architecture] What happens if I say only Nova?

It opens an eight-second window for one follow-up utterance. A command in the same utterance executes directly. Explicit wake speech takes precedence and mute resets activation.

Evidence: `core/activation_controller.py; scripts/always_on_assistant.py`.

## 6. [Architecture] Does always-on mean continuous recording without gaps?

No. The normal voice loop is sequential and half-duplex. Listening resumes after processing/output. Input closes for playback and a settling interval.

Evidence: `audio/half_duplex.py; scripts/always_on_assistant.py`.

## 7. [Architecture] Which VAD model do you use?

No neural VAD. RMS energy is compared with threshold 0.018 by default. Continuous capture adds pre-roll, minimum speech and silence/maximum-duration bounds.

Evidence: `audio/vad.py; audio/continuous_recorder.py`.

## 8. [Offline] Does it work with Internet disconnected?

The core can, after models/dependencies are provisioned locally and Ollama runs locally. Weather/news need Internet and are disabled by default. We still require a physical disconnection rehearsal.

Evidence: `llm/local_endpoint.py; tools/online_tools.py`.

## 9. [Offline] Why is there HTTP in an offline assistant?

Ollama is a separate local process accessed over loopback HTTP. This is local IPC through an API, not a cloud request. Remote URLs, redirects and environment proxies are blocked.

Evidence: `llm/local_endpoint.py; llm/ollama.py`.

## 10. [Offline] Does setup itself require Internet?

Yes, explicit OS/package/model provisioning does. Runtime does not automatically download models. Offline operation starts after provisioning.

Evidence: `deployment/raspberry-pi/setup.sh; models.sh`.

## 11. [Privacy] What is stored when nobody says Nova?

By default passive memory is disabled, so recognized background text is not queued for memory. If enabled, eligible speech can become grounded local observations without a spoken response.

Evidence: `config.py; memory/passive_worker.py`.

## 12. [Privacy] Does disabling passive memory stop transcription?

No. STT precedes transcript wake detection. Use software or physical mute to deny new capture and dispatch.

Evidence: `scripts/always_on_assistant.py; core/privacy.py`.

## 13. [Privacy] Does the physical switch cut microphone power?

No. GPIO informs the software privacy gate. Polling and cancellation cannot establish zero-latency electrical isolation. A power/data disconnect would need additional hardware.

Evidence: `core/hardware.py`.

## 14. [Privacy] What happens to queued work after mute?

New/stale input is rejected by generations and guards. Work already accepted may finish and passive work drains. Committed facts/tasks/reminders remain.

Evidence: `core/privacy.py; memory/passive_worker.py`.

## 15. [Privacy] Are recordings immediately and permanently destroyed?

Owned runtime WAVs are normally removed after their consumer finishes or on cleanup. Abrupt termination can leave files. Removal is not secure erasure, and manual scripts retain sample recordings.

Evidence: `audio/temporary.py; docs/PRIVACY.md`.

## 16. [Privacy] Is memory encrypted?

No. SQLite is plaintext. Private file modes/umask and account protection help, but encryption and secure deletion are absent.

Evidence: `memory/database.py; deployment/raspberry-pi/systemd/nova.service.in`.

## 17. [Memory] How do you distinguish memory from hallucination?

Confirmed facts outrank observations. Passive candidates need supported assertion evidence, subject/category and time grounding. Recall rechecks evidence and saved rows. General model chat can still hallucinate.

Evidence: `memory/passive_processor.py; memory/hybrid_retriever.py`.

## 18. [Memory] Do passive observations belong to the device owner?

No. They are attributed to an unidentified speaker. There is no diarization or voice authentication, and recall states this uncertainty.

Evidence: `memory/passive_retriever.py; memory/hybrid_retriever.py`.

## 19. [Memory] Is semantic recall based on embeddings?

No. It uses a small concept/synonym lexicon with sparse cosine ranking over bounded SQLite candidates after exact relation checks.

Evidence: `memory/hybrid_retriever.py`.

## 20. [Memory] Can it recall arbitrary paraphrases?

Coverage is limited by the concept vocabulary and evidence rules. Unknown relations, qualifiers and dates can return unavailable rather than a guessed personal fact.

Evidence: `memory/hybrid_retriever.py; docs/SEMANTIC_MEMORY.md`.

## 21. [Memory] Does every memory write need confirmation?

No. Proposed ordinary facts and management changes have confirmations, but legacy name setting, explicit notes/tasks and reminder creation can write directly. Passive observations have policy checks rather than voice confirmation.

Evidence: `core/assistant.py; tools/memory_tools.py; tools/lifecycle.py`.

## 22. [Memory] Can I correct or delete saved memory?

Yes, scoped commands review facts/passive records and propose corrections/deletions with expiring confirmations and transactional rechecks. Deleting a fact preserves separate passive history.

Evidence: `memory/management.py`.

## 23. [Memory] Does retention actually delete old rows?

Read-time passive expiry hides old observations. Explicit purge removes them. Default retention 0 means no age expiry. Confirmed memory is not automatically deleted.

Evidence: `memory/passive_repository.py; config.py`.

## 24. [Tools] Can background speech schedule a reminder?

No. Passive task/event records are observations. Only explicit active tool commands create actionable tasks and reminders.

Evidence: `memory/passive_processor.py; tools/lifecycle.py`.

## 25. [Tools] Can the LLM run shell commands?

No arbitrary shell-agent tool exists. QueryRouter selects supported deterministic memory/lifecycle and opt-in weather/news handlers.

Evidence: `router/query_router.py; core/assistant.py`.

## 26. [Tools] What are the online integrations?

Open-Meteo geocoding/current modeled weather/daily forecast and NewsAPI headlines. They require explicit enablement/provider configuration and live validation is unperformed.

Evidence: `tools/online_tools.py; docs/ONLINE_TOOLS.md`.

## 27. [Security] What personal information leaves for weather/news?

Explicit/configured location or allowed configured news topic and provider authentication as needed. The tools do not send memory/history, and answers bypass Ollama and memory storage.

Evidence: `tools/online_requests.py; tools/online_tools.py`.

## 28. [Security] How do you protect against prompt injection?

Deterministic tools do not trust model instructions, passive output is grounded, memory is marked data in chat prompts, and provider answers bypass the LLM. These controls do not make general chat immune to injection.

Evidence: `core/assistant.py; memory/passive_processor.py; tools/online_tools.py`.

## 29. [Security] Can Nova store passwords?

Recognized credential patterns are refused at several boundaries and omitted from context/output. Regex detection is heuristic, so it is not a credential vault or complete data-loss prevention system.

Evidence: `core/privacy_policy.py; memory/repository.py`.

## 30. [Security] Who can issue destructive voice commands?

Anyone with access to the active voice/text interface can issue and confirm supported changes. Confirmations guard intent/concurrency, not identity. Authentication is future work.

Evidence: `memory/management.py; tools/lifecycle.py`.

## 31. [Reliability] How are reminder duplicates prevented?

SQLite claims and renewable leases avoid competing active deliveries. Successful playback must be acknowledged before completion. A crash between sound and durable completion can still repeat delivery.

Evidence: `scheduler/reminder_scheduler.py; memory/repository.py`.

## 32. [Reliability] Does microphone mute also silence reminders?

No general silent-output mode is implemented. The loop checks pending reminders before checking input mute, so microphone privacy does not promise speaker silence.

Evidence: `scripts/always_on_assistant.py`.

## 33. [Reliability] What if a device stops sending audio?

After the stall timeout, capture raises a recoverable error. Recovery logs a sanitized category, waits and retries. Overflowed or dropped-block utterances are discarded.

Evidence: `audio/continuous_recorder.py; audio/recovery.py`.

## 34. [Reliability] Can you interrupt a response?

Experimental console cancellation and optional exact wake+stop monitoring exist. Child STT/TTS and owned playback support cancellation, but Ollama inference may continue and the monitor has recognition gaps.

Evidence: `core/cancellation.py; audio/stop_monitor.py`.

## 35. [Reliability] Is full-duplex conversation implemented?

No. Half-duplex is the default, and the experimental stop monitor is narrower than general barge-in. No acoustic echo cancellation exists.

Evidence: `audio/half_duplex.py; audio/stop_monitor.py`.

## 36. [Performance] What latency can you substantiate?

Historical Windows file-input measurements report about 2.48 seconds median for five recall responses without capture/playback. They are not full physical latency, Pi measurements or fresh results from this audit.

Evidence: `docs/module-1266-validation-results.md`.

## 37. [Performance] How much memory and CPU does Pi need?

The profile targets constrained resources with tiny.en, 1B LLM, two threads and 1,024 context. Actual Pi RAM, CPU, temperature and end-to-end timing remain unmeasured here.

Evidence: `deployment/raspberry-pi/nova.env.example; README.md`.

## 38. [Scalability] What happens with a large memory archive?

Recall bounds candidates/results and lock waits, but concept coverage is limited. General-chat context includes all facts, so total prompt size can grow. Large-archive and multi-user performance are not validated.

Evidence: `memory/hybrid_retriever.py; core/assistant.py`.

## 39. [Scalability] Can several users share the companion?

There is no user-account isolation or voice identity. The current design is a single local companion; multi-user permissions and separate memory namespaces need new work.

Evidence: `memory/database.py; core/assistant.py`.

## 40. [Deployment] Have you actually deployed to Pi 5?

The repository has ARM64 provisioning, preflight, local GPIO and systemd code. Documentation explicitly says physical GPIO, Linux audio, boot/recovery and ARM64 inference have not been validated.

Evidence: `docs/DEVELOPMENT_STATUS.md; deployment/raspberry-pi/README.md`.

## 41. [Deployment] How does it start after reboot?

Installed systemd units can be explicitly enabled. Nova starts muted and a stable physical muted-to-listen switch cycle authorizes capture. Installation alone does not enable services.

Evidence: `core/hardware.py; deployment/raspberry-pi/install-service.sh`.

## 42. [Deployment] What happens if GPIO breaks?

Read/write faults latch software and physical mute until restart. No automatic recovery unmute occurs. An LED fault can prevent a reliable red/off indication.

Evidence: `core/hardware.py`.

## 43. [Deployment] Why can shutdown take a long time?

Accepted passive work drains, and Nova’s systemd stop timeout is infinite to avoid killing it. A stalled shutdown needs operator diagnosis. This is an explicit reliability tradeoff.

Evidence: `memory/passive_worker.py; deployment/raspberry-pi/systemd/nova.service.in`.

## 44. [Evaluation] What do the tests prove?

They cover routing, persistence, privacy gates, failure recovery, lifecycle and mocked voice/GPIO/service policies. The historical latest checkpoint reports 1,278 passing tests. They do not prove physical Pi operation.

Evidence: `tests/; docs/DEVELOPMENT_STATUS.md`.

## 45. [Evaluation] What is your biggest current limitation?

The target Pi and sustained physical workload remain unvalidated, and sequential audio/STT-based wake handling impose gaps and cost. Privacy also lacks identity, encryption and electrical isolation.

Evidence: `docs/DEVELOPMENT_STATUS.md; core/hardware.py`.

## 46. [Future] What would you improve first?

Validate the physical Pi and long-running workload, repair deployment/entry-point/documentation gaps, then measure acoustic wake/VAD improvements and stronger consent, authentication and storage controls.

Evidence: `repository-evaluation.md recommendations`.

## 47. [Future] Would a larger model solve everything?

No. It may improve language quality but increases local resource demand and does not fix acoustic capture, identity, electrical mute, database privacy or service validation.

Evidence: `config.py; core/hardware.py; memory/database.py`.

## 48. [Demo] How will you show that memory is persistent?

Use an isolated demo SQLite path, save a synthetic fact/note, restart with the same path and recall it. Never demonstrate against the personal production database.

Evidence: `memory/database.py; scripts/always_on_assistant.py`.
