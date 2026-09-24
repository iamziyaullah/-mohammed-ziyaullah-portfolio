# Mohammed Ziyaullah — GitHub-ready portfolio source

Premium responsive portfolio with the complete original Blogspot copy, plus a Flask/SQLite content studio. The project includes a **public GitHub Pages preview** in `docs/index.html` and the **real password-protected admin backend** in `app.py`.

> **Important:** This public-repository package deliberately contains **no `data/site.db` and no admin password or password hash**. The database is created on first run. Do not upload a database, `.env`, or `uploads/` to GitHub. The `.gitignore` and `.dockerignore` protect them when using Git/Docker, but not if you manually upload forbidden files.

## 1. Put this code on GitHub

Create a new *empty* repository on GitHub, unzip this source package, and run these commands **inside the extracted folder** (Git Bash or PowerShell on Windows):

```sh
git init
git add .
git commit -m "Add portfolio and admin studio"
git branch -M main
git remote add origin https://github.com/YOUR_USERNAME/YOUR_REPOSITORY.git
git push -u origin main
```

Replace the placeholder URL with your own repository URL. GitHub may ask you to sign in. **Never commit `data/site.db` or an actual `.env` file.**

## 2. Show the public website with GitHub Pages

In your repository, open **Settings → Pages → Build and deployment → Deploy from a branch**. Select **main** and **/docs**, then Save. `docs/index.html` is self-contained, so it needs no external fonts or assets. This publishes the **public portfolio only**.

**GitHub Pages cannot run Python, SQLite, or a secure custom login.** The Admin button on the Pages preview explains this instead of pretending to open an admin panel.

## 3. Open the real admin on your Windows computer

Install Python **3.10+** if necessary. Extract the source ZIP and double-click **`RUN-ADMIN.bat`**. On first run the black window asks for an admin email and a new password. Type the email and password you want to use; only an **Argon2id hash** is saved in the local `data/site.db`. Keep that window open and visit **http://127.0.0.1:8002/admin/login** on the **same computer**. `RUN-LOCAL.bat` opens the public website instead.

The first run needs internet to install packages. If Python is missing, install it with the `py` launcher. If the admin page does not open, read the last error lines in the black window. On macOS/Linux use `sh RUN-ADMIN.sh`.

## 4. Put the real admin online (separate Python host)

Deploy this same repository to a **Python-capable host with persistent storage** (for example a VPS or a platform offering persistent disks/volumes). `Procfile` and `Dockerfile` are provided. On the host set private environment variables:

| Variable | Value / purpose |
| --- | --- |
| `FLASK_SECRET_KEY` | Stable, randomly generated secret (e.g. `python -c "import secrets; print(secrets.token_urlsafe(48))"`) |
| `COOKIE_SECURE` | `1` when served over HTTPS |
| `INITIAL_ADMIN_EMAIL` | `ziyaullahshahid@gmail.com` (or your chosen admin email) |
| `INITIAL_ADMIN_PASSWORD` | The chosen password, **only in the host's secret settings**, never in GitHub; remove this variable after the account is initialized |
| `ZIYA_DB_PATH` | Optional: path to a **persistent** SQLite file, e.g. `/app/data/site.db` |

The app automatically creates the database and original site content from `data/seed.json`. **Only on the first boot, if no admin exists**, `INITIAL_ADMIN_PASSWORD` initializes a server-side Argon2id hash. Remove that environment variable after the first successful boot. Subsequent boots will not overwrite the account. You can also run `python setup_admin.py` interactively on the host instead.

Keep **both `data/site.db` and `uploads/` on persistent storage**. Otherwise a redeploy/restart can erase edits, uploaded portraits and the admin account. Use HTTPS and a stable `FLASK_SECRET_KEY`. A temporary tunnel or GitHub Pages is **not** permanent backend hosting.

Start command if your host does not use the included `Procfile`/`Dockerfile`:

```sh
gunicorn -w 1 --threads 4 --bind 0.0.0.0:$PORT app:app
```

Then open **`https://YOUR_HOST/admin/login`**. If the host has no terminal, use its secret-environment variables for first-time setup as described above.

## Files

- `app.py` / `templates/` / `static/`: server-rendered website and private editor.
- `data/seed.json`: full original copy; `data/site.db` is generated privately and ignored by Git.
- `docs/index.html`: standalone public GitHub Pages site (**no secure admin on Pages**).
- `RUN-ADMIN.bat`: first-run local Windows setup and admin login.
- `tests/test_site.py`: integration tests (`python -m unittest discover -s tests -v`).
- `ORIGINAL-CONTENT-CHECKLIST.md`: readable audit of all original sections.
