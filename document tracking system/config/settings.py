import os
from pathlib import Path
from importlib.util import find_spec

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent


def load_env_file(path):
    env_path = Path(path)
    if not env_path.exists():
        return

    for raw_line in env_path.read_text(encoding='utf-8').splitlines():
        line = raw_line.strip()
        if not line or line.startswith('#') or '=' not in line:
            continue

        key, value = line.split('=', 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")

        if key and key not in os.environ:
            os.environ[key] = value


load_env_file(BASE_DIR / '.env')
env_file = os.getenv('DJANGO_ENV_FILE')
if env_file:
    load_env_file(BASE_DIR / env_file)


# Quick-start development settings - unsuitable for production


def env_bool(name, default=False):
    return os.getenv(name, str(default)).strip().lower() in {'1', 'true', 'yes', 'on'}


def env_int(name, default):
    return int(os.getenv(name, str(default)).strip())


def postgres_config_from_env():
    db_name = os.getenv('POSTGRES_DB', '').strip()
    if not db_name:
        return None

    return {
        'ENGINE': 'django.db.backends.postgresql',
        'NAME': db_name,
        'USER': os.getenv('POSTGRES_USER', '').strip(),
        'PASSWORD': os.getenv('POSTGRES_PASSWORD', ''),
        'HOST': os.getenv('POSTGRES_HOST', '127.0.0.1').strip(),
        'PORT': os.getenv('POSTGRES_PORT', '5432').strip(),
        'CONN_MAX_AGE': env_int('POSTGRES_CONN_MAX_AGE', 60),
        'OPTIONS': {
            'sslmode': os.getenv('POSTGRES_SSLMODE', 'prefer').strip(),
        },
    }


def mysql_config_from_env():
    db_name = os.getenv('MYSQL_DATABASE', '').strip()
    if not db_name:
        return None

    return {
        'ENGINE': 'django.db.backends.mysql',
        'NAME': db_name,
        'USER': os.getenv('MYSQL_USER', '').strip(),
        'PASSWORD': os.getenv('MYSQL_PASSWORD', ''),
        'HOST': os.getenv('MYSQL_HOST', '127.0.0.1').strip(),
        'PORT': os.getenv('MYSQL_PORT', '3306').strip(),
        'CONN_MAX_AGE': env_int('MYSQL_CONN_MAX_AGE', 60),
        'OPTIONS': {
            'charset': os.getenv('MYSQL_CHARSET', 'utf8mb4').strip(),
        },
    }


DEBUG = env_bool('DJANGO_DEBUG', True)

SECRET_KEY = os.getenv('DJANGO_SECRET_KEY')
if not SECRET_KEY:
    if DEBUG:
        SECRET_KEY = 'django-insecure-dev-only-key-change-me'
    else:
        raise RuntimeError('DJANGO_SECRET_KEY must be set when DEBUG is False.')

default_hosts = '127.0.0.1,localhost'
ALLOWED_HOSTS = [host.strip() for host in os.getenv('DJANGO_ALLOWED_HOSTS', default_hosts).split(',') if host.strip()]


# Application definition
INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',

    'coreapp.apps.CoreappConfig',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'coreapp.middleware.SessionTimeoutMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'config.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'config.wsgi.application'


# Database
db_engine = os.getenv('DJANGO_DB_ENGINE', '').strip().lower()
postgres_database = postgres_config_from_env()
mysql_database = mysql_config_from_env()

if db_engine == 'mysql' and mysql_database:
    DATABASES = {
        'default': mysql_database
    }
elif db_engine in {'postgres', 'postgresql'} and postgres_database:
    DATABASES = {
        'default': postgres_database
    }
elif mysql_database:
    DATABASES = {
        'default': mysql_database
    }
elif postgres_database:
    DATABASES = {
        'default': postgres_database
    }
else:
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.sqlite3',
            'NAME': BASE_DIR / 'db.sqlite3',
        }
    }

