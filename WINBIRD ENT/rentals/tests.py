from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from .models import Booking, BookingItem, Category, Customer, Inventory, Notification, Payment, PriceOption, RentalItem
from .services import dispatch_booking_items, return_booking_items


class BookingRuleTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="admin",
            password="pass1234",
            role="ADMIN",
        )
        self.customer = Customer.objects.create(name="Test Customer", phone="0240000000")
        self.category = Category.objects.create(name="Default")
        self.item = RentalItem.objects.create(name="Canopies", category=self.category)
        self.inventory = Inventory.objects.get(rental_item=self.item)
        self.inventory.quantity_total = 5
        self.inventory.quantity_available = 5
        self.inventory.save()
        self.price_option = PriceOption.objects.create(
            rental_item=self.item,
            label="Normal",
            amount=Decimal("40.00"),
            is_default=True,
        )

    def test_cannot_book_more_than_available_stock(self):
        existing = Booking.objects.create(
            customer=self.customer,
            created_by=self.user,
            event_date="2026-04-15",
            return_due_date="2026-04-16",
            status=Booking.Status.CONFIRMED,
        )
        BookingItem.objects.create(
            booking=existing,
            rental_item=self.item,
            price_option=self.price_option,
            quantity=4,
            unit_price=Decimal("40.00"),
        )

        requested = Booking.objects.create(
            customer=self.customer,
            created_by=self.user,
            event_date="2026-04-15",
            return_due_date="2026-04-16",
            status=Booking.Status.PENDING,
        )
        booking_item = BookingItem(
            booking=requested,
            rental_item=self.item,
            price_option=self.price_option,
            quantity=2,
            unit_price=Decimal("40.00"),
        )

        with self.assertRaises(ValidationError):
            booking_item.full_clean()

    def test_payment_status_updates_from_unpaid_to_paid(self):
        booking = Booking.objects.create(
            customer=self.customer,
            created_by=self.user,
            event_date="2026-04-20",
            return_due_date="2026-04-20",
            status=Booking.Status.PENDING,
        )
        BookingItem.objects.create(
            booking=booking,
            rental_item=self.item,
            price_option=self.price_option,
            quantity=2,
            unit_price=Decimal("40.00"),
        )
        booking.refresh_payment_status()
        self.assertEqual(booking.payment_status, Booking.PaymentStatus.UNPAID)

        Payment.objects.create(booking=booking, amount=Decimal("40.00"), recorded_by=self.user)
        booking.refresh_from_db()
        self.assertEqual(booking.payment_status, Booking.PaymentStatus.PARTIAL)

        Payment.objects.create(booking=booking, amount=Decimal("40.00"), recorded_by=self.user)
        booking.refresh_from_db()
        self.assertEqual(booking.payment_status, Booking.PaymentStatus.PAID)

    def test_booking_total_uses_daily_rate_for_each_rental_day(self):
        booking = Booking.objects.create(
            customer=self.customer,
            created_by=self.user,
            event_date="2026-04-20",
            return_due_date="2026-04-21",
            status=Booking.Status.PENDING,
        )
        booking_item = BookingItem.objects.create(
            booking=booking,
            rental_item=self.item,
            price_option=self.price_option,
            quantity=2,
            unit_price=Decimal("40.00"),
        )

        self.assertEqual(booking.rental_days, 2)
        self.assertEqual(booking_item.rental_days, 2)
        self.assertEqual(booking_item.line_total, Decimal("160.00"))
        self.assertEqual(booking.total_amount, Decimal("160.00"))

    def test_dispatch_and_return_adjust_inventory(self):
        booking = Booking.objects.create(
            customer=self.customer,
            created_by=self.user,
            event_date="2026-04-18",
            return_due_date="2026-04-19",
            status=Booking.Status.CONFIRMED,
        )
        BookingItem.objects.create(
            booking=booking,
            rental_item=self.item,
            price_option=self.price_option,
            quantity=3,
            unit_price=Decimal("40.00"),
        )

        dispatch_booking_items(booking)
        self.inventory.refresh_from_db()
        self.assertEqual(self.inventory.quantity_available, 2)

        booking.dispatched_at = "2026-04-18T10:00:00Z"
        return_booking_items(booking)
        self.inventory.refresh_from_db()
        self.assertEqual(self.inventory.quantity_available, 5)


