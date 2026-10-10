"""Check recall on a temporary snapshot, without microphone or model access."""
import argparse
from pathlib import Path
import sqlite3
import tempfile

from offline_ai_companion.config import PROJECT_ROOT
from offline_ai_companion.memory.database import Database
from offline_ai_companion.memory.repository import MemoryRepository
from offline_ai_companion.memory.passive_repository import PassiveMemoryRepository
from offline_ai_companion.memory.hybrid_retriever import HybridMemoryRetriever


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database', type=Path)
    parser.add_argument('--question', default='What sport do I love playing?')
    args = parser.parse_args()
    database = args.database
    if database is None:
        files = list((PROJECT_ROOT / 'sample-data/memory/clean-tests').rglob('companion.db'))
        if not files:
            parser.error('No clean-test database exists. Run a clean voice test first.')
        database = max(files, key=lambda p: p.stat().st_mtime)
    database = database.resolve()
    if not database.is_file():
        parser.error('The selected database does not exist.')
    print(f'Checking database: {database}')
    # SQLite backup includes committed WAL data without modifying the source.
    with tempfile.TemporaryDirectory(prefix='nova-recall-check-') as directory:
        copy = Path(directory) / 'snapshot.db'
        source = sqlite3.connect(database.as_uri() + '?mode=ro', uri=True, timeout=3)
        destination = sqlite3.connect(copy)
        try:
            source.backup(destination)
        finally:
            destination.close()
            source.close()
        db = Database(copy)
        retriever = HybridMemoryRetriever(PassiveMemoryRepository(db), MemoryRepository(db))
        result = retriever.recall(args.question)
        print(result.response if result else 'This question has no supported memory recall route.')
    print('Original database unchanged. No audio capture or model request was made.')


if __name__ == '__main__':
    main()
