# PostgreSQL Migration Setup

This project now supports PostgreSQL through environment variables in `config/settings.py`.

## 1. Install the PostgreSQL driver

Use the project virtual environment:

```powershell
.\.venv\Scripts\pip.exe install psycopg[binary]
```

If that package name gives trouble in your environment, use:

```powershell
.\.venv\Scripts\pip.exe install psycopg2-binary
```

## 2. Create the PostgreSQL database

Create:

- a database
- a database user
- a strong password

Example values:

- Database: `ppbmed_db`
- User: `ppbmed_user`
- Password: your strong password

## 3. Update `.env.production`

Add or update these values:

```env
POSTGRES_DB=ppbmed_db
POSTGRES_USER=ppbmed_user
POSTGRES_PASSWORD=replace-with-a-strong-postgres-password
POSTGRES_HOST=127.0.0.1
POSTGRES_PORT=5432
POSTGRES_CONN_MAX_AGE=60
POSTGRES_SSLMODE=prefer
```

Important:

- If `POSTGRES_DB` is set, Django will use PostgreSQL.
- If `POSTGRES_DB` is empty, Django falls back to SQLite.

## 4. Export the current SQLite data

From the project root:

```powershell
.\.venv\Scripts\python.exe manage.py dumpdata --exclude contenttypes --exclude auth.permission --indent 2 > data.json
```

## 5. Apply migrations to PostgreSQL

Start Django with the production env file:

```powershell
$env:DJANGO_ENV_FILE=".env.production"
.\.venv\Scripts\python.exe manage.py migrate
```

## 6. Load the data into PostgreSQL

```powershell
$env:DJANGO_ENV_FILE=".env.production"
.\.venv\Scripts\python.exe manage.py loaddata data.json
```

## 7. Create or confirm your admin-side users

If needed:

```powershell
$env:DJANGO_ENV_FILE=".env.production"
.\.venv\Scripts\python.exe manage.py createsuperuser
```

## 8. Verify the migration

Run:

```powershell
$env:DJANGO_ENV_FILE=".env.production"
.\.venv\Scripts\python.exe manage.py check
$env:DJANGO_ENV_FILE=".env.production"
.\.venv\Scripts\python.exe manage.py runserver
```

Then test:

- login
- dashboards by role
- documents list
- routing
- staff page
- login history
- backups and IT Admin pages

## 9. Recommended production follow-up

For more than a few concurrent users, also use:

- PostgreSQL
- Redis
- real HTTPS
- scheduled backups
- a real application server instead of `runserver`

## Notes

- Keep the original `db.sqlite3` as a backup until PostgreSQL is fully confirmed.
- If the production database is empty and this is a fresh deployment, you can skip `dumpdata` and `loaddata` and simply run `migrate`.
