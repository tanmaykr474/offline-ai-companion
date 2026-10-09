"""Enumerate audio devices and check formats without recording or playing audio."""
import argparse
import json
import platform
from pathlib import Path

from offline_ai_companion.audio.diagnostics import device_inventory, input_format_check, output_format_check
from offline_ai_companion.config import (
    NOVA_INPUT_DEVICE, NOVA_OUTPUT_DEVICE, WHISPER_EXECUTABLE, WHISPER_MODEL_PATH,
    PIPER_EXECUTABLE, PIPER_MODEL_PATH,
)


def device_index(value):
    index = int(value)
    if index < 0:
        raise argparse.ArgumentTypeError("Device index must be nonnegative.")
    return index


def build_report(input_device=None, output_device=None, include_names=False):
    return {
        "scope": "metadata_and_format_checks_only_not_physical_validation",
        "platform": platform.system(),
        "python": platform.python_version(),
        "inventory": device_inventory(include_names),
        "input_device": input_device,
        "output_device": output_device,
        "input_format": input_format_check(input_device),
        "output_format": output_format_check(output_device),
        "local_files": {
            "whisper_executable": WHISPER_EXECUTABLE.is_file(),
            "whisper_model": WHISPER_MODEL_PATH.is_file(),
            "piper_executable": PIPER_EXECUTABLE.is_file(),
            "piper_model": PIPER_MODEL_PATH.is_file(),
            "piper_model_config": Path(str(PIPER_MODEL_PATH) + ".json").is_file(),
        },
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-device", type=device_index, default=NOVA_INPUT_DEVICE)
    parser.add_argument("--output-device", type=device_index, default=NOVA_OUTPUT_DEVICE)
    parser.add_argument("--include-device-names", action="store_true",
                        help="Opt in to local device labels; they may identify people or equipment.")
    parser.add_argument("--output", type=Path, help="Save the same JSON report to this chosen file.")
    args = parser.parse_args(argv)
    report = build_report(args.input_device, args.output_device, args.include_device_names)
    rendered = json.dumps(report, indent=2)
    if args.output:
        args.output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0 if (report["inventory"]["status"] == "ok" and report["input_format"]["status"] == "ok"
                 and report["output_format"]["status"] == "ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
