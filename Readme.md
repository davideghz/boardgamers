## Project requirements
- Python 3.9+
- PostgreSQL 16 (**important note**: Postgres 17 is NOT SUPPORTED) with `postgis` extension enabled (see below)
- virtualenv

## First time setup
1. Install PostgreSQL (version 17 is NOT SUPPORTED) with `pg_config` (PostgreSQL dev tools)
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
