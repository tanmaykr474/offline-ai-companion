# Nova privacy and retention

Nova is an offline-first personal companion, not a credential vault. Software
privacy controls do not physically disconnect the microphone, protect against
other applications or encrypt the computer's storage.

## Listening and data flow

When the always-on application is running and unmuted, it captures microphone
audio and uses VAD to identify utterances. Local Whisper transcribes them before
wake-word routing. Saying Nova selects active processing; it is not the boundary
for microphone capture or transcription. Passive storage is separately enabled
with `PASSIVE_MEMORY_ENABLED`; it defaults to false.

Press **M in the focused Windows console** to mute/unmute, or start with
`MIC_ENABLED=false`. Muted and stale input is not dispatched to commands or
memory. STT already admitted can finish, but its result is discarded across a
mute boundary. Previously accepted passive work drains and can save while muted.
Active work admitted before mute may finish; reminders and admitted output may
still speak. See [software mute boundaries](module-1271-software-privacy.md).

| Data | Location / lifetime | Protection |
| --- | --- | --- |
| Microphone frames and VAD buffers | Recorder RAM during an utterance | Canceled generations are discarded; no continuous audio archive |
| Input WAV | New `data/audio/nova-session-*/input.wav` | Removed after STT/dispatch exits, including errors, cancellation and stale mute input |
| Whisper transcript and subprocess output | Python/Whisper RAM during processing | No routine transcript logging; secret-bearing passive speech is rejected before queue acceptance |
| Passive queue | RAM until extraction/draining finishes | Accepted work preserved on shutdown; capture time travels with speech |
| Model prompts and responses | Local Ollama HTTP request/response and process RAM | Loopback destination policy; credential-bearing fields replaced before transmission; no Nova prompt archive |
| Confirmed facts, notes, tasks, reminders | SQLite at configured `DATABASE_PATH` | Persist until explicitly deleted; no automatic age expiration |
| Passive observations, evidence and capture/event times | `passive_memories` in the same SQLite database | Grounding checks, automatic sensitive-data exclusion and configurable visibility expiration |
| Conversation turns | Bounded RAM, default 10 turns; context budget 4,000 characters | Sensitive fields omitted; optional age expiration; no disk chat history |
| Piper text and output WAV | Local subprocess stdin and runtime-owned response/reminder WAV | Known credentials redacted; WAV removed after playback or failure |
| Operational logs / console | stdout/stderr/logging; persistence depends on terminal or external log capture | State, timing, status and error categories only; no routine speech, answer or reminder contents |

The implementation paths are `audio/continuous_recorder.py`, `stt/whisper.py`,
`scripts/always_on_assistant.py`, `memory/passive_worker.py`,
`memory/passive_processor.py`, `core/assistant.py`, `llm/ollama.py`, SQLite
repositories, `core/conversation.py` and `tts/piper.py` under the package.

## What may be remembered

The shared policy lives in `core/privacy_policy.py`.

- Ordinary personal facts and preferences remain usable. Name/city/favorites
  are not blanket-rejected. Existing confirmation and explicit note/task/reminder
  behavior remains available.
- Sensitive personal speech such as diagnoses and medical records is excluded
  from automatic extraction and conversation retention. An explicit request such
  as `Remember that my medical diagnosis is asthma` may save a local note.
  Such explicitly saved information can be recalled and used in local model
  context; it remains plaintext in SQLite and may be spoken aloud.
- Recognized credential secrets are refused even with an explicit storage request
  or confirmation. This includes assigned passwords/passcodes, OTPs/PINs, API and
  authentication tokens, recognizable token/private-key formats and payment
  credentials. Use a credential manager instead. The policy also guards direct
  repository writes, tools, generated fact proposals and pending confirmations.
- Direct confirmed-memory repository methods are explicit storage APIs. They
  prohibit credential secrets but permit sensitive personal content. Passive
  repository writes are automatic and use the stricter policy.
- Legacy secret-bearing rows are preserved, excluded from constructed model
  context, and redacted in assistant/tool responses. Direct database and repository
  access remains trusted operator access; it is not an access-control system.

Secret detection is conservative and heuristic. It can reject benign assignment
phrases, and cannot recognize every unlabeled, encoded or unusually phrased
secret. Whole-field omission avoids leaving adjacent credential fragments.
This does not guarantee that every possible secret will be detected.

## Logs and diagnostics

Routine voice diagnostics no longer print raw input, assistant answers or reminder
contents. Audio recovery, worker, model and scheduler errors report categories,
not exception payloads or tracebacks. Whisper/Piper stderr is not embedded in
raised runtime messages. Performance logging remains numeric/status-only.

