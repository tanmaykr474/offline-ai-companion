"""Render non-root Linux units with strictly validated, literal deployment paths."""
import argparse
from pathlib import Path, PurePosixPath
import re


def render(template, root, user):
    if (not re.fullmatch(r"/[A-Za-z0-9_./-]+", root) or ".." in PurePosixPath(root).parts
            or "%" in root or root == "/"):
        raise ValueError("Service root must be a simple absolute Linux path without traversal or spaces.")
    if user == "root" or not re.fullmatch(r"[a-z_][a-z0-9_-]{0,31}", user):
        raise ValueError("Service requires a valid non-root local username.")
    result = template.replace("@ROOT@", root.rstrip("/")).replace("@USER@", user)
    if "@ROOT@" in result or "@USER@" in result:
        raise ValueError("Unresolved service placeholders.")
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True)
    parser.add_argument("--user", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    templates = Path(__file__).resolve().parents[3] / "deployment/raspberry-pi/systemd"
    rendered = {name: render((templates / (name + ".in")).read_text(encoding="utf-8"), args.root, args.user)
                for name in ("nova.service", "nova-ollama.service")}
    args.output_dir.mkdir(parents=True, exist_ok=True)
    for name, content in rendered.items():
        (args.output_dir / name).write_text(content, encoding="utf-8", newline="\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