class DashboardRoutingTests(TestCase):
    def setUp(self):
        self.admin_user = get_user_model().objects.create_user(
            username="boss",
            password="pass1234",
            role="ADMIN",
        )
        self.staff_user = get_user_model().objects.create_user(
            username="worker",
            password="pass1234",
            role="STAFF",
        )

    def test_dashboard_redirects_admin_to_admin_dashboard(self):
        self.client.force_login(self.admin_user)
        response = self.client.get(reverse("dashboard"))
        self.assertRedirects(response, reverse("admin-dashboard"))

    def test_dashboard_redirects_staff_to_staff_dashboard(self):
        self.client.force_login(self.staff_user)
        response = self.client.get(reverse("dashboard"))
        self.assertRedirects(response, reverse("staff-dashboard"))

    def test_staff_cannot_open_admin_dashboard(self):
        self.client.force_login(self.staff_user)
        response = self.client.get(reverse("admin-dashboard"))
        self.assertRedirects(response, reverse("staff-dashboard"))

    def test_admin_cannot_open_staff_dashboard(self):
        self.client.force_login(self.admin_user)
        response = self.client.get(reverse("staff-dashboard"))
        self.assertRedirects(response, reverse("admin-dashboard"))


class BookingApprovalPermissionTests(TestCase):
    def setUp(self):
        self.admin_user = get_user_model().objects.create_user(
            username="approvaladmin",
            password="pass1234",
            role="ADMIN",
        )
        self.staff_user = get_user_model().objects.create_user(
            username="approvalstaff",
            password="pass1234",
            role="STAFF",
        )
        self.trusted_staff = get_user_model().objects.create_user(
            username="trustedstaff",
            password="pass1234",
            role="STAFF",
            is_booking_approver=True,
        )
        self.customer = Customer.objects.create(name="Approval Customer", phone="0249999999")
        self.category = Category.objects.create(name="Approval Category")
        self.item = RentalItem.objects.create(name="Approval Chairs", category=self.category)
        self.inventory = Inventory.objects.get(rental_item=self.item)
        self.inventory.quantity_total = 10
        self.inventory.quantity_available = 10
        self.inventory.save()
        self.price_option = PriceOption.objects.create(
            rental_item=self.item,
            label="Standard",
            amount=Decimal("7.00"),
            is_default=True,
        )
        self.booking = Booking.objects.create(
            customer=self.customer,
            created_by=self.staff_user,
            event_date=timezone.localdate(),
            return_due_date=timezone.localdate(),
            status=Booking.Status.PENDING,
        )
        BookingItem.objects.create(
            booking=self.booking,
            rental_item=self.item,
            price_option=self.price_option,
            quantity=2,
            unit_price=Decimal("7.00"),
        )

    def test_regular_staff_cannot_confirm_booking(self):
        self.client.force_login(self.staff_user)
        response = self.client.post(reverse("booking-action", args=[self.booking.pk, "confirm"]))
        self.assertEqual(response.status_code, 403)

    def test_trusted_staff_can_confirm_booking(self):
        self.client.force_login(self.trusted_staff)
        response = self.client.post(reverse("booking-action", args=[self.booking.pk, "confirm"]))
        self.assertRedirects(response, reverse("booking-detail", args=[self.booking.pk]))
        self.booking.refresh_from_db()
        self.assertEqual(self.booking.status, Booking.Status.CONFIRMED)
        self.assertEqual(self.booking.approved_by, self.trusted_staff)

    def test_trusted_staff_cannot_cancel_booking(self):
        self.booking.status = Booking.Status.CONFIRMED
        self.booking.save(update_fields=["status"])
        self.client.force_login(self.trusted_staff)
        response = self.client.post(reverse("booking-action", args=[self.booking.pk, "cancel"]))
        self.assertEqual(response.status_code, 403)


class NotificationPageTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="notify",
            password="pass1234",
            role="STAFF",
        )
        self.customer = Customer.objects.create(name="Notification Customer", phone="0242222222")
        self.booking = Booking.objects.create(
            customer=self.customer,
            created_by=self.user,
            event_date=timezone.localdate(),
            return_due_date=timezone.localdate(),
            status=Booking.Status.PENDING,
        )
        self.inventory_notification = Notification.objects.create(
            title="Low stock",
            message="Canopies are running low.",
            booking=self.booking,
            is_read=False,
        )
        self.plain_notification = Notification.objects.create(
            title="Payment follow-up",
            message="Booking #3 still has a balance.",
            is_read=False,
        )

    def test_notifications_page_loads(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse("notifications"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Notifications")
        self.assertContains(response, "Payment follow-up")
        self.assertNotContains(response, "Low stock")

    def test_inventory_alerts_page_loads(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse("inventory-alerts"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Inventory Alerts")
        self.assertContains(response, "Low stock")
        self.assertNotContains(response, "Payment follow-up")

    def test_post_marks_unread_notifications_as_read(self):
        self.client.force_login(self.user)
        response = self.client.post(reverse("notifications"))
        self.assertRedirects(response, reverse("notifications"))
        self.plain_notification.refresh_from_db()
        self.inventory_notification.refresh_from_db()
        self.assertTrue(self.plain_notification.is_read)
        self.assertFalse(self.inventory_notification.is_read)

    def test_post_marks_unread_inventory_alerts_as_read(self):
        self.client.force_login(self.user)
        response = self.client.post(reverse("inventory-alerts"))
        self.assertRedirects(response, reverse("inventory-alerts"))
        self.plain_notification.refresh_from_db()
        self.inventory_notification.refresh_from_db()
        self.assertFalse(self.plain_notification.is_read)
        self.assertTrue(self.inventory_notification.is_read)

    def test_open_notification_marks_it_read_and_redirects_to_booking(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse("notification-open", args=[self.inventory_notification.pk]))
        self.assertRedirects(response, reverse("booking-detail", args=[self.booking.pk]))
        self.inventory_notification.refresh_from_db()
        self.assertTrue(self.inventory_notification.is_read)

    def test_open_notification_without_booking_returns_to_notifications(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse("notification-open", args=[self.plain_notification.pk]))
        self.assertRedirects(response, reverse("notifications"))


class BookingListFilterTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="staffer",
            password="pass1234",
            role="STAFF",
        )
        self.other_user = get_user_model().objects.create_user(
            username="otherstaff",
            password="pass1234",
            role="STAFF",
        )
        self.customer = Customer.objects.create(name="Filter Customer", phone="0241111111")
        self.today_booking = Booking.objects.create(
            customer=self.customer,
            created_by=self.other_user,
            event_date=timezone.localdate(),
            return_due_date=timezone.localdate(),
            status=Booking.Status.PENDING,
        )
        self.mine_booking = Booking.objects.create(
            customer=self.customer,
            created_by=self.user,
            event_date=timezone.localdate() + timedelta(days=2),
            return_due_date=timezone.localdate() + timedelta(days=2),
            status=Booking.Status.CONFIRMED,
        )

    def test_today_view_filters_to_todays_schedule(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse("booking-list"), {"view": "today"})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, f"#{self.today_booking.pk}")
        self.assertNotContains(response, f"#{self.mine_booking.pk}")

    def test_mine_view_filters_to_current_users_bookings(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse("booking-list"), {"view": "mine"})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, f"#{self.mine_booking.pk}")
        self.assertNotContains(response, f"#{self.today_booking.pk}")


class StaffAccountManagementTests(TestCase):
    def setUp(self):
        self.admin_user = get_user_model().objects.create_user(
            username="settingsadmin",
            password="pass1234",
            role="ADMIN",
        )
        self.staff_user = get_user_model().objects.create_user(
            username="settingsstaff",
            password="pass1234",
            role="STAFF",
        )

    def test_settings_page_does_not_show_django_admin_shortcut(self):
        self.client.force_login(self.admin_user)
        response = self.client.get(reverse("settings"))
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "Django Admin")

    def test_admin_can_create_staff_account_from_settings(self):
        self.client.force_login(self.admin_user)
        response = self.client.post(
            reverse("settings"),
            {
                "username": "newstaff",
                "first_name": "New",
                "last_name": "Worker",
                "email": "newstaff@example.com",
                "password1": "Newstaffpass123!",
                "password2": "Newstaffpass123!",
            },
        )
        self.assertRedirects(response, reverse("settings"))
        created_user = get_user_model().objects.get(username="newstaff")
        self.assertEqual(created_user.role, "STAFF")
        self.assertFalse(created_user.is_superuser)
        self.assertFalse(created_user.is_booking_approver)

    def test_admin_can_create_trusted_booking_approver_from_settings(self):
        self.client.force_login(self.admin_user)
        response = self.client.post(
            reverse("settings"),
            {
                "username": "trustednewstaff",
                "first_name": "Trusted",
                "last_name": "Worker",
                "email": "trustedstaff@example.com",
                "password1": "Trustedpass123!",
                "password2": "Trustedpass123!",
                "is_booking_approver": "on",
            },
        )
        self.assertRedirects(response, reverse("settings"))
        created_user = get_user_model().objects.get(username="trustednewstaff")
        self.assertTrue(created_user.is_booking_approver)

    def test_staff_cannot_create_staff_account_from_settings(self):
        self.client.force_login(self.staff_user)
        response = self.client.post(
            reverse("settings"),
            {
                "username": "blockedstaff",
                "password1": "Blockedpass123!",
                "password2": "Blockedpass123!",
            },
        )
        self.assertEqual(response.status_code, 403)