For manual diagnostic scripts, `NOVA_PRIVATE_DEBUG=true` explicitly enables
personal transcript/answer/memory output. Recognized credentials are still
redacted. This flag can expose personal information to terminal history, screen
observers or external log collectors; leave it unset for normal use. It does not
enable raw-content output in the always-on runtime. The interactive text UI
(`assistant_test.py`, `llm_test.py`) intentionally displays requested answers,
and the terminal itself echoes typed input; do not type secrets there.

Ollama and subprocesses are separate local software. Their own logs, caches,
telemetry, model configuration and forwarding behavior are outside Nova's
retention control. Runtime Ollama calls reject remote endpoints, redirects and
environment proxies; this is not a network firewall.

## Temporary audio ownership

Each always-on application allocates new session paths via `audio/temporary.py`.
Only those three owned WAV paths are cleaned. Input cleanup waits for its
consumer to finish, so muting does not delete a file while Whisper reads it.
Partial capture, STT/dispatch failures, synthesis/playback failures, Ctrl+C and
ordinary shutdown run cleanup. A cleanup failure logs only its error category
and may leave the file behind.

User-supplied input audio and caller-requested output files are not swept.
Standalone `record_test.py`, `speech_test.py`, `vad_test.py`, voice/TTS demo scripts
and `reminder_demo.py` deliberately use retained `sample-data/audio` paths; they
are manual tools, not the temporary always-on workflow. Earlier `latest_*.wav`
files and existing recordings are left intact. No startup migration or directory
sweep deletes them. Unexpected files in a session directory are also preserved.
Abrupt process termination, OS crashes or power loss can leave session files;
there is no automatic crash-recovery sweep in this module.

Deletion is ordinary file removal, not secure erasure. Filesystem snapshots,
backups, paging and external audio capture may retain copies. SQLite is also
plaintext; protect the Windows account, disk and backups appropriately.

## Retention settings and expiration

Set these in the environment or `.env` before startup:

| Setting | Default | Effect |
| --- | --- | --- |
| `PASSIVE_MEMORY_RETENTION_DAYS` | `0` | Zero disables age expiration; positive integer hides observations at `captured_at + days` |
| `CONVERSATION_RETENTION_SECONDS` | `0` | Zero disables age expiration; positive integer removes old in-memory turns at the exact age boundary |

Negative/noninteger settings fail clearly. Clocks must be timezone-aware and can
be injected for deterministic tests. Passive expiry uses capture time, not event
time, so an old observation about a future event can expire. Expired observations
are excluded before pagination, deterministic recall and model-context building.
Ordinary reads never delete SQLite rows. `list_memories(include_expired=True)`
provides explicit operator access to retained rows. Invalid legacy capture times
are hidden under enabled retention but are not guessed or automatically deleted.

`PassiveMemoryRepository.purge_expired(now=...)` provides the underlying explicit
lifecycle deletion operation. It is a no-op with retention disabled, deletes only
expired passive rows, and is not called automatically. It never deletes confirmed
facts, notes, tasks or reminders. The existing duplicate fingerprint remains in
effect: re-observing an identical retained-but-expired record does not revive it;
after explicit purging, a fresh observation can be stored. No migration changes
existing saved data.

`Clear conversation` clears RAM history and pending confirmation; it preserves
all SQLite memories. Persistent deletion is different. Existing repository
delete/clear APIs remain available; memory-review, correction and deletion
commands are described below. Changes to retention settings take effect on the
next constructed application/repository and do not silently purge records.

## Verification and remaining limits

Automated tests use isolated SQLite databases and audio directories. They cover
automatic/explicit storage, legacy rows, prompt/output/history redaction, error
logs, queue acceptance, mute boundaries, owned audio cleanup, deterministic age
boundaries and preservation of confirmed memory/reminders. Existing tests cover
accepted-work draining and grounding. No physical microphone/speaker validation,
credential-vault encryption or Raspberry Pi deployment is claimed here.

Module 12.7.3 verification: **687 tests passed in 74.49 seconds**, preserving all
613 baseline tests and adding 74 privacy regression cases. The focused suite
passed 343 tests. Existing test files were not modified for this module.

## Files changed in Module 12.7.3

- Shared policy and configuration: `core/privacy_policy.py`, `config.py`.
- Memory/prompt boundaries: `core/assistant.py`, `core/conversation.py`,
  `memory/repository.py`, `memory/passive_repository.py`,
  `memory/passive_processor.py`, `memory/passive_worker.py`,
  `memory/intelligent_extractor.py`, `tools/memory_tools.py`, `llm/ollama.py`.
