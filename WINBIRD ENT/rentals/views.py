import calendar
import csv
from collections import defaultdict
from datetime import datetime
from decimal import Decimal

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.contrib.auth.views import LoginView
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import Count, F, Q, Sum
from django.http import Http404, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.crypto import get_random_string
from django.utils.dateparse import parse_date
from django.utils.http import url_has_allowed_host_and_scheme
from django.utils import timezone
from django.views import View
from django.views.decorators.http import require_POST
from django.views.generic import DetailView, ListView, RedirectView, TemplateView

from .forms import (
    BookingCreateForm,
    BookingItemFormSet,
    InventoryForm,
    LoginForm,
    PaymentForm,
    PriceOptionFormSet,
    RentalItemForm,
    StaffAccountForm,
    StaffAccountUpdateForm,
)
from .models import ActivityLog, Booking, BookingItem, Category, Customer, Inventory, Notification, Payment, RentalItem, User
from .notification_utils import (
    GENERAL_NOTIFICATION_KIND_LABELS,
    filter_notifications,
    group_notifications,
    notification_kind,
)
from .services import create_notification, dispatch_booking_items, log_activity, return_booking_items


def ensure_default_category():
    if not Category.objects.exists():
        Category.objects.create(name="Default")


def notification_redirect_name(notification):
    return "inventory-alerts" if notification_kind(notification) == "inventory" else "notifications"


def notification_redirect(request, notification):
    next_url = request.POST.get("next") or request.GET.get("next")
    if next_url and url_has_allowed_host_and_scheme(
        next_url,
        allowed_hosts={request.get_host()},
        require_https=request.is_secure(),
    ):
        return redirect(next_url)
    return redirect(notification_redirect_name(notification))


class AdminRequiredMixin(UserPassesTestMixin):
    def test_func(self):
        return self.request.user.is_authenticated and self.request.user.can_manage_catalog

    def handle_no_permission(self):
        raise PermissionDenied("Only admins can manage catalog and admin-only actions.")


class HomeRedirectView(RedirectView):
    permanent = False

    def get_redirect_url(self, *args, **kwargs):
        if self.request.user.is_authenticated:
            return reverse("dashboard")
        return reverse("login")


class StaffLoginView(LoginView):
    template_name = "registration/login.html"
    authentication_form = LoginForm
    redirect_authenticated_user = True


class RoleDashboardRedirectView(LoginRequiredMixin, RedirectView):
    permanent = False

    def get_redirect_url(self, *args, **kwargs):
        if self.request.user.can_manage_catalog:
            return reverse("admin-dashboard")
        return reverse("staff-dashboard")


class DashboardBaseView(LoginRequiredMixin, TemplateView):
    def get_base_context(self):
        today = timezone.localdate()
        outstanding_bookings = Booking.objects.exclude(payment_status=Booking.PaymentStatus.PAID).exclude(
            status=Booking.Status.CANCELLED
        )
        overdue_returns = Booking.objects.filter(
            status=Booking.Status.CONFIRMED,
            dispatched_at__isnull=False,
            return_due_date__lt=today,
        ).select_related("customer")

        return {
            "today": today,
            "recent_activity": ActivityLog.objects.select_related("user", "booking")[:8],
            "status_summary": Booking.objects.values("status").annotate(total=Count("id")).order_by("status"),
            "upcoming_bookings": Booking.objects.filter(
                event_date__gte=today,
                status__in=[Booking.Status.PENDING, Booking.Status.CONFIRMED],
            ).select_related("customer")[:6],
            "overdue_returns": overdue_returns[:5],
            "outstanding_bookings": outstanding_bookings.select_related("customer")[:6],
            "outstanding_count": outstanding_bookings.count(),
            "out_of_stock": Inventory.objects.filter(quantity_available=0).select_related("rental_item")[:6],
            "low_stock_items": Inventory.objects.filter(
                quantity_total__gt=0,
                quantity_available__lte=3,
            ).select_related("rental_item")[:6],
            "pending_bookings": Booking.objects.filter(status=Booking.Status.PENDING).count(),
            "active_rentals": Booking.objects.filter(
                status=Booking.Status.CONFIRMED,
                dispatched_at__isnull=False,
            ).count(),
            "total_items": RentalItem.objects.count(),
            "total_bookings": Booking.objects.count(),
            "total_revenue": Payment.objects.aggregate(total=Sum("amount"))["total"] or Decimal("0.00"),
        }

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(self.get_base_context())
        return context


class AdminDashboardView(DashboardBaseView):
    template_name = "rentals/admin_dashboard.html"

    def dispatch(self, request, *args, **kwargs):
        if not request.user.can_manage_catalog:
            return redirect("staff-dashboard")
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(
            {
                "dashboard_variant": "admin",
                "dashboard_title": "Admin Dashboard",
                "dashboard_kicker": "Management overview",
                "staff_count": User.objects.filter(role=User.Role.STAFF, is_active=True).count(),
                "admin_count": User.objects.filter(role=User.Role.ADMIN, is_active=True).count(),
                "pending_approvals": Booking.objects.filter(status=Booking.Status.PENDING)
                .select_related("customer", "created_by")[:6],
                "recent_payments": Payment.objects.select_related("booking__customer", "recorded_by")[:6],
            }
        )
        return context