class OperationsFeatureTests(TestCase):
    def setUp(self):
        self.admin_user = get_user_model().objects.create_user(
            username="opsadmin",
            password="pass1234",
            role="ADMIN",
        )
        self.staff_user = get_user_model().objects.create_user(
            username="opsstaff",
            password="pass1234",
            role="STAFF",
        )
        self.customer = Customer.objects.create(name="Ops Customer", phone="0243333333")
        self.category = Category.objects.create(name="Ops Category")
        self.item = RentalItem.objects.create(name="Ops Chairs", category=self.category)
        self.inventory = Inventory.objects.get(rental_item=self.item)
        self.inventory.quantity_total = 12
        self.inventory.quantity_available = 12
        self.inventory.save()
        self.price_option = PriceOption.objects.create(
            rental_item=self.item,
            label="Standard",
            amount=Decimal("7.00"),
            is_default=True,
        )
        self.booking = Booking.objects.create(
            customer=self.customer,
            created_by=self.staff_user,
            event_date=timezone.localdate(),
            return_due_date=timezone.localdate(),
            status=Booking.Status.CONFIRMED,
        )
        BookingItem.objects.create(
            booking=self.booking,
            rental_item=self.item,
            price_option=self.price_option,
            quantity=2,
            unit_price=Decimal("7.00"),
        )

    def test_booking_search_finds_customer_phone(self):
        self.client.force_login(self.staff_user)
        response = self.client.get(reverse("booking-list"), {"q": self.customer.phone})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, f"#{self.booking.pk}")

    def test_booking_availability_endpoint_returns_json(self):
        self.client.force_login(self.staff_user)
        response = self.client.get(
            reverse("booking-availability"),
            {
                "event_date": timezone.localdate().isoformat(),
                "return_due_date": timezone.localdate().isoformat(),
            },
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(any(row["item"] == self.item.name for row in payload["items"]))

    def test_return_tracker_shows_items_out(self):
        self.booking.dispatched_at = timezone.now()
        self.booking.save(update_fields=["dispatched_at"])
        self.client.force_login(self.staff_user)
        response = self.client.get(reverse("return-tracker"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.customer.name)

    def test_report_export_bookings_returns_csv(self):
        self.client.force_login(self.admin_user)
        response = self.client.get(reverse("report-export", args=["bookings"]))
        self.assertEqual(response.status_code, 200)
        self.assertIn("text/csv", response["Content-Type"])
        self.assertContains(response, self.customer.name)

    def test_reports_use_daily_pricing_for_item_revenue(self):
        extra_booking = Booking.objects.create(
            customer=self.customer,
            created_by=self.staff_user,
            event_date=timezone.localdate(),
            return_due_date=timezone.localdate() + timedelta(days=1),
            status=Booking.Status.CONFIRMED,
        )
        BookingItem.objects.create(
            booking=extra_booking,
            rental_item=self.item,
            price_option=self.price_option,
            quantity=1,
            unit_price=Decimal("7.00"),
        )

        self.client.force_login(self.admin_user)
        response = self.client.get(reverse("reports"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.item.name)
        self.assertContains(response, "GHS 28.00")

    def test_reports_show_monthly_yearly_and_overall_revenue(self):
        today = timezone.localdate()
        same_year_other_month = today.replace(month=1 if today.month != 1 else 2, day=1)
        prior_year_date = today.replace(year=today.year - 1, month=1, day=1)

        Payment.objects.create(
            booking=self.booking,
            amount=Decimal("100.00"),
            recorded_by=self.admin_user,
            paid_on=today,
        )
        Payment.objects.create(
            booking=self.booking,
            amount=Decimal("80.00"),
            recorded_by=self.admin_user,
            paid_on=same_year_other_month,
        )
        Payment.objects.create(
            booking=self.booking,
            amount=Decimal("60.00"),
            recorded_by=self.admin_user,
            paid_on=prior_year_date,
        )

        self.client.force_login(self.admin_user)
        response = self.client.get(reverse("reports"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, f"{today.strftime('%B %Y')} Revenue")
        self.assertContains(response, f"{today.year} Revenue")
        self.assertContains(response, "Overall Revenue")
        self.assertContains(response, "GHS 100.00")
        self.assertContains(response, "GHS 180.00")
        self.assertContains(response, "GHS 240.00")

    def test_admin_can_reset_staff_password_from_settings_tools(self):
        self.client.force_login(self.admin_user)
        response = self.client.post(
            reverse("staff-action", args=[self.staff_user.pk, "reset-password"]),
            follow=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Temporary password for")

    def test_customer_history_page_loads(self):
        self.client.force_login(self.staff_user)
        response = self.client.get(reverse("customer-detail", args=[self.customer.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.customer.name)
        self.assertContains(response, f"#{self.booking.pk}")
        self.assertContains(response, "Balance due")
        self.assertContains(response, "Booking summary")
