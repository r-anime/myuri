# Myuri

<div style="width:20%; margin: ">

![Myuri](/assets/myuri.png) 
</div>

A successor to [holo](https://github.com/r-anime/holo). This is a Django web application and Reddit bot for creating and managing anime episode discussion posts on Reddit.

## Requirements

- Python 3.12+
- Dependencies (installed via `requirements.txt`):
  - Django 6.0
  - PRAW 7.8.1 — Reddit API wrapper
  - django-allauth — Reddit OAuth login
  - django-apscheduler — scheduled episode scanning
  - PyYAML, feedparser
  - psycopg2-binary — required if using PostgreSQL
- Docker (optional, for containerised setup)

## Quick Setup

### 1. Configuration

Copy the example config and fill in your credentials:

```bash
  cp config.ini.example config.ini
```

Sections to complete in `config.ini`:

| Section | Key fields | Notes                                                                          |
|---|---|--------------------------------------------------------------------------------|
| `[django]` | `secret_key`, `debug` | Generate a key with `py -c "import secrets; print(secrets.token_urlsafe(50))"` |
| `[reddit_oauth]` | `client_id`, `client_secret` | Create a **web app** at reddit.com/prefs/apps. This is for website auth.       |
| `[reddit_episode_poster]` | `username`, `password`, `oauth_key`, `oauth_secret` | Account that will post the discussion threads.                                 |
| `[reddit_moderator]` | `username`, `password`, `oauth_key`, `oauth_secret` | Account that will make moderator actions                                       |
| `[discord]` | `webhook_url` | Optional - leave blank to disable notifications.                               |
| `[data]` | `database` | `database.sqlite` (default) or `postgres` (set additional fields)              |


### 2. Local development

```bash
# Create and activate virtual environment
py -m venv venv

# Activate
venv\Scripts\activate        # Windows
source venv/bin/activate     # Linux/Mac

# Install dependencies
pip install -r requirements.txt

# Apply database migrations
cd src/myuri
py manage.py migrate

# Run the server and scheduler (separate terminals)
py manage.py runserver
py manage.py runapscheduler
```

The app will be available at `http://localhost:8000`.

### 3. Docker

**Build the image:**

```bash
  docker build -t myuri .
```

**Run the app:**

```bash
  docker run --rm -p 8000:8000 \
    -v "$(pwd)/config.ini:/opt/myuri/config.ini:ro" \
    -v "$(pwd)/src/myuri/db.sqlite3:/opt/myuri/src/myuri/db.sqlite3" \
    myuri \
    sh -c "python manage.py migrate && python manage.py runapscheduler & python manage.py runserver 0.0.0.0:8000"
```

`config.ini` contains secrets and is mounted read-only — it is never baked into the image. `db.sqlite3` is mounted so data persists across container restarts.
