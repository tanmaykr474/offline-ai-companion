# Raspberry Pi 5 preparation — Module 12.12A

Preparation is implemented and tested with mocks on Windows. **Deployment,
Linux device operation, model inference, RAM capacity and thermal behavior have
not been validated on a Raspberry Pi.** Windows audio/interruption tests passed;
multi-hour physical reliability testing remains deferred. No GPIO wiring or
systemd auto-start is included.

Windows verification: 70 new deployment cases; focused deployment/model/mute/
audio suite 182 passed; complete suite **1,194 passed in 89.43 seconds**. All six
Bash scripts passed syntax parsing. No install, model provisioning or target
binary execution was performed as part of these Windows checks.

## Compatibility matrix

| Component | Existing implementation / gap | Pi preparation / required target check |
|---|---|---|
| OS / Python | Windows Python 3.13; project requires `>=3.13,<3.14` | Supported 64-bit Raspberry Pi OS, preferably current Trixie Lite; confirm `aarch64`, 64-bit Python 3.13. Bookworm Python 3.11 is unsupported without a separately reviewed Python installation. |
| Dependencies | Root requirements.txt contains a Windows editable path and platform freeze | Separate pinned Pi requirements; binary-wheel installation fails on missing ARM64 wheels. Do not copy the Windows venv. |
| whisper.cpp | Windows `.exe`; existing ggml tiny.en model and PCM16 WAV input | CPU ARM64 build pinned to v1.7.6; executable header checked; test actual CLI inference and shared libraries on target. Windows binary version is not assumed. |
| Piper | Windows standalone executable; ONNX voice | Explicit Pi-only piper-tts 1.8.0, ONNX Runtime 1.31.0, `exec` CLI wrapper. ONNX and matching JSON required. ARM64 wheel availability does not establish voice compatibility or performance. |
| Ollama | Loopback-only HTTP client, Llama 3.2 1B | Explicit version/checksum ARM64 archive, local prefix and foreground server; verify dynamic libraries, model load and CPU inference. No automatic upgrade, install service or cloud fallback. |
| Audio | sounddevice/PortAudio and soundfile; numeric device indices; 16 kHz input / 22.05 kHz playback format checks | Install PortAudio/libsndfile; enumerate Linux devices. USB / ALSA / PipeWire defaults and rate conversion need actual tests. Indices can change after reconnect. |
| Console mute | Windows msvcrt hotkeys | Linux interactive terminal uses `M` + Enter; `S` + Enter only when experimental interruption enabled. No raw terminal mode changes. Software mute is not physical disconnection. |
| Subprocesses | Owned subprocess timeout/terminate/kill, portable Python APIs | Piper wrapper uses exec to preserve child ownership; test timeouts, interruption and shutdown on Linux. No forced shared-thread termination. |
| Paths / storage | Windows paths; cwd-relative generated WAVs; SQLite root-relative config | Linux defaults, Windows-path rejection, private DB/audio directories and umask 077. Runtime-owned WAV cleanup preserved. |
| Diagnostics | Numeric resource metrics include Linux `/proc` support; audio checks privacy-safe by default | Metadata checks without capture/inference; model inventory GET on loopback only, no prompts; error check names only. Physical validation remains separate. |
| GPIO | No runtime dependency or wiring implemented | Intentionally deferred. No gpiozero/RPi.GPIO packages installed. |
| Online tools | Opt-in Open-Meteo / NewsAPI | Disabled in Pi profile. Ollama remains local even when online tools are later explicitly enabled. |

