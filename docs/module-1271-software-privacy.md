# Module 12.7.1 — Software mute and local-only Ollama

## Windows controls

Start `scripts/always_on_assistant.py` normally. Press **M** in the focused
Windows console to toggle software microphone mute; Ctrl+C still shuts down.
This console key is not a global system hotkey. Programmatic callers can use
`set_muted(True)`, `set_muted(False)` or `toggle_mute()` on the application.
`MIC_ENABLED=false` starts the application muted; an explicit unmute can enable
capture afterward. `PASSIVE_MEMORY_ENABLED` remains a separate storage option.

Mute changes print only ON/OFF and state names. The application no longer prints
raw STT transcripts or active command input. Module 12.7.3 subsequently removed
active answer/reminder content and exception payloads from routine diagnostics;
see [the current privacy policy](PRIVACY.md). Performance logs continue to
contain only numeric timings.

## Defined mute boundary

- No new recording is admitted while muted. The existing input stream receives
  a cancellation signal, ignores further callbacks and closes when the recorder
  exits its loop. Driver closure is not a physical microphone disconnection.
- An in-flight utterance is discarded as a whole. Cancellation is latched to
  its generation, so a quick mute/unmute cannot reactivate old frames or input.
- Completed recordings that cross a mute boundary are not submitted to STT.
- STT admitted before mute may finish its already-recorded input. Its result
  is discarded before logging, routing or queue submission if mute intervenes,
  even when unmute follows before STT returns. Whisper is not forcibly killed.
- Passive queue submission and mute changes share an acceptance lock. Work
  accepted before mute, including queued and ongoing extraction, continues and
  may save memories while muted. New submissions are rejected while muted.
  Muting does not clear the queue; shutdown still drains accepted work.
- Active commands admitted before mute may finish and retain their side effects.
  A response returned after a mute transition is withheld. Speech/output already
  admitted before mute may finish; this is input mute, not a speaker silence or
  active-request cancellation feature. Previously sent local prompts cannot be
  retracted. No new active command is admitted from a stale transcription.
- Mute transitions reset the wake follow-up window. Unmuting starts a fresh
  recording generation. Reminders remain enabled and may speak while muted.

This provides application-enforced input privacy. It does not secure against
other programs, the OS, a compromised local model server or physical capture.
Previously saved WAV files and memories are not erased by muting.

## Local-only model policy

The runtime Ollama client accepts HTTP(S) origins using `localhost`, literal
IPv4 loopback addresses in `127.0.0.0/8`, IPv6 `::1`, or IPv4-mapped loopback
addresses. Localhost is pinned to `127.0.0.1` without DNS resolution; mapped IPv6
loopback is normalized to IPv4. IPv6 listeners can use `http://[::1]:11434`.
Ports must be valid. TLS verification stays enabled; localhost HTTPS retains
the localhost SNI identity and Host header while connecting to literal loopback.

Remote/private-network hosts, wildcard bind addresses, other hostname aliases,
ambiguous IP notation, credentials, paths, query strings, fragments, scope IDs
and malformed URLs are rejected before transmission. There is no remote-host
opt-out in this module. The host is revalidated before every request.

Environment proxies are disabled for the built-in client. Redirect following is
disabled per request, including injected clients whose default enables redirects.
All 3xx responses are rejected, including redirects to another local endpoint.

Injected real HTTPX clients must use `trust_env=False` and have no configured
mounts/proxies, request hooks or auth flows. These restrictions prevent standard
HTTPX configuration from rerouting prompts. Injected custom transports/clients
are trusted application code: malicious code could open its own network connection.
The policy restricts the client destination; it cannot prevent a local server
from forwarding data. Standalone health checks still have their existing narrower
hostname allowlist; runtime loopback variants are covered by the new policy tests.

## Automated and physical verification

Tests use temporary SQLite databases and mocked devices/transports. They cover
mute/unmute, stale generations, in-flight recordings, STT completion/error,
accepted queue draining, submission races, active-response withholding, initial
configuration, console controls, hostname/IPv4/IPv6 rejection, redirects,
environment proxies, injected-client restrictions and HTTPS identity metadata.
Existing tests remain unchanged.

Physical Windows checks remain required:

1. Press M while listening: observe MUTED, speak both passive and wake statements,
   and verify neither reaches STT, commands or storage. Press M again and verify
   a fresh utterance succeeds.
2. Toggle during an utterance and during Whisper processing. Rapidly unmute;
   verify the earlier utterance is not answered or saved.
3. Queue background speech before muting. Verify it can complete while new muted
   speech is ignored, and that Ctrl+C drains accepted work.
4. Verify console key handling on the actual terminal, device closure latency,
   microphone reconnection and Ctrl+C while muted. No physical-device or local
   HTTPS certificate handshake is claimed as verified by the mocked tests.

Module 12.7.2 and Raspberry Pi deployment are outside this change.
