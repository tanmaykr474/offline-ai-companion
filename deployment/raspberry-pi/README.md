# Raspberry Pi 5 deployment — Modules 12.12A and 12.12C

Preparation is implemented and tested with mocks on Windows. **Deployment,
Linux device operation, model inference, RAM capacity and thermal behavior have
not been validated on a Raspberry Pi.** Windows audio/interruption tests passed;
multi-hour physical reliability testing remains deferred. Module 12.12C adds
GPIO control code, wiring instructions and opt-in systemd installation below.
None has been physically validated on a Pi.

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
| GPIO | Optional local gpiozero backend, mock/no-op backends | Pi 5 uses explicit LGPIOFactory/chip. Distro ARM64 GPIO packages installed separately; real pins are never opened in Windows tests. |
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
first. The following section supersedes 12.12A's deferral of GPIO and auto-start.

## Module 12.12C — hardware controls and headless startup

Automated Windows verification: **80 new cases**, initial focused privacy/audio/
GPIO suite **171 passed**, final GPIO/service/preflight suite **150 passed**,
complete suite **1,278 passed in 114.53 seconds**. The actual baseline was 1,198
after the four pytest-isolation regressions. Eight Bash scripts passed syntax
checks. All GPIO tests use mocked devices; rendered service policies are tested
without installing or starting services. Physical Linux/Pi validation remains pending.

### Explicit wiring configuration

Power off the Pi before wiring. Identify the LED's common pin and individual
color pins from its datasheet or a current-limited test; do not infer them from
leg length alone. Numbering in configuration is **BCM**, not header positions.
These defaults require the four GPIOs not be claimed by overlays or other
processes. Duplicate pin assignments are rejected before acquisition; a kernel
pin-claim conflict fails closed.

| Function | Configuration | BCM | Physical header pin | Connection |
|---|---|---:|---:|---|
| LED red | NOVA_LED_RED_BCM | 17 | 11 | Dedicated series resistor to red LED leg |
| LED green | NOVA_LED_GREEN_BCM | 27 | 13 | Dedicated series resistor to green LED leg |
| LED blue | NOVA_LED_BLUE_BCM | 22 | 15 | Dedicated series resistor to blue LED leg |
| Mute switch input | NOVA_MUTE_SWITCH_BCM | 23 | 16 | Switch contact to GND when listening permitted |
| Common ground | — | — | 6 | Switch ground and common-cathode LED common |
| 3.3 V | — | — | 1 | Common-anode LED common, only if that LED type is selected |

