"""Run the editable portfolio locally and open it in the default browser.

For public deployment use Gunicorn, HTTPS, a persistent database/upload volume,
and environment variables documented in README.md instead.
"""
import argparse
import os
import secrets
import sqlite3
import threading
import webbrowser
from contextlib import closing
from getpass import getpass

os.environ.setdefault('FLASK_SECRET_KEY', secrets.token_urlsafe(48))

from app import app, set_admin_credentials  # noqa: E402 — configure the session key before importing


def configure_admin_if_missing():
    """Create a first-run local admin without shipping a password or hash in GitHub."""
    with closing(sqlite3.connect(app.config['DATABASE'])) as db:
        if db.execute('SELECT id FROM admin WHERE id=1').fetchone():
            return
    print('\nFIRST-RUN ADMIN SETUP (input stays on your computer)')
    try:
        email = input('Admin email [ziyaullahshahid@gmail.com]: ').strip() or 'ziyaullahshahid@gmail.com'
        password = getpass('New admin password (12+ characters): ')
        confirmation = getpass('Repeat admin password: ')
    except (KeyboardInterrupt, EOFError):
        raise SystemExit('\nAdmin setup cancelled; run this launcher again.') from None
    if password != confirmation:
        raise SystemExit('Passwords do not match. Run this launcher again.')
    try:
        set_admin_credentials(app.config['DATABASE'], email, password)
    except ValueError as exc:
        raise SystemExit(f'Could not create admin: {exc}') from exc
    print('Admin created securely. Only an Argon2id hash is stored locally.\n')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Open the portfolio or its admin login on this computer.')
    parser.add_argument('--admin', action='store_true', help='open the working admin login directly')
    args = parser.parse_args()
    configure_admin_if_missing()
    address = 'http://127.0.0.1:8002/'
    target = address + 'admin/login' if args.admin else address
    print(f'Website: {address}')
    print(f'Admin login: {address}admin/login')
    print(f'Opening: {target}')
    print('Keep this terminal open. Press Ctrl+C to stop the local server.')
    threading.Timer(1.25, lambda: webbrowser.open(target)).start()
    app.run(host='127.0.0.1', port=8002, debug=False)
