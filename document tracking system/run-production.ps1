$env:DJANGO_ENV_FILE = ".env.production"

if (-not $env:DJANGO_DEBUG) {
    $env:DJANGO_DEBUG = "False"
}

Write-Host "Using environment file: $env:DJANGO_ENV_FILE"
Write-Host "Running Django with production-oriented settings..."

python manage.py migrate
if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}

python manage.py runserver 0.0.0.0:8000
