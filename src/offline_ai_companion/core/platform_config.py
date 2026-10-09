"""Explicit platform defaults. Windows behavior remains unchanged."""
import os
import platform
from pathlib import Path, PureWindowsPath


def runtime_defaults(system=None, machine=None, profile=""):
    system = platform.system() if system is None else system
    machine = platform.machine().lower() if machine is None else machine.lower()
    if profile not in {"", "raspberry-pi"}:
        raise ValueError("Unsupported Nova deployment profile.")
    if profile == "raspberry-pi" and (system != "Linux" or machine not in {"aarch64", "arm64"}):
        raise ValueError("The Raspberry Pi profile requires Linux ARM64.")
    return {
        "WHISPER_EXECUTABLE": ("deployment/windows/whisper-cpp/Release/whisper-cli.exe" if system == "Windows"
                               else "deployment/raspberry-pi/whisper.cpp/build/bin/whisper-cli"),
        "PIPER_EXECUTABLE": ("deployment/windows/piper/piper.exe" if system == "Windows"
                             else "deployment/raspberry-pi/piper.sh"),
        "WHISPER_MODEL_PATH": "deployment/models/ggml-tiny.en.bin",
        "PIPER_MODEL_PATH": "deployment/models/piper/en_US-lessac-medium.onnx",
    }


def project_path(root, value, system=None):
    system = platform.system() if system is None else system
    if system != "Windows" and (PureWindowsPath(value).drive or "\\" in value):
        raise ValueError("Windows paths cannot be used for Linux runtime files.")
    path = Path(value).expanduser()
    return path if path.is_absolute() else Path(root) / path


def optional_integer(name, low, high, environment=None):
    environment = os.environ if environment is None else environment
    value = environment.get(name, "").strip()
    if not value:
        return None
    try:
        result = int(value)
    except ValueError:
        raise ValueError(f"{name} must be an integer.") from None
    if not low <= result <= high:
        raise ValueError(f"{name} must be between {low} and {high}.")
    return result