- Audio and diagnostic lifecycle: `audio/temporary.py`, `audio/recovery.py`,
  `stt/whisper.py`, `tts/piper.py`, `scheduler/reminder_scheduler.py`,
  `scripts/always_on_assistant.py`.
- Manual-script diagnostics: `scripts/assistant_test.py`, `scripts/llm_test.py`,
  `scripts/memory_test.py`, `scripts/reminder_demo.py`, `scripts/speech_test.py`,
  `scripts/talking_assistant_test.py`, `scripts/vad_test.py`,
  `scripts/voice_assistant_test.py`, `scripts/voice_llm_test.py`.
- Regression tests: `tests/unit/test_privacy_retention.py`,
  `tests/integration/test_privacy_audio_lifecycle.py`.
- Documentation: this file and the superseded logging note in
  `docs/module-1271-software-privacy.md`.

Package paths above are relative to `src/offline_ai_companion` unless prefixed
with `scripts`, `tests` or `docs`.

## Memory review, correction and deletion (Module 12.7.4)

Prefix each spoken command and confirmation with **Nova**. In the text UI, use
the commands directly. Bare speech without wake activation remains passive input.

| Command | Behavior |
| --- | --- |
| `What do you remember about me?` / `Show my saved memories` | Review confirmed facts and nonexpired passive observations |
| `List my preferences` | Review confirmed favorite/preference facts and passive preferences |
| `What facts have you saved about me?` / `Show my saved facts` | Review confirmed facts only |
| `Show my passive memories` | Review nonexpired passive observations only |
| `Show my saved memories page 2` | Repeat any review with an explicit page number; three results per page |
| `Show memory number 5` / `Show passive:5` | Inspect passive observation 5 with bounded evidence and timestamps |
| `Show fact:user.birthplace` | Inspect a confirmed fact by its stable key |
| `Delete memory number 5` / `Delete passive:5` | Propose deletion of only passive observation 5 |
| `Delete fact:user.birthplace` | Propose deletion of only that confirmed fact |
| `Forget that I love playing cricket` | Match the existing deterministic statement; ask for an ID if ambiguous |
| `Forget my birthplace` / `Remove my favorite food preference` | Propose the confirmed fact if one exists; otherwise require one matching passive observation |
| `My favorite food is now pizza` / `Update my birthplace to Delhi` | Propose a confirmed correction; captured observations/evidence stay unchanged |
| `Actually, I prefer football instead of cricket` | Use a unique confirmed preference topic first, then a grounded passive favorite topic; a unique activity observation can support a new confirmed preferred-activity fact |
| `Forget everything you remember about me` | Propose deletion of confirmed facts and all passive observations, including expired ones |
| `Clear my passive memories` | Propose deletion of all passive observations, including expired ones |
| `Delete all saved facts` | Propose deletion of confirmed facts only |

`Memory number` refers specifically to the passive table. Numeric IDs are not
global: note 5, task 5 and passive observation 5 can all exist simultaneously.
Typed IDs such as `passive:5` and `fact:user.birthplace` prevent cross-category
selection. Review output distinguishes confirmed facts from observations,
attributes unknown speech to an unidentified speaker, limits previews and pages,
and filters recognized credentials. It does not assert that a passive speaker
was you. Review commands make no persistent writes and are not added to history.
Notes, tasks and reminders retain their separate existing review commands.

All new persistent changes require confirmation. Nova states the target/scope
and asks for **Yes** or **No**, with a 120-second default deadline. Exact `confirm`
also accepts; `yes delete`/`confirm deletion` and `yes update`/`confirm update`
must name the correct action. `No` or `Cancel` leaves records untouched. Compound
replies, `yeah` and `go ahead` do not authorize these operations. Existing regular
fact-confirmation reply vocabulary is preserved, with the same default deadline.

There is at most one active workflow: a new management request clears a pending
fact proposal, and an unrelated question or new request cancels a pending
management operation. Repeating a command asks again; it does not confirm itself.
Pending operations exist only in RAM and are lost on restart. A late/repeated Yes
does not execute a previous operation. Existing conversation-reset commands also
cancel pending changes. Recognized secret-bearing requests cancel pending changes
and retain the credential refusal policy.

Deletion and explicit corrections use a SQLite transaction. Before writing, Nova
rechecks the reviewed rows under a write lock. Changes to a selected record, or
to the complete requested bulk scope, cancel the operation and require a new
request. Failure rolls back the entire transaction. Bulk operations never silently
include notes, tasks, reminders or conversation history; the confirmation states
those exclusions. Atomic changes across different SQLite databases are refused.

