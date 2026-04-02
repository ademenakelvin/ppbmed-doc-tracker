$env:DJANGO_ENV_FILE = ".env.production"

if (-not $env:DJANGO_DEBUG) {
    $env:DJANGO_DEBUG = "False"
}

Write-Host "Using environment file: $env:DJANGO_ENV_FILE"
Write-Host "Starting local production-style test server on HTTP..."
Write-Host "Open this exact address in your browser:"
Write-Host "http://127.0.0.1:8001"

python manage.py runserver 127.0.0.1:8001
