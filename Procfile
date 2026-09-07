web: gunicorn config.wsgi --config gunicorn.conf.py
release: python manage.py migrate --noinput && python manage.py collectstatic --noinput
