"""Build an empty desktop seed unless personal data is explicitly requested."""
from contextlib import closing
import os
from pathlib import Path
import sqlite3
import tempfile

from vocab import Store


def prepare_seed(destination, source=None, *, include_personal=False):
    destination = Path(destination)
    source = Path(source) if source is not None else None
    if source is not None and destination.resolve() == source.resolve():
        raise ValueError('The seed must be separate from the personal database')
    if include_personal and (source is None or not source.is_file()):
        raise FileNotFoundError('The requested personal database does not exist')
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=destination.parent, suffix='.db', delete=False) as handle:
        temporary = Path(handle.name)
    try:
        if include_personal:
            with closing(sqlite3.connect(source)) as original:
                with closing(sqlite3.connect(temporary)) as target:
                    original.backup(target)
        Store(temporary)
        with closing(sqlite3.connect(temporary)) as target:
            target.executemany('INSERT OR REPLACE INTO settings VALUES (?,?)', [
                ('offline_path', '__BUNDLED__'), ('bundled_dictionary_path', '__BUNDLED__'),
                ('online', '0'), ('tts', '0'), ('auto_sync', '0'), ('vault', ''),
                ('word_table_path', ''), ('auto_save_word_table', '0'),
            ])
            target.execute('DELETE FROM query_cache')
            target.commit()
            target.execute('VACUUM')
        os.replace(temporary, destination)
        return destination
    finally:
        temporary.unlink(missing_ok=True)
