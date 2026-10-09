"""Own only new runtime WAV paths; never sweep user recordings."""

import logging
from pathlib import Path
from tempfile import mkdtemp

logger = logging.getLogger(__name__)


class TemporaryAudio:
    def __init__(self, parent):
        self.root = Path(mkdtemp(prefix="nova-session-", dir=parent)).resolve()
        self.paths = set()

    def path(self, name):
        if name not in {"input.wav", "response.wav", "reminder.wav"}:
            raise ValueError("Unsupported temporary audio name.")
        path = self.root / name
        self.paths.add(path)
        return path

    def cleanup(self, path):
        path = Path(path).absolute()
        if path not in self.paths or path.parent.resolve() != self.root:
            return
        try:
            path.unlink(missing_ok=True)
        except OSError as exc:
            logger.error("Temporary audio cleanup failed: %s", type(exc).__name__)

    def close(self):
        for path in self.paths:
            self.cleanup(path)
        try:
            self.root.rmdir()  # Do not recursively delete unexpected retained files.
        except OSError as exc:
            logger.error("Temporary audio directory cleanup failed: %s", type(exc).__name__)
