## Project requirements
- Python 3.9+
- PostgreSQL 16 (**important note**: Postgres 17+ is NOT SUPPORTED) with `postgis` extension enabled (see below)
- virtualenv
- Docker Desktop (required on Windows)
- PyCharm (recommended) or any IDE of your choice

## First time setup (Linux/MacOS)
1. Install PostgreSQL (versions 17+ are NOT SUPPORTED) with `pg_config` (PostgreSQL dev tools)
2. Install GDAL
```bash
# On MacOS
brew install gdal
```
```bash
# On Linux
sudo apt-get update
sudo apt-get install libgdal-dev
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
5. Make a copy of `local_settings_template.py`, name it `local_settings.py`, and add the right values.
6. Activate virtual environment and install project's dependencies
```
source venv/bin/activate
pip install
```
7. Run migrations
```bash
python manage.py migrate
```
8. Run Django Server
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

### GDAL
Add the buildpack:
```bash
heroku buildpacks:add --index 1 heroku-community/apt
```
Heroku docs [HERE](https://help.heroku.com/Q0VCG3DE/how-do-i-install-gdal-on-heroku)

## Translations
To avoid to generate po file for dependencies, run:
```
python manage.py makemessages -l it -i "venv/*" -i "static/*" -i "migrations/*" -i "node_modules/*"
```
Add your translations, then, in order to compile locales run:
```
python manage.py compilemessages
```

---

## First Time Setup (Windows)

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
- Start the Django container (`.web`)
- Start the PostgreSQL + PostGIS container (`.db`)
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

#### 4.1 Open the project
Open the project folder in **PyCharm**.

#### 4.2 Configure Docker Compose interprete
Go to:
```bash
Settings → Project → Python Interpreter → Add Interpreter
```
Select:
```bash
Docker Compose
```
Then configure:
- Compose file: `.docker-compose.yml`
- Service: `.web`
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