Corrections replace the value of one confirmed fact, preserving its unique key.
They do not rewrite historical evidence or automatically delete conflicting
observations. Deleting a confirmed fact can therefore reveal an older passive
observation on subsequent recall; the deletion prompt explicitly warns that
history remains. Activity preference corrections do not imply that a historical
love/enjoyment statement was false. Ask `What activities do I prefer?` for the
confirmed preferred activity. Unresolvable or multiple preference topics require
an explicit `Update my ... to ...` command rather than a guess.

Explicit typed-ID deletion can remove a retained expired record; ordinary review
still hides it. Future or previously accepted background speech may create new
observations after a deletion. These commands are not a permanent collection
opt-out: mute/disable passive collection, allow accepted work to drain, then
repeat the deletion if that is the desired boundary. No speaker authentication
is introduced; anyone with access to the active interface can issue and confirm
commands. Physical-device behavior remains subject to manual validation.

SQLite deletion is logical removal, not guaranteed secure erasure of database
pages, WAL/journal files, backups, filesystem snapshots or storage media.

Module 12.7.4 verification: 742 tests passed in 79.27 seconds, including 55 new memory-management regression and mocked voice integration cases. Physical microphone and speaker validation remains separate.

## Task and reminder changes (Module 12.7.5)

Explicit task/reminder commands use the shared credential policy. Review is
paginated and filters legacy credential contents. Changes require RAM-only,
expiring confirmations and transactionally recheck the reviewed record. They do
not include facts, passive observations, notes or conversation history. Background
task/event observations are never actionable scheduling commands. Reminder
delivery claims are persisted only as operational ownership tokens and expiry
times alongside the existing reminder; they do not contain transcripts. SQLite
deletion remains logical deletion, with the secure-erasure limits above.

See [TASKS_AND_REMINDERS.md](TASKS_AND_REMINDERS.md) for available commands,
local timezone configuration, confirmation and crash-recovery limitations.

## Windows audio diagnostics (Module 12.8A)

`NOVA_AUDIO_DIAGNOSTICS=true` opts into stage/event labels and durations without
audio or text content. Failure categories and numeric overflow warnings are safe
by default. `scripts/audio_diagnostics.py` queries metadata/format support only;
device names require explicit `--include-device-names` and may be personal.
It neither records nor plays audio and does not read stored memories.

Capture and output are serialized; playback cancels old capture generations and
stale STT results, including after mute/unmute and completed shutdown. Accepted
passive work still drains. Overflowed utterances are discarded rather than stored
from incomplete audio. This is software isolation, not hardware-enforced privacy
or acoustic echo cancellation. Delayed echo and physical device behavior require
the [Windows manual checklist](WINDOWS_AUDIO_VALIDATION.md).

## Experimental interruption (Module 12.8B)

Both `NOVA_EXPERIMENTAL_INTERRUPTION` and `NOVA_SPOKEN_INTERRUPTION` default to
false. Experimental mode enables console S cancellation. The separate spoken
setting permits microphone monitoring during active processing and speech output.
Only exact wake-prefixed stop is recognized; monitor input never reaches Assistant,
memory, tasks, reminders or conversation history. Local Whisper uses owned transient
WAV files removed after each clip and shutdown. Mute invalidates in-flight clips.

The monitor has no acoustic echo cancellation. Echo may cause a false stop, but
cannot create a new command or passive memory. Stop transcripts are not logged.
Interrupted audio is not acknowledged as completed reminder speech; that reminder
stays pending with a 60-second deferral. Committed notes, tasks, facts and reminders
remain saved even if their acknowledgment is interrupted. Generated conversation
text can already be present before playback interruption. Accepted passive work
continues draining. Ollama remains local-only; cancellation suppresses its response
without guaranteeing server inference has stopped.

See [the interruption checklist](WINDOWS_INTERRUPTION_VALIDATION.md). New physical
interruption scenarios have not been executed; use headphones for initial testing.

## Runtime reliability diagnostics (Module 12.9)

`NOVA_RUNTIME_DIAGNOSTICS=true` enables periodic numeric resource/health snapshots;
the default is false and `NOVA_RUNTIME_INTERVAL` defaults to 30 seconds. Fixed
counter/timing aggregates stay in constant-size memory. No speech, SQL, record
content, exception messages or process command lines are sampled. Snapshots are
written to the local console only; use bounded rotation if redirecting to disk.

The optional synthetic soak runner uses temporary databases and generated audio,
never production memories or physical input. Only its numeric report persists.
Its normal file cleanup and SQLite deletion are not secure erasure. Existing saved
data is preserved; no retention policy or journal-mode migration was added.
See [LONG_RUNNING_VALIDATION.md](LONG_RUNNING_VALIDATION.md).
