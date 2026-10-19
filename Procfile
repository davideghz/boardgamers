release: ./manage.py migrate
web: gunicorn boardGames.wsgi --workers 2 --threads 4 --log-file -
