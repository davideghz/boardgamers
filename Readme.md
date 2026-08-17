## Table of Contents

- [Project Requirements](#project-requirements)
- [Setup Without Docker (Linux/MacOS)](#setup-without-docker-linuxmacos)
- [Setup With Docker (Windows)](#setup-with-docker-windows)

## Project Requirements
- Python 3.12
- PostgreSQL 16 (**important note**: Postgres 17+ is NOT SUPPORTED) with `postgis` extension enabled (see below)
- GeoDjango native libraries: GDAL, GEOS, PROJ (GDAL ≥ 3.0; any compatible recent version works — exact parity with production is not required)
- virtualenv
- Docker Desktop (required on Windows, optional everywhere else)
- PyCharm (recommended) or any IDE of your choice

## Setup Without Docker (Linux/MacOS)
1. Install PostgreSQL (versions 17+ are NOT SUPPORTED) with `pg_config` (PostgreSQL dev tools)
2. Install the GeoDjango native libraries (GDAL, GEOS, PROJ)
```bash
# On MacOS (GDAL pulls in GEOS and PROJ as dependencies)
brew install gdal
```
```bash
# On Linux
sudo apt-get update
sudo apt-get install gdal-bin libgdal-dev libgeos-dev libproj-dev
```
3. Create database on your system and enable `postgis` extension
```bash
sudo -u postgres psql
CREATE USER bg_user WITH PASSWORD 'bg_password';
ALTER USER bg_user CREATEDB;
CREATE DATABASE boardgamers OWNER bg_user;
\q
sudo -u postgres psql boardgamers
CREATE EXTENSION postgis;
\q
```
4. Make a copy of `.env_template`, name it `.env`, and add the right values.
5. Activate virtual environment and install project's dependencies
```
source venv/bin/activate
pip install -r requirements.txt
```
6. Run migrations
```bash
python manage.py migrate
```
7. Run Django Server
```bash
python manage.py runserver
```
## HEROKU SETUP

### PostGIS
```
heroku pg:psql DATABASE_URL -a example-app
CREATE EXTENSION postgis;
```
Heroku docs [HERE](https://devcenter.heroku.com/articles/heroku-postgres-extensions-postgis-full-text-search#postgis)

### GDAL / GEOS / PROJ (geo libraries)
The geo libraries are provided by the [heroku-geo-buildpack](https://github.com/heroku/heroku-geo-buildpack),
which must be added **before** the Python buildpack:
```bash
heroku buildpacks:add --index 1 https://github.com/heroku/heroku-geo-buildpack.git
heroku buildpacks:add heroku/python
```

#### Versions
By default the buildpack installs the latest version available for the current stack — this is the
recommended setup. You can optionally pin versions via config vars, **but only to versions that are
prebuilt for your stack** (see the buildpack's [available versions](https://github.com/heroku/heroku-geo-buildpack#available-versions)):
```bash
heroku config:set GDAL_VERSION=3.12.3 GEOS_VERSION=3.14.1 PROJ_VERSION=9.8.1 -a <app-name>
```

> ⚠️ **When upgrading the Heroku stack** (e.g. `heroku-24` → `heroku-26`): pinned versions that are
> not prebuilt for the new stack will fail the build with a `curl 403` error. Either update the
> config vars to versions available for the new stack, or unset them to use the defaults:
> ```bash
> heroku config:unset GDAL_VERSION GEOS_VERSION PROJ_VERSION -a <app-name>
> ```
> Then **purge the build cache** before redeploying (otherwise the failed download is reused):
> ```bash
> heroku builds:cache:purge -a <app-name>   # requires: heroku plugins:install heroku-builds
> ```

## Email in local development (Mailtrap)

For local development, emails are sent via [Mailtrap](https://mailtrap.io), an SMTP sandbox that captures outgoing emails without delivering them.

1. Sign up at [mailtrap.io](https://mailtrap.io) and create an inbox
2. Copy the SMTP credentials from your inbox and add them to `.env`:
   ```
   EMAIL_HOST=sandbox.smtp.mailtrap.io
   EMAIL_HOST_USER=<your-user>
   EMAIL_HOST_PASSWORD=<your-password>
   EMAIL_PORT=2525
   ```
3. All emails sent by the app will appear in your Mailtrap inbox

> In production, replace these with your SMTP provider credentials (e.g. AWS SES).

## Translations
To extract translatable strings (ignoring the virtualenv), run:
```
python manage.py makemessages -l it --no-location -i "venv/*"
```
Add your translations, then, in order to compile locales run:
```
python manage.py compilemessages
```

> **Why `--no-location`.** Without it the `.po` stores a `#: file:line` comment
> for every string; when code moves, those line numbers shift and the file
> shows a huge diff even when no translation changed. `--no-location` drops
> those comments so the diff only reflects real string changes. Trade-off: you
> lose the "where is this string used" context that tools like Poedit rely on.
> Use it **consistently** — mixing runs with and without the flag flips all the
> location comments back and forth. The first run after adopting it produces a
> one-time large diff that strips the existing location comments.
>
> `venv/*` is the only ignore that matters here (the virtualenv lives at
> `./venv`); there is no top-level `static/`, `migrations/`, or `node_modules/`
> to skip. Both `django.po` **and** the compiled `django.mo` are committed to
> git — production does not recompile them.

---

## Setup With Docker (Windows)

### 1. Environment variables

1. Copy the file `.env_template` and rename it to `.env`.

2. Open `.env` and update the database host:

```env
DB_HOST=db
```
This is required because Docker containers communicate using service names, not `.localhost`.

### 2. Build and start Docker containers
From the project root, run:
```bash
docker compose up -d
```
This command will:
- Build the Docker images
- Start the Django container (`web`)
- Start the PostgreSQL + PostGIS container (`db`)
- Apply migrations automatically

Wait until both of the cointainers are built.
You can verify their status with:
```bash
docker compose ps
```
### 3. Populate the database

Enter the `web` container:
```bash
docker compose exec web bash
```

Inside the container, run the following command to populate the database:
```bash
python manage.py populate_db
```

### 4. PyCharm configuration (recommended)
The following steps are recommended for proper debugging and execution using **PyCharm**.

#### 4.1 Open the project folder in **PyCharm**.

#### 4.2 Make a copy of `.env_template`, name it `.env`, and add the right values.

#### 4.3 Configure Docker Compose interprete
Go to:
```bash
Settings → Project → Python Interpreter → Add Interpreter
```
Select:
```bash
Docker Compose
```
Then configure:
- Compose file: `docker-compose.yml`
- Service: `web`
- Python interpreter path: keep default
- Environment variables: keep default

Click **Next** and then **Apply**.

PyCharm will now use Python directly from the Docker container.

### 5. Run the project
If the containers are already running:

- Simply press the Run ▶️ or Debug 🐞 button in PyCharm.

If containers are not running, start them first using one of the following options:
```bash
docker compose up -d
```
or via **Docker Desktop UI**.

### 6. Access the application
Once Django is running, open your browser:
```bash
http://localhost:8000
```

### Notes
- Django runs inside Docker, not on your local machine.
- Always use 0.0.0.0:8000 inside containers.
- If environment variables change, restart containers:
```bash
docker compose up -d
```
- If Dockerfile or dependencies change:
```bash
docker compose up -d --build
```

If you need to access the container terminal, you can use:
```bash
docker compose exec web bash
```


## Management Commands

### Production Cron Jobs
In production, the following commands are scheduled via cron:
- `update_table_status`: Runs **Hourly at :00**
- `batch_notification`: Runs **Hourly at :30**
- `send_queued_notifications`: Runs **Every 10 minutes**
- `cleanup_old_notifications`: Runs **Daily at 3:00 AM UTC**

### Utility Commands

Run with `python manage.py [command-name]`

- `setup_ses_template`
  - Used to update AWS SES templates for new table notifications.
  - **Usage**: Run this ONLY if the base template or the `email_notification_new_table` template has been modified.

- `populate_db`
  - **Usage**: Run this **only locally** to generate test data in your local database.

- `manage_notifications`
  - Used to manage and clean up notifications.
  - **Functionality**: Can set notifications as read, sent, or delete them.
