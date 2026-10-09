"""Pi preflight checks: no audio capture, inference, downloads or database writes."""
import argparse
import importlib
import json
import os
import platform
import struct
import sys
from pathlib import Path

from dotenv import dotenv_values
from .platform_config import optional_integer, project_path, runtime_defaults
from offline_ai_companion.llm.local_endpoint import local_endpoint


def environment_file(path, inherited=None):
    # Do not source shell code or expand values containing other environment variables.
    values = dotenv_values(path, interpolate=False)
    if any(value is None for value in values.values()):
        raise ValueError("Environment settings require values.")
    values.update(os.environ if inherited is None else inherited)
    values["NOVA_ENV_FILE"] = str(Path(path).resolve())
    return values


def arm64_executable(path):
    with path.open("rb") as stream:
        header = stream.read(64)
    return (len(header) == 64 and header[:6] == b"\x7fELF\x02\x01"
            and int.from_bytes(header[18:20], "little") == 183)


def ollama_available(host, model):
    import httpx
    endpoint = local_endpoint(host)  # Validate before constructing a client.
    with httpx.Client(trust_env=False, follow_redirects=False, timeout=3) as client:
        with client.stream("GET", endpoint + "/api/tags") as response:
            if response.status_code != 200:
                return False
            chunks, size = [], 0
            for chunk in response.iter_bytes():
                size += len(chunk)
                if size > 65536:
                    return False
                chunks.append(chunk)
            body = json.loads(b"".join(chunks))
    return any(item.get("name") == model for item in body.get("models", []) if isinstance(item, dict))