Use **one series resistor per color**, initially 680 ohms to 1 kohm for an
ordinary low-current indicator LED. Choose the final value from the LED's forward
voltage and desired current using R >= (3.3 V - Vf) / I; verify brightness and
RP1 GPIO electrical limits on target. Use a suitable driver for higher-current
LEDs or modules. Never connect GPIO or a common-anode LED to 5 V. Shared ground is
required. [Raspberry Pi hardware documentation](https://www.raspberrypi.com/documentation/computers/raspberry-pi.html)
and [gpiozero output polarity](https://gpiozero.readthedocs.io/en/stable/api_output.html)
describe the electrical interfaces and active-high/active-low behavior.

- Common **cathode**: common to GND; `NOVA_LED_ACTIVE_HIGH=true`.
- Common **anode**: common to 3.3 V; `NOVA_LED_ACTIVE_HIGH=false`.
- Default SPST switch: GPIO23 to one contact, GND to the other, internal pull-up;
  `NOVA_SWITCH_MUTED_HIGH=true`. **Open = MUTED; closed to ground = LISTEN permitted.**
  For SPDT use the common terminal and only the ground contact; leave the other
  contact unconnected. Label the positions accordingly.
- Alternate wiring is supported explicitly: `NOVA_SWITCH_MUTED_HIGH=false`
  uses internal pull-down, **open = MUTED**, contact to 3.3 V = LISTEN permitted.
  Do not mix these two wiring conventions or connect opposing supplies together.

The switch changes **software capture permission**, not USB microphone power or
an electrical signal cutoff. A true hardware microphone cutoff requires an
appropriate independent physical circuit. Software cannot identify all electrical
faults: a stuck short can resemble a listen position, and a reconnected switch
wire can resemble a deliberate switch change. GPIO API faults are detected and
latch mute; wiring integrity still requires physical inspection/testing.

### GPIO dependency and chip setup

Run the 12.12A setup/model steps first. Then on Raspberry Pi OS 64-bit:

```bash
cd ~/nova
bash deployment/raspberry-pi/setup-hardware.sh
# Log out/in so the user's gpio/audio group membership takes effect.
id
gpiodetect
gpioinfo
ls -l /dev/gpiochip* /dev/snd
```

The script installs distro `python3-gpiozero`, `python3-lgpio` and `gpiod` packages,
then explicitly enables system-site packages for the existing Python 3.13 venv.
Existing venv-installed packages retain precedence; this step does not upgrade
them. Distro-built lgpio avoids assuming a CPython 3.13 ARM64 PyPI wheel exists.
Review installed versions with `dpkg-query -W python3-gpiozero python3-lgpio`
and `.venv/bin/python -m pip show gpiozero`. The preflight and runtime require
gpiozero major version 2 and supported lgpio APIs; unsupported imports/APIs stop
startup. Compatibility still requires actual chip acquisition on the target OS.

The production backend constructs
`gpiozero.pins.lgpio.LGPIOFactory(chip=NOVA_GPIO_CHIP)` directly. It never silently
falls back to RPi.GPIO, remote GPIO, or a mock factory. Choose the chip whose label
and line map correspond to the **RP1 header GPIO controller**. Current kernels
often use gpiochip0; older Pi 5 setups can use gpiochip4. Do not assume either:
inspect the target inventory, then set `NOVA_GPIO_CHIP` explicitly. See
[gpiozero pin factories](https://gpiozero.readthedocs.io/en/stable/api_pins.html)
and the [Pi 5 kernel numbering issue](https://github.com/gpiozero/gpiozero/issues/1166).
Do not grant broad device permissions or run Nova as root to bypass an error.

Edit the existing private `deployment/raspberry-pi/nova.env`:

```dotenv
NOVA_HEADLESS=true
NOVA_GPIO_BACKEND=lgpio
NOVA_GPIO_CHIP=0
NOVA_LED_RED_BCM=17
NOVA_LED_GREEN_BCM=27
NOVA_LED_BLUE_BCM=22
NOVA_MUTE_SWITCH_BCM=23
NOVA_LED_ACTIVE_HIGH=true
NOVA_SWITCH_MUTED_HIGH=true
NOVA_SWITCH_DEBOUNCE_SECONDS=0.1
NOVA_GPIO_POLL_SECONDS=0.02
MIC_ENABLED=false
NOVA_ONLINE_TOOLS_ENABLED=false
```

Adjust chip and LED/switch polarity to the actual hardware. Keep mode 600.
`NOVA_GPIO_BACKEND=none` is the default for development/preparation; `mock` is a
pure Python test backend and is **rejected for production headless startup**.
Unavailable hardware falls back to no-op outputs with capture muted; required
headless GPIO initialization failure exits with configuration status 78.

### Safety and state behavior

Each process starts muted regardless of switch position or prior state. Move the
switch to MUTED, hold at least the configured debounce interval, then move to
LISTEN and hold again. This is required after every restart. A startup switch
already in LISTEN cannot automatically authorize capture. Stable release permits
listening; software mute can still pause capture. Physical MUTED overrides all
software/console unmute requests.

The switch is polled every 20 ms by default. A detected muted sample immediately
invalidates the existing microphone generation; release must remain stable for
100 ms. This is not zero-latency electrical isolation. The existing recorder,
transcription and dispatch guards reject stale input. Work accepted before mute
continues to drain; committed tasks/reminders/facts are not rolled back.

The LED reflects the existing assistant state: green LISTENING, blue PROCESSING
or SPEAKING, red whenever muted, off in idle/interrupted and shutdown. Shutdown
off is latched. GPIO read/write errors force mute until restart, with no automatic
unmute on API recovery. Failed GPIO may prevent a reliable red/off indication;
verify electrically. Audio recovery never clears physical mute. Headless mode
creates no terminal reader, and no Windows keyboard API is used on Linux.

### Foreground check, service installation and control

Stop any manual Ollama process before starting its systemd unit to avoid port
conflicts. Model provisioning must already be complete; services do not download
packages or models. Before enabling services, manually run:

```bash
.venv/bin/python -m offline_ai_companion.core.pi_deployment --headless --audio --ollama
.venv/bin/python -m offline_ai_companion.core.pi_deployment --start --headless
```

The first command does not acquire GPIO or perform audio/model inference; the
second acquires GPIO and remains muted until a deliberate switch cycle. It can
run without stdin/a keyboard. Physically validate before enabling boot startup.

```bash
bash deployment/raspberry-pi/install-service.sh
sudo systemctl enable --now nova-ollama.service
sudo systemctl enable --now nova.service
systemctl status nova.service nova-ollama.service
journalctl -u nova.service -u nova-ollama.service --since '10 minutes ago' --no-pager
sudo systemctl stop nova.service
sudo systemctl disable --now nova.service nova-ollama.service
```

Install renders literal paths/user from the checkout, requires a simple absolute
Linux path without whitespace/traversal, runs `systemd-analyze verify` on both
rendered units, installs them with sudo, and reloads systemd. **Install does not
enable or start them.** Units run as the invoking non-root user. Nova uses
supplementary gpio/audio groups, the existing venv, private environment file and
umask 0077; startup is ordered after local filesystems, sound and its local Ollama
unit. `Wants` lets Ollama recover without forcibly killing Nova's accepted work.
Initial local model/device readiness failures use temporary status 75 and bounded
retries; missing configuration/files/GPIO use status 78 without auto-restart.
Three failures within five minutes stop automatic retries. After fixing the cause:

```bash
sudo systemctl reset-failed nova.service nova-ollama.service
sudo systemctl restart nova-ollama.service nova.service
```

SIGTERM follows the existing Ctrl+C cleanup path: capture/playback/subprocess
finally blocks run, SQLite transactions roll back if interrupted, scheduler
waiters close, accepted passive work drains, GPIO outputs turn off and pins/factory
close. Repeated SIGTERM does not interrupt draining. Committed operations remain.
Nova uses `KillMode=mixed` so children are not sent SIGTERM alongside the main
process. `TimeoutStopSec=infinity` intentionally avoids killing accepted work:
**a genuinely stalled shutdown needs operator investigation**. Changing this
policy to a finite timeout can lose unfinished accepted work. Ollama's separate
unit has a 60-second stop timeout and cgroup cleanup. SIGKILL/power loss cannot
execute GPIO/audio cleanup; restart still starts muted. No acoustic echo
cancellation, disk encryption or electrically enforced microphone cutoff is added.

### Raspberry Pi troubleshooting and physical checklist

- For permissions/initialization failures, inspect groups, `/dev/gpiochip*`, RP1
  chip mapping and `dpkg-query` versions. Re-login after group changes. Check
  overlays/pin conflicts with `gpioinfo`; do not probe claimed pins while running.
- For ALSA/PortAudio issues use `arecord -l`, `aplay -l` and the existing audio
  diagnostics as the service user. A desktop PipeWire session's devices/defaults
  may differ from headless ALSA. Explicitly select valid Linux PortAudio indices.
- For service failures use sanitized check names and journal error categories.
  Do not publish environment files, SQLite, WAVs, private transcripts or prompts.
- LED inverted or wrong colors: stop/power off, verify common type, resistor and
  color leg mapping, then correct polarity/BCM settings. Do not rewire live GPIO.
- If a driver error latched mute, repair the problem and explicitly restart. A
  restart requires a new physical mute-to-listen cycle.

The following remain **unverified until executed on the actual Pi**:

1. Confirm gpiozero/lgpio versions, ARM64 imports, RP1 chip mapping and non-root access.
2. Verify all LED colors, polarity, per-color resistors and off after shutdown.
3. Boot/restart with each switch position; verify muted startup and required switch cycle.
4. Test bounce, console unmute denial, broken/open wire behavior and software mute.
5. Mute during recording/STT/LLM/playback; verify no stale speech reaches storage/commands.
6. Validate headless ALSA microphone/speaker, model inference, reminders and restart persistence.
7. Exercise supported GPIO API/device failures: latch mute and verify no automatic recovery unmute.
8. Enable units, reboot, verify startup ordering, crash restart and permanent-error/start-limit behavior.
9. Send `systemctl stop`/SIGTERM during inference/playback/passive extraction; verify draining,
   SQLite consistency, audio closure, child exit, LED off and pin release.
10. Verify Internet-disconnected operation, resource/thermal capacity and the deferred multi-hour soak.

Windows mocked GPIO and service-template tests do not establish Linux GPIO,
audio, systemd or model-inference success. Bash syntax and rendered unit-policy
checks are preparation checks; target `systemd-analyze verify` and physical checks
are still mandatory.