Compatibility references: [Raspberry Pi OS](https://www.raspberrypi.com/software/operating-systems/),
[whisper.cpp build and ARM support](https://github.com/ggml-org/whisper.cpp/tree/v1.7.6),
[Ollama Linux ARM64 installation](https://docs.ollama.com/linux),
[Ollama server settings](https://docs.ollama.com/faq),
[Piper CLI](https://github.com/OHF-Voice/piper1-gpl/blob/v1.8.0/docs/CLI.md),
[Piper 1.8.0 distributions](https://pypi.org/project/piper-tts/1.8.0/#files),
[ONNX Runtime 1.31.0 distributions](https://pypi.org/project/onnxruntime/1.31.0/#files),
[PortAudio installation](https://python-sounddevice.readthedocs.io/en/latest/installation.html).
Check the pinned audio wheels on the target during setup. No dependency versions
or Python requirements are changed for Windows. Piper's maintained Pi package is
GPL-3.0; review its license and the lessac voice MODEL_CARD before redistribution.

## Provisioning on the Pi

Use a fresh Linux checkout in a user-owned directory such as `~/nova`. Transfer
source through Git or an archive; exclude `.venv`, `.env`, Windows binaries and
private databases/audio. Do not run assistant or provisioning scripts as root.
If transferring scripts from Windows, ensure LF line endings; deployment-local
`.gitattributes` records this for Git checkouts.

```bash
cd ~/nova
uname -m                          # must be aarch64
python3 --version                 # must be 3.13.x
bash deployment/raspberry-pi/setup.sh --system-deps
```

Setup uses sudo only for apt packages, not Nova. It creates the venv, installs
the separate pinned audio/Piper dependencies and project, creates private
directories, and copies `nova.env.example` only if `nova.env` does not exist.
Reruns preserve existing configuration and database contents. Permission changes
to these dedicated directories and environment file are intentional. Existing
database files must be owner-only (`chmod 600 data/private/companion.db` after
an intentional migration); preflight refuses broad permissions rather than
rewriting or reading saved memories. Do not put user recordings in the runtime
audio directory.

Install Ollama with an explicitly reviewed published version and trusted SHA256
from the [official releases](https://github.com/ollama/ollama/releases).
Use a version publishing `ollama-linux-arm64.tar.zst`; older `.tgz` releases are
not handled by this script. One explicitly selectable provisioning version is
[0.40.2, whose ARM64 asset and SHA256 were checked against official metadata](https://github.com/ollama/ollama/releases/expanded_assets/v0.40.2).
This is a Pi provisioning candidate, not a tested upgrade to Windows or a Pi
runtime compatibility claim:

```bash
bash deployment/raspberry-pi/install-ollama.sh 0.40.2 92b3ef3d5e10f5849273bfa1345000f2a8ce8bc834e95061ff5b9df5d08e3c3f
bash deployment/raspberry-pi/ollama-serve.sh
```

The archive is downloaded and verified before extraction into a local prefix;
an existing different install is refused. Keep this foreground server terminal
open. Verify `deployment/raspberry-pi/ollama/bin/ollama -v` on target. If local
prefix shared-library discovery fails, inspect the official manual layout before
proceeding; this preparation has not validated the binary loader on Pi. The
upstream automatic installer is deliberately not invoked because it can install
an auto-start service. Archive installation does not pull a model.

In a second terminal, explicitly provision the models (Internet required):

```bash
cd ~/nova
bash deployment/raspberry-pi/models.sh --provision
```

This builds CPU whisper.cpp with two build jobs, obtains ggml tiny.en and the
lessac-medium ONNX/config pair through the official download tools, then pulls
Llama 3.2 1B from the local Ollama server only if absent. Existing nonempty model
files are reused; partial voice or empty Whisper files are refused for manual
inspection. Upstream model tags/download URLs can change; locally recorded
SHA256 values document installed artifacts, not independently verified publisher
signatures. Retain known-good models for subsequent offline provisioning. No
model downloads occur during normal assistant startup or preflight. Package,
source, archive and model provisioning intentionally use Internet access.

Expected layout:

```text
nova/.venv/bin/python
nova/deployment/raspberry-pi/nova.env           # 600, not committed
nova/deployment/raspberry-pi/whisper.cpp/build/bin/whisper-cli
nova/deployment/raspberry-pi/ollama/bin/ollama
nova/deployment/raspberry-pi/ollama/lib/ollama/ # upstream archive libraries
nova/deployment/models/ggml-tiny.en.bin
nova/deployment/models/piper/en_US-lessac-medium.onnx[.json]
nova/data/private/companion.db                # local SQLite, 600
nova/data/private/ollama/                     # model storage
nova/data/audio/                              # runtime-owned temporary WAVs
```

## Preflight, audio and foreground startup

```bash
.venv/bin/python -m offline_ai_companion.core.pi_deployment --audio --ollama
NOVA_ENV_FILE=deployment/raspberry-pi/nova.env .venv/bin/python scripts/audio_diagnostics.py --include-device-names
.venv/bin/python -m offline_ai_companion.core.pi_deployment --start
```

Preflight requires Linux ARM64 / Python 3.13 / non-root user, secure environment,
private writable layout, executables, model/config presence, imports, bounded
profile settings and loopback Ollama. Optional audio checks validate formats
without opening recording/playback streams. Optional Ollama checks use a bounded
local GET /api/tags with proxies and redirects disabled; they do not load models.
Startup includes both checks and requires a terminal for mute controls. Failures
return a nonzero status and fixed check names, without exception payloads, paths,
transcripts or secrets. Headers/file/import checks cannot establish binary/model
correctness; physical inference is required. Environment is parsed as data,
without interpolation or shell sourcing. Explicit process environment overrides
file values; remove conflicting Windows environment settings before using Pi.
Set `REMINDER_TIMEZONE` to the intended IANA timezone before scheduling; the
profile explicitly starts with the existing Asia/Kolkata default.

Set `NOVA_INPUT_DEVICE` / `NOVA_OUTPUT_DEVICE` in `nova.env` to the indices from
the Pi inventory, or leave blank for host defaults. Device names are shown only
with the opt-in flag and can identify equipment; omit them from shared reports.
Start muted, then type `M` + Enter to enable listening. Type it again to mute.
Ctrl+C stops Nova and drains accepted passive work; stop the foreground Ollama
server separately. Terminal EOF or a console read failure forces software mute
and stops the control reader; restart Nova in an interactive terminal to resume.
No service/SSH background daemon controls are supplied in this module.

## Resource profile and privacy

On a 4 GB Pi the starting choices are tiny.en STT, existing medium Piper voice,
Llama 3.2 1B, 1024-token context, two inference threads, one loaded Ollama model
and one parallel request, zero keep-alive, server queue two, audio block queue
50, passive queue two. These are conservative hypotheses, **not measured RAM or
latency guarantees**. Zero keep-alive trades repeated model-load latency for
releasing memory after responses. Weight download size is not peak resident RAM.
Whisper/Piper still spawn on demand. Half-duplex and passive extraction disabled
avoid concurrent background inference initially; do not enable passive extraction
or interruption until measuring capacity. OMP/BLAS thread caps apply only to
libraries honoring those variables. Ollama settings are in `ollama-serve.sh` and
must be adjusted separately from the client profile.

Monitor `free -h`, `df -h`, `ps -o pid,rss,nlwp,pcpu -p PID`, and on the Pi
`vcgencmd measure_temp` / `vcgencmd get_throttled`. Existing runtime metrics can
be enabled explicitly with `NOVA_RUNTIME_DIAGNOSTICS=true`. Check sustained
latency, queue overflow, swap/oom events and thermal throttling before increasing
models, queues or concurrency. Do not use shell tracing or dump environment files
into diagnostic bundles. Offline operation follows initial provisioning: no
online tools, no cloud LLM/semantic recall, and no model auto-download at startup.
No network firewall or encrypted SQLite storage is supplied. Local file
permissions do not protect against root, same-user access, backups or theft of
the SD card. See `docs/PRIVACY.md` for memory retention and WAV cleanup rules.

## Troubleshooting and hardware validation checklist

| Check / symptom | Action and expected outcome |
|---|---|
| Platform or Python failed | Verify 64-bit OS and Python 3.13. Do not bypass checks or relax project requirements. |
| Dependency / ELF / executable failed | Install ARM64 wheels/system libraries; rebuild whisper.cpp; check executable permission and loader dependencies. Do not copy .exe files. |
| Voice / Whisper model failed | Check nonempty model, matching voice JSON, model checksums and an actual local inference sample. Restore a known-good artifact explicitly. |
| Audio format failed | Inspect `arecord -l`, `aplay -l`, local device inventory and ALSA/PipeWire settings. Select USB input/output indices; verify 16 kHz capture and 22.05 kHz playback support. No silent sample-rate replacement. |
| Ollama inventory failed / OOM | Start the correct foreground server; check the local model exists, port binding, memory, temperature and shared libraries. No automatic retries/downloads in preflight. |
| Private path / environment failed | Fix ownership/modes for the dedicated file/directories; confirm storage is writable with sufficient space. Preserve personal data. |
| Long-running resources grow | Capture numeric sanitized metrics and failure check names; inspect orphan child processes / queue overflow. Avoid sharing transcripts, DB files or WAVs. |

All following checks are **pending actual Pi execution**:

- Confirm binaries and models perform inference, not just preflight successfully.
- Unmute and verify continuous capture, VAD, wake activation, Whisper and Piper.
- Verify mute closes streams; no muted or stale recordings reach STT/memory.
- Verify playback echo cannot become a command or passive memory; resume capture.
- Enable passive extraction only after measuring RAM; verify grounded recall and
  accepted-work shutdown draining using deliberately non-sensitive test speech.
- Verify task/reminder persistence, notifications and restart without duplicates.
- Disconnect/reconnect USB mic and speaker; verify bounded recovery and device reselection.
- Ctrl+C during capture/STT/model/TTS/playback; inspect process exit and owned WAV cleanup.
- Verify permissions, local-only binding and operation with Internet disconnected.
- Measure peak RSS, CPU, latency, queue depth, temperature and throttling on 4 GB.
- Run the deferred multi-hour physical reliability test; no completion is claimed here.

Do not enable experimental spoken interruption as proof of acoustic echo
cancellation: none is implemented. Validate the default half-duplex workflow
first. GPIO wiring and auto-start remain separate future modules.