def preflight(root, env_file, environment=None, *, system=None, machine=None,
              python=None, bits=None, uid=None, importer=importlib.import_module,
              executable=os.access, audio=None, model_probe=None):
    """Return sanitized checks. Injectable boundaries permit Windows CI tests."""
    root, env_file = Path(root), Path(env_file)
    system = platform.system() if system is None else system
    machine = platform.machine() if machine is None else machine
    python = sys.version_info[:2] if python is None else python
    bits = struct.calcsize("P") * 8 if bits is None else bits
    uid = getattr(os, "getuid", lambda: None)() if uid is None else uid
    checks = []

    def check(name, operation):
        try:
            ok = bool(operation())
        except Exception:
            ok = False  # Exceptions may contain credentials, paths or provider payloads.
        checks.append({"check": name, "status": "ok" if ok else "failed"})
        return ok

    check("linux_arm64", lambda: system == "Linux" and machine.lower() in {"aarch64", "arm64"} and bits == 64)
    check("python_313", lambda: tuple(python) == (3, 13))
    check("unprivileged_user", lambda: uid is not None and uid != 0)
    check("private_environment", lambda: env_file.is_file() and
          (system != "Linux" or (env_file.stat().st_mode & 0o077 == 0 and env_file.stat().st_uid == uid)))
    try:
        env = environment_file(env_file, environment)
        defaults = runtime_defaults(system, machine, env.get("NOVA_PROFILE", ""))
    except Exception:
        check("configuration", lambda: False)
        return {"scope": "preflight_not_physical_validation", "checks": checks, "ok": False}
    check("pi_profile", lambda: env.get("NOVA_PROFILE") == "raspberry-pi")
    for name, low, high in (("WHISPER_THREADS", 1, 16), ("NOVA_AUDIO_QUEUE_SIZE", 1, 1000),
                            ("NOVA_OLLAMA_NUM_CTX", 128, 8192), ("NOVA_OLLAMA_NUM_THREAD", 1, 16)):
        check(name.lower(), lambda n=name, lo=low, hi=high: optional_integer(n, lo, hi, env) is not None)
    for name in ("NOVA_INPUT_DEVICE", "NOVA_OUTPUT_DEVICE"):
        check(name.lower(), lambda n=name: not env.get(n, "").strip() or int(env[n]) >= 0)
    check("loopback_ollama", lambda: bool(local_endpoint(env.get("OLLAMA_HOST", "http://127.0.0.1:11434"))))
    for name in ("WHISPER_EXECUTABLE", "PIPER_EXECUTABLE"):
        def executable_check(n=name):
            path = project_path(root, env.get(n, defaults[n]), system)
            if not path.is_file() or not executable(path, os.X_OK):
                return False
            if n == "WHISPER_EXECUTABLE":
                return arm64_executable(path)
            with path.open("rb") as stream:
                return stream.read(2) == b"#!" or arm64_executable(path)
        check(name.lower(), executable_check)
    for name in ("WHISPER_MODEL_PATH", "PIPER_MODEL_PATH"):
        check(name.lower(), lambda n=name: (p := project_path(root, env.get(n, defaults[n]), system)).is_file() and p.stat().st_size > 0)
    def voice_config():
        path = Path(str(project_path(root, env.get("PIPER_MODEL_PATH", defaults["PIPER_MODEL_PATH"]), system)) + ".json")
        if not path.is_file() or not 0 < path.stat().st_size <= 1048576:
            return False
        return 8000 <= json.loads(path.read_text(encoding="utf-8"))["audio"]["sample_rate"] <= 48000
    check("piper_voice_config", voice_config)
    for name, directory in (("DATABASE_PATH", False), ("NOVA_AUDIO_DIRECTORY", True)):
        def private_path(n=name, is_directory=directory):
            path = project_path(root, env[n], system)
            parent = path if is_directory else path.parent
            return (parent.is_dir() and os.access(parent, os.W_OK) and (system != "Linux" or
                    (parent.stat().st_mode & 0o077 == 0 and parent.stat().st_uid == uid))
                    and (not path.exists() or is_directory or (path.is_file() and
                         os.access(path, os.W_OK) and (system != "Linux" or (path.stat().st_mode & 0o077 == 0 and path.stat().st_uid == uid)))))
        check(name.lower(), private_path)
    for module in ("numpy", "sounddevice", "soundfile", "httpx", "dotenv", "piper", "onnxruntime"):
        check("dependency_" + module, lambda m=module: importer(m) is not None)
    if audio is not None:
        def audio_check():
            device = lambda name: int(env[name]) if env.get(name, "").strip() else None
            report = audio(device("NOVA_INPUT_DEVICE"), device("NOVA_OUTPUT_DEVICE"))
            return all(report[key]["status"] == "ok" for key in ("inventory", "input_format", "output_format"))
        check("audio_formats", audio_check)
    if model_probe is not None:
        # Never send requests if endpoint validation failed.
        check("ollama_model_available", lambda: model_probe(local_endpoint(env.get("OLLAMA_HOST", "http://127.0.0.1:11434")),
                                                            env.get("OLLAMA_MODEL", "llama3.2:1b")))
    return {"scope": "preflight_not_physical_validation", "checks": checks,
            "ok": all(item["status"] == "ok" for item in checks)}


def main(argv=None, *, checker=preflight, runner=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path)
    parser.add_argument("--start", action="store_true", help="Start in this foreground terminal after preflight.")
    parser.add_argument("--audio", action="store_true", help="Check device formats without recording.")
    parser.add_argument("--ollama", action="store_true", help="Check local model inventory without inference.")
    args = parser.parse_args(argv)
    root = Path(__file__).resolve().parents[3]
    env_file = args.env_file or root / "deployment/raspberry-pi/nova.env"
    try:
        env = environment_file(env_file)
        # Import configuration only after selecting this environment; no Windows .env leakage.
        os.environ.update(env)
        if args.audio or args.start:
            import runpy
            audio = runpy.run_path(str(root / "scripts/audio_diagnostics.py"))["build_report"]
        else:
            audio = None
        report = checker(root, env_file, env, audio=audio,
                         model_probe=ollama_available if args.ollama or args.start else None)
    except Exception:
        report = {"ok": False, "checks": [{"check": "configuration", "status": "failed"}]}
    if args.start and not sys.stdin.isatty():
        report["ok"] = False
        report["checks"].append({"check": "interactive_mute_controls", "status": "failed"})
    print(json.dumps(report, indent=2))
    if not report["ok"]:
        return 1
    if args.start:
        os.umask(0o077)
        os.chdir(root)
        if runner is None:
            import runpy
            runner = lambda: runpy.run_path(str(root / "scripts/always_on_assistant.py"), run_name="__main__")
        runner()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
