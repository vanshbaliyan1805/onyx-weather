# QUICKSTART — Run this in 5 minutes

Complete instructions to go from nothing to collecting live weather data.
No API keys needed. No accounts to create.

---

## Step 0 — Install these two things first

**Python** — https://www.python.org/downloads/
On Windows, **tick the box that says "Add Python to PATH"** during install.
That box is easy to miss and skipping it causes most setup problems.

**Git** — https://git-scm.com/downloads
Accept all the default options.

Check both worked. Open a terminal and run:

```
python --version
git --version
```

If both print a version number, you're ready. If `python` isn't recognized on
Windows, try `py --version` instead and use `py` everywhere below.

---

## Step 1 — Download the code

Pick a folder you want the project in (Desktop is fine), then:

```
cd Desktop
git clone https://github.com/vanshbaliyan1805/onyx-weather.git
```

This creates a folder called `onyx-weather`.

---

## Step 2 — Go into the pipeline folder

```
cd onyx-weather/data/ingestion_pipeline
```

**This step matters.** Every command after this must be run from inside this
folder. If you get `can't open file 'main.py'`, you're in the wrong place —
come back here.

---

## Step 3 — Create a virtual environment

This keeps the project's packages separate from the rest of your system.

```
python -m venv .venv
```

Then activate it. **The command differs by terminal:**

| Terminal | Command |
|---|---|
| Windows PowerShell | `.venv\Scripts\Activate.ps1` |
| Windows Git Bash | `source .venv/Scripts/activate` |
| Windows CMD | `.venv\Scripts\activate.bat` |
| macOS / Linux | `source .venv/bin/activate` |

**You'll know it worked when your prompt starts with `(.venv)`.**

### If PowerShell says "running scripts is disabled on this system"

Run this once, then try activating again:

```
Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned
```

---

## Step 4 — Install the packages

```
pip install -r requirements.txt
```

Takes about 30 seconds.

---

## Step 5 — Create the database

```
python main.py init-db
```

You should see: `Database ready at ...weather_reports.db`

---

## Step 6 — Collect real data

```
python main.py fetch
```

**This takes 1–2 minutes.** Let it finish. You'll see a line per source:

```
[pipeline] openmeteo: fetched=51 inserted=51 ...
[pipeline] mastodon:  fetched=1540 inserted=1540 ...
[pipeline] rss:       fetched=61 inserted=61 ...
[pipeline] citizen:   fetched=0 inserted=0 ...
```

`citizen: 0` is normal — that source is for user-submitted reports and is
empty until someone submits one.

---

## Step 7 — See what you collected

```
python main.py stats
```

Shows how many records came from each source.

---

## Step 8 — Export it (optional)

```
python main.py export --format csv --out exports/weather_reports.csv
```

Opens in Excel, Google Sheets, pandas — anything.

---

# That's it. You're done.

The data lives in `weather_reports.db` (a single SQLite file) and, if you ran
step 8, `exports/weather_reports.csv`.

Run `python main.py fetch` again any time to collect new data. It's safe to
re-run — anything already collected gets skipped automatically, so you only
ever add what's new.

---

# Every command in one block

If you just want to copy-paste the whole thing (PowerShell version):

```powershell
cd Desktop
git clone https://github.com/vanshbaliyan1805/onyx-weather.git
cd onyx-weather\data\ingestion_pipeline
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python main.py init-db
python main.py fetch
python main.py stats
```

---

# If something goes wrong

**`can't open file 'main.py'`**
You're in the wrong folder. Run `cd onyx-weather/data/ingestion_pipeline`.

**`python is not recognized`**
Python isn't on your PATH. Try `py` instead of `python`, or reinstall Python
with the "Add to PATH" box ticked.

**`ModuleNotFoundError: No module named 'requests'`**
The virtual environment isn't active. Your prompt must show `(.venv)`.
Redo step 3, then step 4.

**`running scripts is disabled on this system`**
See the box in step 3.

**A source shows `fetched=0`**
Usually fine — it means nothing new matched right now. The exception is
`openmeteo`; if that returns 0, look for an error message printed just above
it, since that source should always return around 51 rows.

**Lots of red `403 Forbidden` errors mentioning bluesky**
You ran `--source bluesky` explicitly. Don't — it's disabled by default for a
reason (see the main README). Just run `python main.py fetch` with no flags.

**`fetch` seems frozen**
It isn't. The RSS stage checks 28 news feeds and slow ones take a while.
Give it two minutes.

---

# One warning

**Don't run `python main.py fetch --demo`.**

Demo mode writes fake sample records into your database. They look real and
you won't be able to tell them apart later. It exists only for testing without
internet.

If you ran it by accident:

```
python main.py purge-demo
```

That removes the fake rows safely and leaves real data untouched.

---

For the full column-by-column data format, how the sources work, and notes for
the ML stage, see `README.md` in this same folder.
