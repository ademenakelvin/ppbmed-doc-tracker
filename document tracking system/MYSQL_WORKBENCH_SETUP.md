# MySQL Workbench Setup

This project can now use MySQL if you set `DJANGO_DB_ENGINE=mysql` and fill in the MySQL environment variables.

## 1. Install a MySQL driver for Django

Use the project virtual environment:

```powershell
.\.venv\Scripts\pip.exe install mysqlclient
```

If `mysqlclient` gives you build trouble on Windows, use:

```powershell
.\.venv\Scripts\pip.exe install PyMySQL
```

If you use `PyMySQL`, we can wire that in next.

## 2. Create the database in MySQL Workbench

Open MySQL Workbench and run this SQL in a query tab:

```sql
CREATE DATABASE ppbmed_db
  CHARACTER SET utf8mb4
  COLLATE utf8mb4_unicode_ci;

CREATE USER 'ppbmed_user'@'localhost' IDENTIFIED BY 'ChangeThisToAStrongPassword';
GRANT ALL PRIVILEGES ON ppbmed_db.* TO 'ppbmed_user'@'localhost';
FLUSH PRIVILEGES;
```

If Django will connect from another machine, replace `'localhost'` with the correct host pattern.

## 3. Update `.env.production`

Use these values:

```env
DJANGO_DB_ENGINE=mysql
MYSQL_DATABASE=ppbmed_db
MYSQL_USER=ppbmed_user
MYSQL_PASSWORD=ChangeThisToAStrongPassword
MYSQL_HOST=127.0.0.1
MYSQL_PORT=3306
MYSQL_CONN_MAX_AGE=60
MYSQL_CHARSET=utf8mb4
```

## 4. Move the current SQLite data

Export the current data:

```powershell
.\.venv\Scripts\python.exe manage.py dumpdata --exclude contenttypes --exclude auth.permission --indent 2 > data.json
```

## 5. Run migrations on MySQL

Start Django with the production env file:

```powershell
$env:DJANGO_ENV_FILE=".env.production"
.\.venv\Scripts\python.exe manage.py migrate
```

## 6. Load the data into MySQL

```powershell
$env:DJANGO_ENV_FILE=".env.production"
.\.venv\Scripts\python.exe manage.py loaddata data.json
```

## 7. Verify

```powershell
$env:DJANGO_ENV_FILE=".env.production"
.\.venv\Scripts\python.exe manage.py check
$env:DJANGO_ENV_FILE=".env.production"
.\.venv\Scripts\python.exe manage.py runserver
```

Then test:

- login
- dashboards
- documents
- staff
- notifications
- login history
- backups and IT Admin

## Notes

- Keep `db.sqlite3` as a backup until MySQL is confirmed working.
- `utf8mb4` is recommended so text storage is safe and modern.
