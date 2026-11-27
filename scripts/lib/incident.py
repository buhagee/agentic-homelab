"""Durable incident transitions. One local database per reporting identity."""
from contextlib import closing
import os
from pathlib import Path
import re
import sqlite3
import sys
import time

from send_email import send_email


def observe(path, key, status, detail, deliver, *, now=None):
    if not re.fullmatch('[a-z0-9][a-z0-9.-]{0,95}', key) or status not in ('failed', 'healthy', 'unknown'):
        raise ValueError('invalid incident observation')
    now = int(time.time() if now is None else now)
    with closing(sqlite3.connect(path, timeout=50, isolation_level=None)) as db:
        db.execute('BEGIN IMMEDIATE')
        db.execute('CREATE TABLE IF NOT EXISTS incidents (key TEXT PRIMARY KEY, first_good INTEGER)')
        db.execute('CREATE TABLE IF NOT EXISTS mail (id INTEGER PRIMARY KEY, key TEXT, subject TEXT, detail TEXT)')
        row = db.execute('SELECT first_good FROM incidents WHERE key=?', (key,)).fetchone()
        transition = None
        if status == 'failed' and row is None:
            db.execute('INSERT INTO incidents VALUES (?,NULL)', (key,))
            transition = 'failed'
        elif row is not None:
            if status != 'healthy':
                db.execute('UPDATE incidents SET first_good=NULL WHERE key=?', (key,))
            elif row[0] is None or now < row[0]:
                db.execute('UPDATE incidents SET first_good=? WHERE key=?', (now, key))
            elif now - row[0] >= 60:
                db.execute('DELETE FROM incidents WHERE key=?', (key,))
                transition = 'recovered'
        if transition:
            db.execute('INSERT INTO mail(key,subject,detail) VALUES (?,?,?)',
                       (key, f'Qacey {key} {transition}', detail))
        db.commit()
        # Commit each delivery separately. A lost SMTP acknowledgement can cause
        # replay (SMTP offers no exactly-once guarantee), never periodic reminders.
        while True:
            db.execute('BEGIN IMMEDIATE')
            pending = db.execute('SELECT id,subject,detail FROM mail WHERE key=? ORDER BY id LIMIT 1', (key,)).fetchone()
            if pending is None:
                db.commit()
                return
            deliver(pending[1:])
            db.execute('DELETE FROM mail WHERE id=?', (pending[0],))
            db.commit()


def main(argv):
    key, status, detail = argv
    os.umask(0o077)
    directory = Path.home() / '.local/state/qacey-incidents'
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    if directory.is_symlink() or directory.stat().st_uid != os.geteuid() or directory.stat().st_mode & 0o077:
        raise ValueError('incident state directory must be private')
    observe(directory / 'state.sqlite', key, status, detail, lambda msg: send_email(*msg))


if __name__ == '__main__':
    try:
        main(sys.argv[1:])
    except Exception as exc:
        sys.exit(f'incident state or delivery failed ({type(exc).__name__}); retry on next observation')
