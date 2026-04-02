# WINBIRD Enterprise Internal Rental System

Internal Django web application for WINBIRD ENTERPRISE staff to manage rental items, bookings, inventory, payments, and operational tracking.

## Quick start

1. Create and activate a virtual environment.
2. Install dependencies:
   `pip install -r requirements.txt`
3. Run migrations:
   `python manage.py migrate`
4. Create an admin user:
   `python manage.py createsuperuser`
5. Seed the rental catalog:
   `python manage.py seed_winbird_data`
6. Start the server:
   `python manage.py runserver`

## Included pages

- Login
- Dashboard
- Rental items
- Booking list and booking creation
- Booking detail and workflow actions
- Inventory overview
- Payment tracking
- Reports
- Settings

## Design document

See `docs/winbird_internal_system.md` for the full system overview, roles, workflow, data model, and implementation plan.
