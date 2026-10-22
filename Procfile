release: ./manage.py migrate
web: gunicorn boardGames.wsgi --workers 2 --threads 4 --graceful-timeout 20 --log-file -
