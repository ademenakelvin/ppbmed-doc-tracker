# WINBIRD ENTERPRISE Internal Staff Rental System

## 1. System Overview

This Django application is an internal staff-only operations system for WINBIRD ENTERPRISE in Breman Asikuma. It helps workers record customer bookings manually, manage rental items and price options, monitor inventory availability, track payments, and move bookings through fulfilment and return.

Daily staff use:

- Staff log in to the dashboard to review pending bookings, upcoming jobs, overdue returns, and stock alerts.
- Staff create bookings from walk-in or phone requests.
- Admins confirm bookings after checking availability.
- Staff record manual payments and mark items out when they leave the store.
- Staff mark items returned after the event, then close completed bookings.

## 2. User Roles and Permissions

### Admin

- View: everything in the application and Django Admin.
- Create: items, prices, bookings, payments, users through admin.
- Edit: all catalog, inventory, and booking records.
- Approve: confirm or cancel bookings.
- Delete: through Django Admin where needed.

### Staff

- View: dashboard, bookings, items, inventory, payments, reports, settings.
- Create: bookings and manual payments.
- Edit: operational progress through out/returned actions.
- Approve: no.
- Delete: no direct delete tools in the main UI.

## 3. Core Features

- Staff authentication and login screen.
- Dashboard with cards for bookings, items out, pending approvals, and catalog size.
- Rental item management with category, active status, inventory, and price options.
- Multiple predefined price options per item.
- Booking creation with customer details, dates, notes, and multiple booking items.
- Availability checks against total inventory and overlapping active bookings.
- Inventory view showing total stock, current available stock, and reserved quantity for today.
- Manual payment capture with automatic unpaid/partial/paid status updates.
- Booking workflow actions: confirm, mark out, mark returned, complete, cancel.
- Notifications and activity log for operational visibility.
- Reports page for revenue totals, booking status mix, payment mix, and most-booked items.

## 4. Booking Workflow

1. Staff receive a customer request by walk-in or phone.
2. Staff create a booking and enter customer name and phone.
3. Staff choose rental items, price options, and quantities.
4. Staff select the event date and return due date.
5. The system checks stock availability for the selected period.
6. The booking is saved as `Pending`.
7. An admin confirms the booking after reviewing availability.
8. Staff record payment manually as unpaid, partial, or paid.
9. When items leave the business, staff mark the booking items as out.
10. After the event, staff mark items returned.
11. Once returned, the booking is marked `Completed`.

## 5. Required Pages

- `Login`: secure staff access.
- `Dashboard`: operational summary, alerts, and recent activity.
- `Rental items`: list of items, stock, and price options.
- `Add/Edit item`: maintain item details, inventory counts, and price options.
- `Booking list`: browse and filter all bookings by status.
- `Create booking`: manual staff booking entry form.
- `Booking detail`: booking summary, items, payments, and workflow actions.
- `Inventory`: stock visibility and quick update links.
- `Payment`: payment list plus payment entry from a booking.
- `Reports`: management summary and trends.
- `Settings`: system notes, roles, assumptions, and operational shortcuts.

## 6. Database Design

### User

- Django custom user model extending `AbstractUser`
- `role`

### Customer

- `name`
- `phone`
- `created_at`
- `updated_at`

### Category

- `name`
- `created_at`

### RentalItem

- `category`
- `name`
- `is_active`
- `created_at`
- `updated_at`

### PriceOption

- `rental_item`
- `label`
- `amount`
- `is_default`
- `is_active`

### Inventory

- `rental_item`
- `quantity_total`
- `quantity_available`
- `updated_at`

### Booking

- `customer`
- `created_by`
- `approved_by`
- `event_date`
- `return_due_date`
- `status`
- `payment_status`
- `notes`
- `approved_at`
- `dispatched_at`
- `returned_at`
- `completed_at`
- `created_at`
- `updated_at`

### BookingItem

- `booking`
- `rental_item`
- `price_option`
- `quantity`
- `unit_price`

### Payment

- `booking`
- `amount`
- `paid_on`
- `recorded_by`
- `notes`
- `created_at`

### Notification

- `title`
- `message`
- `booking`
- `is_read`
- `created_at`

### ActivityLog

- `booking`
- `user`
- `action`
- `created_at`

## 7. Status Design

### Booking Status

- `Pending`
- `Confirmed`
- `Cancelled`
- `Returned`
- `Completed`

### Payment Status

- `Unpaid`
- `Partial`
- `Paid`

## 8. Business Rules

- A booking cannot request more quantity than available stock for overlapping dates.
- A booking must include at least one item.
- Quantity must be greater than zero.
- Customer name and phone are required.
- Prices must come from predefined price options.
- Items must be returned before the booking can be completed.
- Current available stock cannot exceed total stock.

## 9. Django Implementation Plan

App structure:

- `config/` for project settings and root URLs.
- `rentals/` as the main business app.

Key files:

- `rentals/models.py`
- `rentals/forms.py`
- `rentals/views.py`
- `rentals/urls.py`
- `rentals/admin.py`
- `templates/`
- `static/`

Implementation approach:

- Class-based views for page screens and CRUD-style flows.
- Function-based action endpoint for booking state transitions.
- Django Admin enabled for quick staff/user/catalog management.
- SQLite for development, easy migration path to MySQL later.

## 10. UI and UX Guidance

- Dashboard cards for booking counts, active jobs, and alerts.
- Responsive tables for lists of bookings, items, inventory, and payments.
- Sidebar layout for quick navigation between operations pages.
- Structured forms for item setup, bookings, and payments.
- Mobile-friendly CSS with stacked layouts on smaller screens.
- Internal-focus interface with dense operational information and low customer-facing styling overhead.

## 11. Technology Stack

- Backend: Django
- Frontend: HTML, CSS, JavaScript
- Database: SQLite in development, MySQL in production
- Editor: VS Code

## 12. Optional Enhancements

Optional only:

- SMS alerts for booking reminders
- Receipt or invoice generation
- PDF or Excel export for reports
- Dark mode
- Role-specific dashboard views

## Assumptions

- Customers do not log into the application.
- Staff enter all bookings manually.
- Inventory totals can be updated later when physical counts are finalized.
- Payments are recorded manually without online payment integration.