class StaffDashboardView(DashboardBaseView):
    template_name = "rentals/staff_dashboard.html"

    def dispatch(self, request, *args, **kwargs):
        if request.user.can_manage_catalog:
            return redirect("admin-dashboard")
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        today = context["today"]
        user = self.request.user
        my_bookings = Booking.objects.filter(created_by=user).select_related("customer")
        my_active_jobs = my_bookings.filter(
            status=Booking.Status.CONFIRMED,
            dispatched_at__isnull=False,
        )
        today_jobs = Booking.objects.filter(
            event_date=today,
            status__in=[Booking.Status.PENDING, Booking.Status.CONFIRMED],
        ).select_related("customer")

        context.update(
            {
                "dashboard_variant": "staff",
                "dashboard_title": "Staff Dashboard",
                "dashboard_kicker": "Daily operations",
                "my_bookings_count": my_bookings.count(),
                "my_active_jobs_count": my_active_jobs.count(),
                "today_jobs_count": today_jobs.count(),
                "my_payments_count": Payment.objects.filter(recorded_by=user).count(),
                "my_recent_bookings": my_bookings[:6],
                "today_jobs": today_jobs[:6],
                "returns_due_today": Booking.objects.filter(
                    status=Booking.Status.CONFIRMED,
                    dispatched_at__isnull=False,
                    return_due_date__lte=today,
                ).select_related("customer")[:6],
            }
        )
        return context


class RentalItemListView(LoginRequiredMixin, ListView):
    template_name = "rentals/item_list.html"
    context_object_name = "items"

    def get_queryset(self):
        return RentalItem.objects.select_related("category", "inventory").prefetch_related("price_options")


class RentalItemCreateView(LoginRequiredMixin, AdminRequiredMixin, View):
    template_name = "rentals/item_form.html"

    def get(self, request):
        ensure_default_category()
        context = {
            "form": RentalItemForm(),
            "inventory_form": InventoryForm(),
            "price_formset": PriceOptionFormSet(prefix="prices"),
            "page_title": "Add Rental Item",
        }
        return render(request, self.template_name, context)

    def post(self, request):
        ensure_default_category()
        form = RentalItemForm(request.POST)
        inventory_form = InventoryForm(request.POST)
        price_formset = PriceOptionFormSet(request.POST, prefix="prices")
        if form.is_valid() and inventory_form.is_valid() and price_formset.is_valid():
            with transaction.atomic():
                item = form.save()
                inventory = item.inventory
                inventory.quantity_total = inventory_form.cleaned_data["quantity_total"]
                inventory.quantity_available = inventory_form.cleaned_data["quantity_available"]
                inventory.save()
                price_formset.instance = item
                price_formset.save()
                log_activity(request.user, f"Created rental item {item.name}.")
            messages.success(request, "Rental item created successfully.")
            return redirect("item-list")

        return render(
            request,
            self.template_name,
            {
                "form": form,
                "inventory_form": inventory_form,
                "price_formset": price_formset,
                "page_title": "Add Rental Item",
            },
        )


class RentalItemUpdateView(LoginRequiredMixin, AdminRequiredMixin, View):
    template_name = "rentals/item_form.html"

    def get_object(self, pk):
        return get_object_or_404(RentalItem, pk=pk)

    def get(self, request, pk):
        item = self.get_object(pk)
        inventory, _ = Inventory.objects.get_or_create(
            rental_item=item,
            defaults={"quantity_total": 0, "quantity_available": 0},
        )
        return render(
            request,
            self.template_name,
            {
                "form": RentalItemForm(instance=item),
                "inventory_form": InventoryForm(instance=inventory),
                "price_formset": PriceOptionFormSet(instance=item, prefix="prices"),
                "page_title": f"Edit {item.name}",
                "item": item,
            },
        )

    def post(self, request, pk):
        item = self.get_object(pk)
        inventory, _ = Inventory.objects.get_or_create(
            rental_item=item,
            defaults={"quantity_total": 0, "quantity_available": 0},
        )
        form = RentalItemForm(request.POST, instance=item)
        inventory_form = InventoryForm(request.POST, instance=inventory)
        price_formset = PriceOptionFormSet(request.POST, instance=item, prefix="prices")
        if form.is_valid() and inventory_form.is_valid() and price_formset.is_valid():
            with transaction.atomic():
                item = form.save()
                inventory_form.save()
                price_formset.save()
                log_activity(request.user, f"Updated rental item {item.name}.")
            messages.success(request, "Rental item updated successfully.")
            return redirect("item-list")

        return render(
            request,
            self.template_name,
            {
                "form": form,
                "inventory_form": inventory_form,
                "price_formset": price_formset,
                "page_title": f"Edit {item.name}",
                "item": item,
            },
        )


