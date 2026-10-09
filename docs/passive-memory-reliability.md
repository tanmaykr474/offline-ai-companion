# Passive memory shutdown and transcript filtering

The passive worker stops accepting new transcripts when `stop()` is called,
then processes all accepted items before exiting. `stop(timeout=5)` returns
`False` if processing is still in progress. Calling it again continues waiting;
it does not discard the queue or terminate a thread. The always-on script waits
for this drain before printing `Nova stopped.`

The worker is non-daemon so ordinary process exit cannot silently abandon
accepted work. Shutdown can take longer when multiple model requests are queued.
Forced process termination or power loss can still lose the in-memory queue.
Processing failures are reported and subsequent queued items continue; failed
extractions do not create memories or automatically retry.

Passive extraction uses a dedicated Ollama client with no automatic retries and
`PASSIVE_MEMORY_LLM_TIMEOUT=30` seconds by default. Set this environment variable
before starting Nova to allow more time on slower hardware. This is an HTTP
request timeout, not a guarantee of an exact total shutdown duration. Active
conversation retains its existing timeout and retry policy.

The voice loop, worker and processor use the shared transcript filter. Square
bracket annotations and recognized parenthesized audio captions are removed.
Caption-only output such as `[XBOX SOUND] [MUSIC]` is ignored before queueing.
Actual speech alongside captions is retained, including wake activation.

Automated tests use injected models and temporary SQLite databases. They cover
queue draining under slow and failed processing, repeated shutdown waits,
caption filtering, and memory extraction. They do not verify live microphone,
Whisper, Piper or Raspberry Pi timing.