cache_backend = os.getenv('DJANGO_CACHE_BACKEND', '').strip().lower()
redis_url = os.getenv('REDIS_URL', '').strip()
redis_package_available = find_spec('redis') is not None

if (cache_backend == 'redis' or redis_url) and redis_package_available:
    CACHES = {
        'default': {
            'BACKEND': 'django.core.cache.backends.redis.RedisCache',
            'LOCATION': redis_url or 'redis://127.0.0.1:6379/1',
        }
    }
else:
    CACHES = {
        'default': {
            'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
            'LOCATION': 'ppbmed-security-cache',
        }
    }


# Password validation
AUTH_PASSWORD_VALIDATORS = [
    {
        'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
        'OPTIONS': {
            'min_length': 10,
        },
    },
    {
        'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator',
    },
]


# Internationalization
LANGUAGE_CODE = 'en-us'

TIME_ZONE = 'Africa/Accra'

USE_I18N = True

USE_TZ = True


# Static files (CSS, JavaScript, Images)
STATIC_URL = '/static/'
STATICFILES_DIRS = [BASE_DIR / 'static']

# Media files
MEDIA_URL = '/media/'
MEDIA_ROOT = BASE_DIR / 'media'


# Default primary key field type
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

CSRF_FAILURE_VIEW = 'django.views.csrf.csrf_failure'

LOGIN_URL = 'login'
LOGIN_REDIRECT_URL = 'dashboard'
LOGOUT_REDIRECT_URL = 'login'

SESSION_COOKIE_AGE = int(os.getenv('SESSION_COOKIE_AGE', '1800'))
SESSION_SAVE_EVERY_REQUEST = True
SESSION_EXPIRE_AT_BROWSER_CLOSE = True
SESSION_IDLE_TIMEOUT = int(os.getenv('SESSION_IDLE_TIMEOUT', '1800'))

LOGIN_RATE_LIMIT_ATTEMPTS = int(os.getenv('LOGIN_RATE_LIMIT_ATTEMPTS', '5'))
LOGIN_RATE_LIMIT_WINDOW = int(os.getenv('LOGIN_RATE_LIMIT_WINDOW', '900'))
TWO_FACTOR_CODE_TTL = int(os.getenv('TWO_FACTOR_CODE_TTL', '300'))
TWO_FACTOR_MAX_ATTEMPTS = int(os.getenv('TWO_FACTOR_MAX_ATTEMPTS', '5'))

SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SECURE = env_bool('SESSION_COOKIE_SECURE', not DEBUG)
CSRF_COOKIE_SECURE = env_bool('CSRF_COOKIE_SECURE', not DEBUG)
CSRF_COOKIE_HTTPONLY = True
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = 'same-origin'
X_FRAME_OPTIONS = 'DENY'

if not DEBUG:
    SECURE_SSL_REDIRECT = env_bool('SECURE_SSL_REDIRECT', True)
    SECURE_HSTS_SECONDS = int(os.getenv('SECURE_HSTS_SECONDS', '31536000'))
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_HSTS_PRELOAD = True
    SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')

EMAIL_BACKEND = os.getenv('EMAIL_BACKEND', 'django.core.mail.backends.console.EmailBackend' if DEBUG else 'django.core.mail.backends.smtp.EmailBackend')
EMAIL_HOST = os.getenv('EMAIL_HOST', 'localhost')
EMAIL_PORT = int(os.getenv('EMAIL_PORT', '25'))
EMAIL_HOST_USER = os.getenv('EMAIL_HOST_USER', '')
EMAIL_HOST_PASSWORD = os.getenv('EMAIL_HOST_PASSWORD', '')
EMAIL_USE_TLS = env_bool('EMAIL_USE_TLS', False)
EMAIL_USE_SSL = env_bool('EMAIL_USE_SSL', False)
DEFAULT_FROM_EMAIL = os.getenv('DEFAULT_FROM_EMAIL', 'no-reply@ppbmed.local')

SMS_BACKEND = os.getenv('SMS_BACKEND', 'console').strip().lower()
SMS_FROM = os.getenv('SMS_FROM', 'PPBMED')