class BookingListView(LoginRequiredMixin, ListView):
    template_name = "rentals/booking_list.html"
    context_object_name = "bookings"
    paginate_by = 20

    def get_filtered_queryset(self):
        queryset = Booking.objects.select_related("customer", "created_by", "approved_by").prefetch_related("items")
        selected_view = self.request.GET.get("view", "")
        search = self.request.GET.get("q", "").strip()
        status = self.request.GET.get("status", "")
        payment_status = self.request.GET.get("payment_status", "")
        event_date = self.request.GET.get("event_date", "")
        date_from = self.request.GET.get("date_from", "")
        date_to = self.request.GET.get("date_to", "")

        if selected_view == "today":
            queryset = queryset.filter(event_date=timezone.localdate())
        elif selected_view == "mine":
            queryset = queryset.filter(created_by=self.request.user)

        if search:
            search_term = search.lstrip("#")
            search_query = Q(customer__name__icontains=search) | Q(customer__phone__icontains=search)
            if search_term.isdigit():
                search_query |= Q(pk=int(search_term))
            queryset = queryset.filter(search_query)

        if status:
            queryset = queryset.filter(status=status)

        if payment_status:
            queryset = queryset.filter(payment_status=payment_status)

        if event_date:
            queryset = queryset.filter(event_date=event_date)

        if date_from:
            queryset = queryset.filter(event_date__gte=date_from)

        if date_to:
            queryset = queryset.filter(event_date__lte=date_to)

        return queryset.order_by("event_date", "created_at")

    def get_queryset(self):
        return self.get_filtered_queryset()

    def get_paginate_by(self, queryset):
        if self.request.GET.get("display") == "calendar":
            return None
        return self.paginate_by

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        selected_view = self.request.GET.get("view", "")
        display_mode = self.request.GET.get("display", "list")
        selected_status = self.request.GET.get("status", "")
        selected_payment_status = self.request.GET.get("payment_status", "")
        selected_event_date = self.request.GET.get("event_date", "")
        selected_date_from = self.request.GET.get("date_from", "")
        selected_date_to = self.request.GET.get("date_to", "")
        search_query = self.request.GET.get("q", "").strip()
        query_params = self.request.GET.copy()
        if "page" in query_params:
            query_params.pop("page")

        scope_params = query_params.copy()
        if "view" in scope_params:
            scope_params.pop("view")

        display_params = query_params.copy()
        if "display" in display_params:
            display_params.pop("display")
        if "month" in display_params:
            display_params.pop("month")

        status_params = query_params.copy()
        if "status" in status_params:
            status_params.pop("status")

        payment_params = query_params.copy()
        if "payment_status" in payment_params:
            payment_params.pop("payment_status")

        if selected_view == "today":
            active_view_label = "Today's schedule"
            active_view_copy = "Showing bookings scheduled for today."
        elif selected_view == "mine":
            active_view_label = "My bookings"
            active_view_copy = "Showing bookings you created."
        else:
            active_view_label = "All bookings"
            active_view_copy = "Showing the full booking register."

        context["selected_view"] = selected_view
        context["display_mode"] = display_mode
        context["selected_status"] = selected_status
        context["selected_payment_status"] = selected_payment_status
        context["selected_event_date"] = selected_event_date
        context["selected_date_from"] = selected_date_from
        context["selected_date_to"] = selected_date_to
        context["search_query"] = search_query
        context["status_choices"] = Booking.Status.choices
        context["payment_status_choices"] = Booking.PaymentStatus.choices
        context["active_view_label"] = active_view_label
        context["active_view_copy"] = active_view_copy
        context["page_query"] = query_params.urlencode()
        context["scope_query"] = scope_params.urlencode()
        context["display_query"] = display_params.urlencode()
        context["status_query"] = status_params.urlencode()
        context["payment_query"] = payment_params.urlencode()

        month_value = self.request.GET.get("month") or timezone.localdate().strftime("%Y-%m")
        try:
            selected_month = datetime.strptime(month_value, "%Y-%m").date().replace(day=1)
        except ValueError:
            selected_month = timezone.localdate().replace(day=1)
            month_value = selected_month.strftime("%Y-%m")

        if display_mode == "calendar":
            month_start = selected_month
            month_end = selected_month.replace(
                day=calendar.monthrange(selected_month.year, selected_month.month)[1]
            )
            calendar_queryset = self.get_filtered_queryset().filter(
                event_date__gte=month_start,
                event_date__lte=month_end,
            )
            bookings_by_date = defaultdict(list)
            for booking in calendar_queryset:
                bookings_by_date[booking.event_date].append(booking)

            weeks = []
            for week in calendar.Calendar(firstweekday=0).monthdatescalendar(selected_month.year, selected_month.month):
                week_days = []
                for day in week:
                    week_days.append(
                        {
                            "date": day,
                            "in_month": day.month == selected_month.month,
                            "is_today": day == timezone.localdate(),
                            "bookings": bookings_by_date.get(day, []),
                        }
                    )
                weeks.append(week_days)

            previous_month = selected_month.month - 1 or 12
            previous_year = selected_month.year - 1 if selected_month.month == 1 else selected_month.year
            next_month = 1 if selected_month.month == 12 else selected_month.month + 1
            next_year = selected_month.year + 1 if selected_month.month == 12 else selected_month.year

            calendar_params = self.request.GET.copy()
            calendar_params["display"] = "calendar"
            if "page" in calendar_params:
                calendar_params.pop("page")

            previous_params = calendar_params.copy()
            previous_params["month"] = f"{previous_year}-{previous_month:02d}"

            next_params = calendar_params.copy()
            next_params["month"] = f"{next_year}-{next_month:02d}"

            context["calendar_weeks"] = weeks
            context["calendar_month"] = selected_month
            context["calendar_month_value"] = month_value
            context["calendar_previous_query"] = previous_params.urlencode()
            context["calendar_next_query"] = next_params.urlencode()
        return context


