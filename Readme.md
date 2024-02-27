## GeoDjango dependencies

### PostGIS
#### On Local dev system
```
CREATE EXTENSION postgis;
```
#### Heroku setup
```
heroku pg:psql DATABASE_URL -a example-app
CREATE EXTENSION postgis;
```
Heroku docs [HERE](https://devcenter.heroku.com/articles/heroku-postgres-extensions-postgis-full-text-search#postgis)
___
### GDAL
#### On MacOS
```bash
brew install gdal
```
#### On Linux
```bash
sudo apt-get update
sudo apt-get install libgdal-dev
```
#### On Heroku
Add the buildpack:
```bash
heroku buildpacks:add --index 1 heroku-community/apt
```
Create a file in your application root called Aptfile with the gdal dependency:

**Aptfile**
```
gdal-bin
```
Heroku docs [HERE](https://help.heroku.com/Q0VCG3DE/how-do-i-install-gdal-on-heroku)