class BookingCreateView(LoginRequiredMixin, View):
    template_name = "rentals/booking_form.html"

    def get(self, request):
        form = BookingCreateForm(
            initial={"event_date": timezone.localdate(), "return_due_date": timezone.localdate()}
        )
        item_formset = BookingItemFormSet(prefix="items")
        return render(
            request,
            self.template_name,
            {"form": form, "item_formset": item_formset, "page_title": "Create Booking"},
        )

    def post(self, request):
        form = BookingCreateForm(request.POST)
        event_date = None
        return_due_date = None
        if form.is_valid():
            event_date = form.cleaned_data["event_date"]
            return_due_date = form.cleaned_data["return_due_date"]

        item_formset = BookingItemFormSet(
            request.POST,
            prefix="items",
            event_date=event_date,
            return_due_date=return_due_date,
        )

        if form.is_valid() and item_formset.is_valid():
            with transaction.atomic():
                customer, created = Customer.objects.get_or_create(
                    phone=form.cleaned_data["customer_phone"],
                    defaults={"name": form.cleaned_data["customer_name"]},
                )
                if not created and customer.name != form.cleaned_data["customer_name"]:
                    customer.name = form.cleaned_data["customer_name"]
                    customer.save(update_fields=["name", "updated_at"])

                booking = Booking.objects.create(
                    customer=customer,
                    created_by=request.user,
                    event_date=form.cleaned_data["event_date"],
                    return_due_date=form.cleaned_data["return_due_date"],
                    notes=form.cleaned_data["notes"],
                    status=Booking.Status.PENDING,
                )

                for cleaned_data in item_formset.cleaned_data:
                    if not cleaned_data or cleaned_data.get("DELETE"):
                        continue
                    BookingItem.objects.create(
                        booking=booking,
                        rental_item=cleaned_data["rental_item"],
                        price_option=cleaned_data["price_option"],
                        quantity=cleaned_data["quantity"],
                        unit_price=cleaned_data["price_option"].amount,
                    )

                booking.refresh_payment_status()
                create_notification(
                    "Pending booking",
                    f"Booking #{booking.pk} for {booking.customer.name} is waiting for confirmation.",
                    booking=booking,
                )
                log_activity(request.user, f"Created booking #{booking.pk}.", booking=booking)

            messages.success(request, "Booking saved as pending.")
            return redirect("booking-detail", pk=booking.pk)

        return render(
            request,
            self.template_name,
            {"form": form, "item_formset": item_formset, "page_title": "Create Booking"},
        )


class BookingDetailView(LoginRequiredMixin, DetailView):
    template_name = "rentals/booking_detail.html"
    context_object_name = "booking"

    def get_queryset(self):
        return Booking.objects.select_related("customer", "created_by", "approved_by").prefetch_related(
            "items__rental_item",
            "items__price_option",
            "payments__recorded_by",
            "activity_logs__user",
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        booking = context["booking"]
        timeline_entries = [
            {
                "title": "Booking created",
                "timestamp": booking.created_at,
                "detail": f"Created by {booking.created_by}",
                "complete": True,
            },
            {
                "title": "Booking confirmed",
                "timestamp": booking.approved_at,
                "detail": f"Confirmed by {booking.approved_by}" if booking.approved_by else "Waiting for booking confirmation",
                "complete": bool(booking.approved_at),
            },
            {
                "title": "Payment settled",
                "timestamp": booking.payments.order_by("-paid_on", "-created_at").first().created_at if booking.payments.exists() else None,
                "detail": (
                    f"Paid in full. Balance due is GHS {booking.balance_due:.2f}."
                    if booking.payment_status == Booking.PaymentStatus.PAID
                    else f"Current payment status: {booking.get_payment_status_display()}"
                ),
                "complete": booking.payment_status == Booking.PaymentStatus.PAID,
            },
            {
                "title": "Items dispatched",
                "timestamp": booking.dispatched_at,
                "detail": "Items have been marked as out." if booking.dispatched_at else "Items are still waiting to go out.",
                "complete": bool(booking.dispatched_at),
            },
            {
                "title": "Items returned",
                "timestamp": booking.returned_at,
                "detail": "All items were returned." if booking.returned_at else "Return still pending.",
                "complete": bool(booking.returned_at),
            },
            {
                "title": "Booking completed",
                "timestamp": booking.completed_at,
                "detail": "Rental job is fully closed." if booking.completed_at else "Completion still pending.",
                "complete": bool(booking.completed_at),
            },
        ]
        context["timeline_entries"] = timeline_entries
        return context


class CustomerDetailView(LoginRequiredMixin, DetailView):
    template_name = "rentals/customer_detail.html"
    context_object_name = "customer"

    def get_queryset(self):
        return Customer.objects.all()

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        customer = context["customer"]
        bookings = list(
            customer.bookings.select_related("created_by", "approved_by").prefetch_related("items", "payments").order_by(
                "-event_date", "-created_at"
            )
        )
        today = timezone.localdate()
        upcoming_bookings = sorted(
            [booking for booking in bookings if booking.status != Booking.Status.CANCELLED and booking.event_date >= today],
            key=lambda booking: (booking.event_date, booking.created_at),
        )
        spotlight_booking = upcoming_bookings[0] if upcoming_bookings else (bookings[0] if bookings else None)
        context.update(
            {
                "bookings": bookings,
                "total_bookings": len(bookings),
                "total_spend": sum((booking.amount_paid for booking in bookings), Decimal("0.00")),
                "active_bookings_count": sum(
                    1
                    for booking in bookings
                    if booking.status in [Booking.Status.PENDING, Booking.Status.CONFIRMED, Booking.Status.RETURNED]
                ),
                "outstanding_balance": sum(
                    (
                        booking.balance_due
                        for booking in bookings
                        if booking.status != Booking.Status.CANCELLED and booking.balance_due > Decimal("0.00")
                    ),
                    Decimal("0.00"),
                ),
                "spotlight_booking": spotlight_booking,
                "spotlight_title": "Next booking" if spotlight_booking and spotlight_booking.event_date >= today else "Latest booking",
            }
        )
        return context


@login_required
@require_POST
def booking_action(request, pk, action):
    booking = get_object_or_404(
        Booking.objects.select_related("customer").prefetch_related("items__rental_item__inventory"),
        pk=pk,
    )

    try:
        with transaction.atomic():
            if action == "confirm":
                if not request.user.can_confirm_bookings:
                    raise PermissionDenied("Only admins or trusted booking approvers can confirm bookings.")
                if booking.status != Booking.Status.PENDING:
                    raise ValidationError("Only pending bookings can be confirmed.")
                for booking_item in booking.items.select_related("rental_item__inventory"):
                    inventory = Inventory.objects.get(rental_item=booking_item.rental_item)
                    available = inventory.available_for_range(
                        booking.event_date,
                        booking.return_due_date,
                        exclude_booking=booking,
                    )
                    if booking_item.quantity > available:
                        raise ValidationError(
                            f"{booking_item.rental_item.name} no longer has enough stock for these dates."
                        )
                booking.status = Booking.Status.CONFIRMED
                booking.approved_by = request.user
                booking.approved_at = timezone.now()
                booking.save(update_fields=["status", "approved_by", "approved_at", "updated_at"])
                create_notification(
                    "Booking confirmed",
                    f"Booking #{booking.pk} has been confirmed.",
                    booking=booking,
                )
                log_activity(request.user, f"Confirmed booking #{booking.pk}.", booking=booking)
                messages.success(request, "Booking confirmed.")
            elif action == "cancel":
                if not request.user.can_cancel_bookings:
                    raise PermissionDenied("Only admins can cancel bookings.")
                if booking.dispatched_at and not booking.returned_at:
                    raise ValidationError("Return the items before cancelling this booking.")
                if booking.status == Booking.Status.COMPLETED:
                    raise ValidationError("Completed bookings cannot be cancelled.")
                booking.status = Booking.Status.CANCELLED
                booking.save(update_fields=["status", "updated_at"])
                create_notification(
                    "Booking cancelled",
                    f"Booking #{booking.pk} has been cancelled.",
                    booking=booking,
                )
                log_activity(request.user, f"Cancelled booking #{booking.pk}.", booking=booking)
                messages.success(request, "Booking cancelled.")
            elif action == "mark_out":
                if booking.status != Booking.Status.CONFIRMED:
                    raise ValidationError("Only confirmed bookings can be marked as out.")
                dispatch_booking_items(booking)
                booking.dispatched_at = timezone.now()
                booking.save(update_fields=["dispatched_at", "updated_at"])
                log_activity(request.user, f"Marked booking #{booking.pk} items as out.", booking=booking)
                messages.success(request, "Items marked as out.")
            elif action == "mark_returned":
                if booking.status != Booking.Status.CONFIRMED:
                    raise ValidationError("Only confirmed bookings can be returned.")
                return_booking_items(booking)
                booking.status = Booking.Status.RETURNED
                booking.returned_at = timezone.now()
                booking.save(update_fields=["status", "returned_at", "updated_at"])
                log_activity(request.user, f"Returned items for booking #{booking.pk}.", booking=booking)
                messages.success(request, "Items marked as returned.")
            elif action == "complete":
                if not booking.can_be_completed:
                    raise ValidationError("Items must be returned before a booking can be completed.")
                booking.status = Booking.Status.COMPLETED
                booking.completed_at = timezone.now()
                booking.save(update_fields=["status", "completed_at", "updated_at"])
                log_activity(request.user, f"Completed booking #{booking.pk}.", booking=booking)
                messages.success(request, "Booking marked as completed.")
            else:
                raise Http404("Unknown booking action.")
    except PermissionDenied:
        raise
    except ValidationError as exc:
        messages.error(request, exc.messages[0] if hasattr(exc, "messages") else str(exc))

    return redirect("booking-detail", pk=booking.pk)


class InventoryListView(LoginRequiredMixin, TemplateView):
    template_name = "rentals/inventory.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        today = timezone.localdate()
        context["inventory_rows"] = [
            {
                "inventory": inventory,
                "reserved_today": inventory.reserved_quantity(today, today),
            }
            for inventory in Inventory.objects.select_related("rental_item", "rental_item__category")
        ]
        context["today"] = today
        return context


class ReturnTrackerView(LoginRequiredMixin, TemplateView):
    template_name = "rentals/returns.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        today = timezone.localdate()
        active_returns = Booking.objects.filter(
            status=Booking.Status.CONFIRMED,
            dispatched_at__isnull=False,
        ).select_related("customer", "created_by")

        context.update(
            {
                "today": today,
                "overdue_returns": active_returns.filter(return_due_date__lt=today),
                "returns_due_today": active_returns.filter(return_due_date=today),
                "items_out": active_returns.order_by("return_due_date", "event_date"),
            }
        )
        return context


@login_required
def booking_availability(request):
    event_date = parse_date(request.GET.get("event_date", ""))
    return_due_date = parse_date(request.GET.get("return_due_date", ""))

    if not event_date or not return_due_date:
        return JsonResponse({"error": "Choose both event and return dates first."}, status=400)

    if return_due_date < event_date:
        return JsonResponse({"error": "Return due date cannot be earlier than the event date."}, status=400)

    rows = []
    inventories = Inventory.objects.select_related("rental_item", "rental_item__category").prefetch_related(
        "rental_item__price_options"
    )
    for inventory in inventories:
        rental_item = inventory.rental_item
        available = inventory.available_for_range(event_date, return_due_date)
        price_labels = ", ".join(
            f"{option.label} - GHS {option.amount:.2f}/day"
            for option in rental_item.price_options.filter(is_active=True)
        )
        rows.append(
            {
                "item": rental_item.name,
                "category": rental_item.category.name,
                "available": available,
                "total": inventory.quantity_total,
                "price_labels": price_labels,
                "status": "available" if available > 0 else "unavailable",
            }
        )

    rows.sort(key=lambda row: (row["available"] == 0, row["item"]))
    return JsonResponse({"items": rows})


class PaymentListView(LoginRequiredMixin, ListView):
    template_name = "rentals/payment_list.html"
    context_object_name = "payments"
    paginate_by = 20

    def get_queryset(self):
        return Payment.objects.select_related("booking__customer", "recorded_by")


class PaymentCreateView(LoginRequiredMixin, View):
    template_name = "rentals/payment_form.html"

    def get_booking(self, booking_pk):
        return get_object_or_404(Booking.objects.select_related("customer"), pk=booking_pk)

    def get(self, request, booking_pk):
        booking = self.get_booking(booking_pk)
        form = PaymentForm(initial={"paid_on": timezone.localdate()})
        return render(request, self.template_name, {"form": form, "booking": booking})

    def post(self, request, booking_pk):
        booking = self.get_booking(booking_pk)
        form = PaymentForm(request.POST)
        if form.is_valid():
            with transaction.atomic():
                payment = form.save(commit=False)
                payment.booking = booking
                payment.recorded_by = request.user
                payment.save()
                if booking.balance_due > Decimal("0.00"):
                    create_notification(
                        "Payment reminder",
                        f"Booking #{booking.pk} still has a balance of GHS {booking.balance_due:.2f}.",
                        booking=booking,
                    )
                else:
                    create_notification(
                        "Booking fully paid",
                        f"Booking #{booking.pk} is now fully paid.",
                        booking=booking,
                    )
                log_activity(
                    request.user,
                    f"Recorded payment of GHS {payment.amount} for booking #{booking.pk}.",
                    booking=booking,
                )
            messages.success(request, "Payment recorded.")
            return redirect("booking-detail", pk=booking.pk)
        return render(request, self.template_name, {"form": form, "booking": booking})


class BookingReceiptView(LoginRequiredMixin, DetailView):
    template_name = "rentals/booking_receipt.html"
    context_object_name = "booking"

    def get_queryset(self):
        return Booking.objects.select_related("customer", "created_by", "approved_by").prefetch_related(
            "items__rental_item",
            "items__price_option",
            "payments__recorded_by",
        )


class PaymentReceiptView(LoginRequiredMixin, DetailView):
    template_name = "rentals/payment_receipt.html"
    context_object_name = "payment"

    def get_queryset(self):
        return Payment.objects.select_related("booking__customer", "recorded_by")


class ReportsView(LoginRequiredMixin, TemplateView):
    template_name = "rentals/reports.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        today = timezone.localdate()
        item_revenue_totals = defaultdict(lambda: Decimal("0.00"))
        for booking_item in BookingItem.objects.select_related("booking", "rental_item"):
            item_revenue_totals[booking_item.rental_item.name] += booking_item.line_total

        item_revenue = [
            {"item_name": item_name, "revenue": revenue}
            for item_name, revenue in sorted(item_revenue_totals.items(), key=lambda item: (-item[1], item[0]))[:8]
        ]
        current_month_revenue = (
            Payment.objects.filter(paid_on__year=today.year, paid_on__month=today.month).aggregate(total=Sum("amount"))["total"]
            or Decimal("0.00")
        )
        current_year_revenue = (
            Payment.objects.filter(paid_on__year=today.year).aggregate(total=Sum("amount"))["total"]
            or Decimal("0.00")
        )
        overall_revenue = Payment.objects.aggregate(total=Sum("amount"))["total"] or Decimal("0.00")
        context.update(
            {
                "current_month_revenue": current_month_revenue,
                "current_month_label": today.strftime("%B %Y"),
                "current_year_revenue": current_year_revenue,
                "current_year_label": str(today.year),
                "overall_revenue": overall_revenue,
                "outstanding_bookings": Booking.objects.exclude(payment_status=Booking.PaymentStatus.PAID).exclude(
                    status=Booking.Status.CANCELLED
                ).count(),
                "completed_bookings": Booking.objects.filter(status=Booking.Status.COMPLETED).count(),
                "status_breakdown": Booking.objects.values("status").annotate(total=Count("id")).order_by("status"),
                "payment_breakdown": Booking.objects.values("payment_status").annotate(total=Count("id")).order_by("payment_status"),
                "top_items": BookingItem.objects.values(item_name=F("rental_item__name"))
                .annotate(total_quantity=Sum("quantity"))
                .order_by("-total_quantity", "item_name")[:8],
                "top_revenue_items": item_revenue,
                "activity_by_staff": ActivityLog.objects.values(
                    staff_name=F("user__username")
                ).annotate(total_actions=Count("id")).order_by("-total_actions", "staff_name")[:8],
            }
        )
        return context


@login_required
def report_export(request, report_type):
    if report_type == "bookings":
        response = HttpResponse(content_type="text/csv")
        response["Content-Disposition"] = 'attachment; filename="winbird-bookings-report.csv"'
        writer = csv.writer(response)
        writer.writerow(
            [
                "Booking ID",
                "Customer",
                "Phone",
                "Event Date",
                "Return Due",
                "Status",
                "Payment Status",
                "Total Amount",
                "Amount Paid",
                "Balance Due",
            ]
        )
        for booking in Booking.objects.select_related("customer"):
            writer.writerow(
                [
                    booking.pk,
                    booking.customer.name,
                    booking.customer.phone,
                    booking.event_date,
                    booking.return_due_date,
                    booking.get_status_display(),
                    booking.get_payment_status_display(),
                    booking.total_amount,
                    booking.amount_paid,
                    booking.balance_due,
                ]
            )
        return response

    if report_type == "payments":
        response = HttpResponse(content_type="text/csv")
        response["Content-Disposition"] = 'attachment; filename="winbird-payments-report.csv"'
        writer = csv.writer(response)
        writer.writerow(["Payment ID", "Booking ID", "Customer", "Amount", "Paid On", "Recorded By", "Notes"])
        for payment in Payment.objects.select_related("booking__customer", "recorded_by"):
            writer.writerow(
                [
                    payment.pk,
                    payment.booking.pk,
                    payment.booking.customer.name,
                    payment.amount,
                    payment.paid_on,
                    payment.recorded_by,
                    payment.notes,
                ]
            )
        return response

    raise Http404("Unknown report export.")


class NotificationsView(LoginRequiredMixin, TemplateView):
    template_name = "rentals/notifications.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        selected_kind = self.request.GET.get("kind", "all")
        selected_state = self.request.GET.get("state", "all")
        if selected_kind not in GENERAL_NOTIFICATION_KIND_LABELS:
            selected_kind = "all"

        notifications = filter_notifications(
            Notification.objects.select_related("booking"),
            scope="general",
            state=selected_state,
            kind=selected_kind,
        )
        grouped_notifications = group_notifications(notifications, GENERAL_NOTIFICATION_KIND_LABELS)

        context.update(
            {
                "notifications": notifications,
                "grouped_notifications": grouped_notifications,
                "selected_kind": selected_kind,
                "selected_state": selected_state,
                "notification_kind_labels": GENERAL_NOTIFICATION_KIND_LABELS,
            }
        )
        return context

    def post(self, request, *args, **kwargs):
        unread_notifications = filter_notifications(
            Notification.objects.select_related("booking"),
            scope="general",
            state="unread",
        )
        updated_count = Notification.objects.filter(pk__in=[note.pk for note in unread_notifications], is_read=False).update(
            is_read=True
        )
        if updated_count:
            messages.success(request, f"{updated_count} notification(s) marked as read.")
        else:
            messages.info(request, "There are no unread notifications right now.")
        return redirect("notifications")


class InventoryAlertsView(LoginRequiredMixin, TemplateView):
    template_name = "rentals/inventory_alerts.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        selected_state = self.request.GET.get("state", "all")
        inventory_alerts = filter_notifications(
            Notification.objects.select_related("booking"),
            scope="inventory",
            state=selected_state,
        )
        context.update(
            {
                "inventory_alerts": inventory_alerts,
                "selected_state": selected_state,
            }
        )
        return context

    def post(self, request, *args, **kwargs):
        unread_alerts = filter_notifications(
            Notification.objects.select_related("booking"),
            scope="inventory",
            state="unread",
        )
        updated_count = Notification.objects.filter(pk__in=[note.pk for note in unread_alerts], is_read=False).update(
            is_read=True
        )
        if updated_count:
            messages.success(request, f"{updated_count} inventory alert(s) marked as read.")
        else:
            messages.info(request, "There are no unread inventory alerts right now.")
        return redirect("inventory-alerts")


@login_required
def notification_open(request, pk):
    notification = get_object_or_404(Notification.objects.select_related("booking"), pk=pk)
    if not notification.is_read:
        notification.is_read = True
        notification.save(update_fields=["is_read"])

    if notification.booking_id:
        return redirect("booking-detail", pk=notification.booking_id)
    return notification_redirect(request, notification)


@login_required
@require_POST
def notification_action(request, pk, action):
    notification = get_object_or_404(Notification, pk=pk)

    if action == "read":
        if not notification.is_read:
            notification.is_read = True
            notification.save(update_fields=["is_read"])
            messages.success(request, "Notification marked as read.")
    elif action == "delete":
        notification.delete()
        messages.success(request, "Notification deleted.")
    else:
        raise Http404("Unknown notification action.")

    return notification_redirect(request, notification)


@login_required
@require_POST
def notification_bulk_action(request, action):
    scope = request.POST.get("scope", "general")
    if scope not in {"general", "inventory"}:
        scope = "general"

    if action == "delete-read":
        read_notifications = filter_notifications(
            Notification.objects.select_related("booking"),
            scope=scope,
            state="read",
        )
        deleted_count, _ = Notification.objects.filter(pk__in=[note.pk for note in read_notifications]).delete()
        if deleted_count:
            messages.success(request, f"Deleted {deleted_count} read notification(s).")
        else:
            messages.info(request, "There are no read notifications to delete.")
        return redirect("inventory-alerts" if scope == "inventory" else "notifications")

    raise Http404("Unknown notification bulk action.")


class StaffAccountUpdateView(LoginRequiredMixin, AdminRequiredMixin, View):
    template_name = "rentals/staff_account_form.html"

    def get_object(self, pk):
        return get_object_or_404(User, pk=pk, role=User.Role.STAFF)

    def get(self, request, pk):
        staff_user = self.get_object(pk)
        return render(
            request,
            self.template_name,
            {
                "form": StaffAccountUpdateForm(instance=staff_user),
                "staff_user": staff_user,
            },
        )

    def post(self, request, pk):
        staff_user = self.get_object(pk)
        form = StaffAccountUpdateForm(request.POST, instance=staff_user)
        if form.is_valid():
            form.save()
            messages.success(request, f"Updated staff account for {staff_user.username}.")
            return redirect("settings")

        return render(
            request,
            self.template_name,
            {
                "form": form,
                "staff_user": staff_user,
            },
        )


@login_required
@require_POST
def staff_account_action(request, pk, action):
    if not request.user.can_manage_catalog:
        raise PermissionDenied("Only admins can manage staff accounts.")

    staff_user = get_object_or_404(User, pk=pk, role=User.Role.STAFF)

    if action == "toggle-active":
        staff_user.is_active = not staff_user.is_active
        staff_user.save(update_fields=["is_active"])
        state_label = "activated" if staff_user.is_active else "deactivated"
        messages.success(request, f"{staff_user.username} has been {state_label}.")
    elif action == "reset-password":
        temporary_password = get_random_string(10)
        staff_user.set_password(temporary_password)
        staff_user.save(update_fields=["password"])
        messages.success(request, f"Temporary password for {staff_user.username}: {temporary_password}")
    else:
        raise Http404("Unknown staff account action.")

    return redirect("settings")


class SettingsView(LoginRequiredMixin, TemplateView):
    template_name = "rentals/settings.html"

    def build_context(self, staff_form=None):
        staff_users = User.objects.filter(role=User.Role.STAFF).order_by(
            "-is_booking_approver",
            "-is_active",
            "first_name",
            "last_name",
            "username",
        )
        return {
            "user_count": User.objects.count(),
            "category_count": Category.objects.count(),
            "staff_account_count": staff_users.count(),
            "booking_approver_count": staff_users.filter(is_booking_approver=True, is_active=True).count(),
            "admin_count": User.objects.filter(role=User.Role.ADMIN).count(),
            "staff_users": staff_users[:12],
            "staff_form": staff_form if self.request.user.can_manage_catalog else None,
        }

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(self.build_context(staff_form=StaffAccountForm()))
        return context

    def post(self, request, *args, **kwargs):
        if not request.user.can_manage_catalog:
            raise PermissionDenied("Only admins can create staff accounts.")

        staff_form = StaffAccountForm(request.POST)
        if staff_form.is_valid():
            staff_user = staff_form.save()
            messages.success(request, f"Staff account created for {staff_user.username}.")
            return redirect("settings")

        context = super().get_context_data(**kwargs)
        context.update(self.build_context(staff_form=staff_form))
        return self.render_to_response(context)
