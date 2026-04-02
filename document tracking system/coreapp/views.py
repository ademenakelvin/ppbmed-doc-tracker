import csv
from datetime import date, datetime, timedelta
from functools import wraps
from importlib import metadata
import logging
from pathlib import Path

from django.contrib import messages
from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.core.mail import send_mail
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db.models import Q, Count
from django.http import FileResponse, Http404, HttpResponse, JsonResponse
from django.urls import reverse
from django.shortcuts import render, redirect, get_object_or_404
from django.utils import timezone

from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

from .models import Staff, Document, DocumentRouting, StaffMessage, StaffMessageRecipient, Notification, SystemPreference, LoginHistory, AuditLog, RolePermission, ITMaintenanceLog
from .ocr_utils import extract_text_from_upload, build_document_autofill, build_preview
from .forms import (
    StaffForm,
    DocumentForm,
    DocumentRoutingForm,
    MessageComposeForm,
    MessageReplyForm,
    ProfileSettingsForm,
    PreferenceSettingsForm,
    PasswordChangeCustomForm,
    UPLOAD_ACCEPT_ATTR,
    validate_uploaded_file,
)


def get_logged_in_staff(request):
    if request.user.is_authenticated:
        return getattr(request.user, 'staff_profile', None)
    return None


logger = logging.getLogger(__name__)

MESSAGE_IMAGE_EXTENSIONS = {'.png', '.jpg', '.jpeg', '.gif', '.webp', '.bmp'}


PERMISSION_DEFINITIONS = [
    ("view_documents", "View Documents", "Open the main documents library."),
    ("add_document", "Add Documents", "Create new document records."),
    ("edit_document", "Edit Documents", "Update existing document details."),
    ("delete_document", "Delete Documents", "Remove document records."),
    ("route_document", "Route Documents", "Assign, forward, or complete documents."),
    ("view_messages", "View Messages", "Open messages sent inside the system."),
    ("manage_messages", "Send Messages", "Send internal messages to staff."),
    ("view_incoming", "View Incoming", "Open the incoming documents page."),
    ("view_outgoing", "View Outgoing", "Open the outgoing documents page."),
    ("view_tracking", "View Tracking", "Open the tracking history page."),
    ("view_reports", "View Reports", "Open the reports and analytics page."),
    ("view_access_history", "View Access History", "Open login and audit history."),
    ("view_staff_directory", "View Staff Directory", "Open the staff listing page."),
    ("manage_staff", "Manage Staff", "Add, edit, or delete staff members."),
    ("export_document_pdf", "Export Document PDF", "Export document history PDFs."),
    ("view_document_attachment", "View Attachments", "Open protected document or routing attachments."),
]

PERMISSION_META = {
    key: {"label": label, "description": description}
    for key, label, description in PERMISSION_DEFINITIONS
}

DEFAULT_ROLE_PERMISSIONS = {
    "Director": {
        "view_documents": True,
        "add_document": True,
        "edit_document": True,
        "delete_document": True,
        "route_document": True,
        "view_messages": True,
        "manage_messages": True,
        "view_incoming": True,
        "view_outgoing": True,
        "view_tracking": True,
        "view_reports": True,
        "view_access_history": False,
        "view_staff_directory": False,
        "manage_staff": False,
        "export_document_pdf": True,
        "view_document_attachment": True,
    },
    "Deputy Director": {
        "view_documents": True,
        "add_document": True,
        "edit_document": True,
        "delete_document": False,
        "route_document": True,
        "view_messages": True,
        "manage_messages": False,
        "view_incoming": True,
        "view_outgoing": True,
        "view_tracking": True,
        "view_reports": True,
        "view_access_history": False,
        "view_staff_directory": False,
        "manage_staff": False,
        "export_document_pdf": True,
        "view_document_attachment": True,
    },
    "Staff": {
        "view_documents": True,
        "add_document": True,
        "edit_document": True,
        "delete_document": False,
        "route_document": True,
        "view_messages": True,
        "manage_messages": False,
        "view_incoming": True,
        "view_outgoing": True,
        "view_tracking": True,
        "view_reports": False,
        "view_access_history": False,
        "view_staff_directory": False,
        "manage_staff": False,
        "export_document_pdf": True,
        "view_document_attachment": True,
    },
    "Registry": {
        "view_documents": True,
        "add_document": False,
        "edit_document": False,
        "delete_document": False,
        "route_document": False,
        "view_messages": True,
        "manage_messages": False,
        "view_incoming": False,
        "view_outgoing": False,
        "view_tracking": True,
        "view_reports": False,
        "view_access_history": False,
        "view_staff_directory": False,
        "manage_staff": False,
        "export_document_pdf": False,
        "view_document_attachment": True,
    },
    "Admin": {
        "view_documents": False,
        "add_document": False,
        "edit_document": False,
        "delete_document": False,
        "route_document": False,
        "view_messages": True,
        "manage_messages": False,
        "view_incoming": False,
        "view_outgoing": False,
        "view_tracking": False,
        "view_reports": False,
        "view_access_history": True,
        "view_staff_directory": True,
        "manage_staff": True,
        "export_document_pdf": False,
        "view_document_attachment": False,
    },
}


def get_staff_preferences(staff_user):
    if not staff_user:
        return None

    try:
        return staff_user.preferences
    except SystemPreference.DoesNotExist:
        return None


def get_role_permission_map(role):
    permission_map = DEFAULT_ROLE_PERMISSIONS.get(role, {}).copy()
    overrides = RolePermission.objects.filter(role=role)

    for item in overrides:
        permission_map[item.permission_key] = item.enabled

    return permission_map


def has_role_permission(staff_user, permission_key):
    if not staff_user or not staff_user.is_active:
        return False

    return get_role_permission_map(staff_user.role).get(permission_key, False)


def create_notification(recipient, message, notification_type='general', document=None, staff_message=None):
    if recipient and recipient.is_active:
        safe_message = (message or '')[:255]
        exists = Notification.objects.filter(
            recipient=recipient,
            document=document,
            staff_message=staff_message,
            message=safe_message,
            notification_type=notification_type,
            is_read=False
        ).exists()
        if not exists:
            Notification.objects.create(
                recipient=recipient,
                document=document,
                staff_message=staff_message,
                message=safe_message,
                notification_type=notification_type
            )


def get_messages_redirect(counterpart=None, compose=False):
    url = reverse('messages')
    query_parts = []

    if counterpart:
        query_parts.append(f"with={counterpart.pk}")

    if compose:
        query_parts.append("compose=1")

    if query_parts:
        return f"{url}?{'&'.join(query_parts)}"

    return url


def build_chat_subject(base_subject, counterpart):
    subject = (base_subject or '').strip()
    if not subject:
        return f"Chat with {counterpart.full_name}"
    if subject.lower().startswith('re:'):
        return subject
    return f"Re: {subject}"


def build_message_attachment_data(staff_message):
    if not staff_message.attachment:
        return None

    file_name = Path(staff_message.attachment.name).name
    extension = Path(file_name).suffix.lower()

    return {
        "name": file_name,
        "is_image": extension in MESSAGE_IMAGE_EXTENSIONS,
        "url": reverse('download_message_attachment', kwargs={'pk': staff_message.pk}),
    }


def build_message_preview(body, attachment_data):
    preview = (body or '').replace('\r', ' ').replace('\n', ' ').strip()
    if preview:
        if len(preview) > 88:
            preview = f"{preview[:88].rstrip()}..."
        return preview

    if attachment_data:
        label = "Photo" if attachment_data["is_image"] else "Attachment"
        return f"{label}: {attachment_data['name']}"

    return "New message"


def send_single_staff_message(sender, recipient, subject, body, *, attachment=None, actor_notice, audit_action):
    message_record = StaffMessage.objects.create(
        sender=sender,
        subject=subject,
        body=body,
        attachment=attachment,
    )
    StaffMessageRecipient.objects.create(
        staff_message=message_record,
        recipient=recipient,
    )

    log_audit_event(
        sender,
        audit_action,
        "Message",
        message_record.subject,
        actor_notice,
    )

    return message_record


def create_overdue_alerts():
    today = date.today()
    overdue_docs = Document.objects.select_related('assigned_to').filter(
        due_date__lt=today
    ).exclude(status="Completed")

    for doc in overdue_docs:
        if doc.status != "Overdue":
            doc.status = "Overdue"
            doc.save()

        if doc.assigned_to:
            create_notification(
                recipient=doc.assigned_to,
                message=f"Document {doc.reference_id} is overdue.",
                notification_type="overdue",
                document=doc
            )


def get_workflow_steps(document):
    routing_actions = list(document.routing_history.values_list('action', flat=True))

    return [
        {"name": "Received", "done": True, "active": document.status == "Pending" and not routing_actions},
        {"name": "Assigned", "done": "Assigned" in routing_actions or document.assigned_to is not None, "active": document.status == "Pending"},
        {"name": "In Progress", "done": document.status in ["In Progress", "Completed", "Overdue"], "active": document.status == "In Progress"},
        {"name": "Returned", "done": "Returned" in routing_actions, "active": "Returned" in routing_actions and document.status == "Pending"},
        {"name": "Completed", "done": document.status == "Completed", "active": document.status == "Completed"},
    ]


def can_access_document(staff_user, document):
    if not staff_user or not staff_user.is_active:
        return False

    if not has_role_permission(staff_user, "view_documents"):
        return False

    if staff_user.role == "Director":
        return True

    if staff_user.role == "Deputy Director":
        if staff_user.department and document.department == staff_user.department:
            return True
        if document.assigned_to and staff_user.department and document.assigned_to.department == staff_user.department:
            return True
        return document.assigned_to == staff_user

    return document.assigned_to == staff_user


def log_audit_event(actor, action, target_type, target_label, details=""):
    AuditLog.objects.create(
        actor=actor,
        action=action,
        target_type=target_type,
        target_label=target_label,
        details=details,
    )


def get_dependency_audit_notes():
    package_notes = [
        ("Django", "Core web framework. Keep this updated for security fixes and auth/session hardening."),
        ("reportlab", "Used for PDF exports. Keep aligned with your Python version and patch security updates."),
        ("pytesseract", "Used for OCR processing. Requires the native Tesseract binary to be secured and maintained."),
        ("Pillow", "Processes uploaded images. Keep updated because image libraries receive security fixes regularly."),
        ("redis", "Recommended for shared login throttling and distributed cache in production."),
    ]

    audit_rows = []
    for package_name, note in package_notes:
        try:
            installed_version = metadata.version(package_name)
            installed = True
        except metadata.PackageNotFoundError:
            installed_version = "Not installed"
            installed = False

        audit_rows.append({
            "name": package_name,
            "version": installed_version,
            "installed": installed,
            "note": note,
        })

    return audit_rows


def get_role_access_summary(role):
    permission_map = get_role_permission_map(role) if role else {}
    enabled_items = []

    if role == "Admin":
        return [
            "Control who can access what across the system.",
            "Manage staff accounts and staff records.",
            "Review login history, audit activity, and security events.",
            "Oversee backups, security checklist work, and IT maintenance records.",
        ]

    for permission_key, _, _ in PERMISSION_DEFINITIONS:
        if permission_map.get(permission_key):
            meta = PERMISSION_META[permission_key]
            enabled_items.append(f"{meta['label']}: {meta['description']}")

    if role == "Director":
        enabled_items.insert(0, "Full dashboard overview and full document access across the system.")

    return enabled_items


def get_control_governance_summary():
    return [
        {
            "title": "Director",
            "scope": "Application control",
            "detail": "Owns business-level decisions, reporting, and document oversight inside the application.",
            "badge": "App authority",
        },
        {
            "title": "Admin / IT Officer",
            "scope": "Access control and technical oversight",
            "detail": "Mainly controls permissions, staff accounts, audit and history review, backup oversight, security monitoring, and IT maintenance records.",
            "badge": "Technical authority",
        },
        {
            "title": "Deputy Director",
            "scope": "Operational workflow control",
            "detail": "Supervises day-to-day document work in the app, but should not normally control the server room or machine-level security unless separately authorized.",
            "badge": "Operations",
        },
        {
            "title": "Staff",
            "scope": "System use only",
            "detail": "Uses the application for assigned work and tracking, but should not have server-room access or technical backend control.",
            "badge": "User access",
        },
    ]


def get_base_context(request):
    create_overdue_alerts()

    staff_user = get_logged_in_staff(request)
    preferences = get_staff_preferences(staff_user)
    unread_notifications_count = 0
    unread_messages_count = 0
    latest_notifications = []

    if staff_user:
        unread_notifications_count = Notification.objects.filter(
            recipient=staff_user,
            is_read=False
        ).exclude(notification_type='message').count()
        unread_messages_count = StaffMessageRecipient.objects.filter(
            recipient=staff_user,
            is_read=False
        ).count()

        latest_notifications = Notification.objects.filter(
            recipient=staff_user
        ).exclude(notification_type='message').order_by('-created_at')[:5]

    permission_flags = get_role_permission_map(staff_user.role) if staff_user else {}

    return {
        "staff_user": staff_user,
        "role": staff_user.role if staff_user else None,
        "permission_flags": permission_flags,
        "preferences": preferences,
        "dark_mode_enabled": preferences.dark_mode if preferences else False,
        "unread_notifications_count": unread_notifications_count,
        "unread_messages_count": unread_messages_count,
        "latest_notifications": latest_notifications,
        "session_idle_timeout_minutes": max(getattr(settings, "SESSION_IDLE_TIMEOUT", 1800) // 60, 1),
    }


def role_required(*allowed_roles):
    def decorator(view_func):
        @wraps(view_func)
        @login_required
        def wrapper(request, *args, **kwargs):
            staff_user = get_logged_in_staff(request)

            if not staff_user or not staff_user.is_active:
                raise PermissionDenied("No active staff profile is linked to this account.")

            if allowed_roles and staff_user.role not in allowed_roles:
                raise PermissionDenied("You do not have permission to access this page.")

            return view_func(request, *args, **kwargs)
        return wrapper
    return decorator


def require_permission(staff_user, permission_key, message="You do not have permission to access this page."):
    if not has_role_permission(staff_user, permission_key):
        raise PermissionDenied(message)


def scoped_documents_queryset(staff_user, include_archived=False):
    documents_qs = Document.objects.select_related('assigned_to')

    if not include_archived:
        documents_qs = documents_qs.filter(is_archived=False)

    if staff_user.role == "Director":
        return documents_qs.order_by('-created_at')

    if staff_user.role == "Deputy Director":
        department_filters = Q(assigned_to=staff_user)
        if staff_user.department:
            department_filters |= Q(department=staff_user.department)
            department_filters |= Q(assigned_to__department=staff_user.department)
        return documents_qs.filter(department_filters).distinct().order_by('-created_at')

    return documents_qs.filter(assigned_to=staff_user).order_by('-created_at')


def apply_document_filters(documents_qs, request):
    search_query = request.GET.get('search', '').strip()
    status_filter = request.GET.get('status', '').strip()
    priority_filter = request.GET.get('priority', '').strip()
    department_filter = request.GET.get('department', '').strip()
    assigned_filter = request.GET.get('assigned_to', '').strip()
    date_from = request.GET.get('date_from', '').strip()
    date_to = request.GET.get('date_to', '').strip()
    archive_filter = request.GET.get('archive', 'active').strip() or 'active'

    if archive_filter == 'archived':
        documents_qs = documents_qs.filter(is_archived=True)
    elif archive_filter == 'all':
        pass
    else:
        documents_qs = documents_qs.filter(is_archived=False)

    if search_query:
        documents_qs = documents_qs.filter(
            Q(reference_id__icontains=search_query) |
            Q(subject__icontains=search_query) |
            Q(origin__icontains=search_query) |
            Q(destination__icontains=search_query) |
            Q(document_type__icontains=search_query) |
            Q(assigned_to__full_name__icontains=search_query) |
            Q(department__icontains=search_query)
        )

    if status_filter:
        documents_qs = documents_qs.filter(status=status_filter)

    if priority_filter:
        documents_qs = documents_qs.filter(priority=priority_filter)

    if department_filter:
        documents_qs = documents_qs.filter(department=department_filter)

    if assigned_filter:
        documents_qs = documents_qs.filter(assigned_to_id=assigned_filter)

    if date_from:
        documents_qs = documents_qs.filter(date_received__gte=date_from)

    if date_to:
        documents_qs = documents_qs.filter(date_received__lte=date_to)

    return documents_qs, {
        "search_query": search_query,
        "status_filter": status_filter,
        "priority_filter": priority_filter,
        "department_filter": department_filter,
        "assigned_filter": assigned_filter,
        "date_from": date_from,
        "date_to": date_to,
        "archive_filter": archive_filter,
    }


def document_filter_options(documents_qs):
    return {
        "department_options": list(
            documents_qs.exclude(department__isnull=True).exclude(department__exact='').values_list('department', flat=True).distinct().order_by('department')
        ),
        "assigned_options": Staff.objects.filter(is_active=True, is_archived=False).order_by('full_name'),
    }


def serialize_document_row(document):
    return [
        document.reference_id,
        document.subject,
        document.direction,
        document.document_type or '',
        document.department or '',
        document.origin,
        document.destination,
        document.assigned_to.full_name if document.assigned_to else '',
        document.priority,
        document.status,
        document.date_received.isoformat() if document.date_received else '',
        document.due_date.isoformat() if document.due_date else '',
        'Archived' if document.is_archived else 'Active',
    ]


@login_required
def dashboard(request):
    today = date.today()
    staff_user = get_logged_in_staff(request)

    if not staff_user or not staff_user.is_active:
        raise PermissionDenied("No active staff profile is linked to this account.")

    visible_docs = scoped_documents_queryset(staff_user)

    context = {
        **get_base_context(request),
        "recent_documents": [],
    }

    role = staff_user.role

    if role == "Director":
        recent_documents = visible_docs[:5]
        director_reports_count = visible_docs.values('department').distinct().count()
        context.update({
            "dashboard_type": "director",
            "page_subtitle": "Full directorate overview and control.",
            "card_1_title": "Total Documents",
            "card_1_value": visible_docs.count(),
            "card_2_title": "Pending Approvals",
            "card_2_value": visible_docs.filter(status="Pending").count(),
            "card_3_title": "Completed",
            "card_3_value": visible_docs.filter(status="Completed").count(),
            "card_4_title": "Overdue",
            "card_4_value": visible_docs.filter(due_date__lt=today).exclude(status="Completed").count(),
            "recent_documents": recent_documents,
            "director_stat_links": {
                "card_1": reverse("documents"),
                "card_2": reverse("documents") + "?status=Pending",
                "card_3": reverse("documents") + "?status=Completed",
                "card_4": reverse("documents") + "?status=Overdue",
                "queue": reverse("tracking"),
                "notices": reverse("notifications"),
                "gaps": reverse("documents") + "?search=&archive=active",
            },
            "director_overview_items": [
                {
                    "title": "Operational scope",
                    "detail": "Lead directorate-wide document oversight, review trends, and unblock major workflow issues.",
                    "icon": "fas fa-building-shield",
                    "url": reverse("reports"),
                },
                {
                    "title": "Reporting coverage",
                    "detail": f"{director_reports_count} department view(s) available in reports and summaries.",
                    "icon": "fas fa-chart-column",
                    "url": reverse("reports"),
                },
                {
                    "title": "Unread notices",
                    "detail": f"{Notification.objects.filter(recipient=staff_user, is_read=False).exclude(notification_type='message').count()} notice(s) waiting for review.",
                    "icon": "fas fa-bell",
                    "url": reverse("notifications"),
                },
            ],
        })

    elif role == "Admin":
        backup_root = Path(settings.BASE_DIR) / "backups"
        backup_folders = []
        if backup_root.exists():
            backup_folders = sorted([item for item in backup_root.iterdir() if item.is_dir()], reverse=True)

        recent_security_events = AuditLog.objects.filter(
            Q(target_type="Authentication") |
            Q(target_type="Security")
        ).select_related('actor')[:6]
        recent_permission_updates = AuditLog.objects.filter(
            action__icontains="Permission"
        ).select_related('actor')[:5]
        recent_staff_activity = AuditLog.objects.filter(
            Q(target_type="Staff") | Q(action__icontains="Staff")
        ).select_related('actor')[:5]
        recent_maintenance_logs = ITMaintenanceLog.objects.select_related('logged_by')[:5]
        failed_login_count = AuditLog.objects.filter(
            action="Login Failed",
            created_at__date=today
        ).count()
        blocked_login_count = AuditLog.objects.filter(
            action="Login Blocked",
            created_at__date=today
        ).count()
        login_events_today = LoginHistory.objects.filter(
            event_type="login",
            logged_in_at__date=today
        ).count()

        context.update({
            "dashboard_type": "admin",
            "page_subtitle": "Control access, staff accounts, security checks, and technical oversight.",
            "card_1_title": "Permission Overrides",
            "card_1_value": RolePermission.objects.count(),
            "card_2_title": "Staff Accounts",
            "card_2_value": Staff.objects.filter(is_active=True, is_archived=False).count(),
            "card_3_title": "Audit Events Today",
            "card_3_value": AuditLog.objects.filter(created_at__date=today).count(),
            "card_4_title": "Security Alerts",
            "card_4_value": recent_security_events.count(),
            "dashboard_pending_actions_count": recent_security_events.count(),
            "dashboard_unassigned_count": backup_folders and 0 or 1,
            "admin_stat_links": {
                "card_1": reverse("role_permissions"),
                "card_2": reverse("staff"),
                "card_3": reverse("login_history"),
                "card_4": reverse("security_checklist"),
                "queue": reverse("login_history"),
                "notices": reverse("notifications"),
                "gaps": reverse("backup_restore_center"),
            },
            "recent_security_events": recent_security_events,
            "recent_permission_updates": recent_permission_updates,
            "recent_staff_activity": recent_staff_activity,
            "recent_maintenance_logs": recent_maintenance_logs,
            "admin_latest_backup": backup_folders[0].name if backup_folders else "No backup found",
            "admin_backup_status": "Available" if backup_folders else "Needs attention",
            "admin_security_breakdown": [
                {
                    "title": "Failed logins",
                    "value": failed_login_count,
                    "detail": "invalid sign-in attempts recorded today",
                    "icon": "fas fa-user-lock",
                    "url": reverse("login_history"),
                },
                {
                    "title": "Blocked attempts",
                    "value": blocked_login_count,
                    "detail": "rate-limited sign-in attempts today",
                    "icon": "fas fa-ban",
                    "url": reverse("login_history"),
                },
                {
                    "title": "Successful logins",
                    "value": login_events_today,
                    "detail": "login events successfully recorded today",
                    "icon": "fas fa-right-to-bracket",
                    "url": reverse("login_history"),
                },
            ],
            "admin_health_checks": [
                {
                    "title": "Backups",
                    "status": "Healthy" if backup_folders else "Attention",
                    "detail": "Recent backup folder detected." if backup_folders else "No backup folder detected yet.",
                    "url": reverse("backup_restore_center"),
                },
                {
                    "title": "Security logging",
                    "status": "Healthy" if recent_security_events.exists() else "Review",
                    "detail": "Security and authentication events are being captured." if recent_security_events.exists() else "No recent security events found to review today.",
                    "url": reverse("security_checklist"),
                },
                {
                    "title": "Maintenance records",
                    "status": "Healthy" if recent_maintenance_logs else "Review",
                    "detail": "Recent IT maintenance notes are available." if recent_maintenance_logs else "No maintenance log has been entered yet.",
                    "url": reverse("it_admin_center"),
                },
            ],
            "admin_quick_metrics": [
                {
                    "title": "Access Control",
                    "value": RolePermission.objects.values("role").distinct().count(),
                    "detail": "roles with centralized permission settings",
                    "icon": "fas fa-shield-halved",
                    "url": reverse("role_permissions"),
                },
                {
                    "title": "Auth Events",
                    "value": LoginHistory.objects.filter(logged_in_at__date=today).count(),
                    "detail": "login or logout records captured today",
                    "icon": "fas fa-clock-rotate-left",
                    "url": reverse("login_history"),
                },
                {
                    "title": "Unread Notices",
                    "value": Notification.objects.filter(recipient=staff_user, is_read=False).count(),
                    "detail": "admin notices still waiting for review",
                    "icon": "fas fa-bell",
                    "url": reverse("notifications"),
                },
            ],
        })

    elif role == "Deputy Director":
        deputy_docs = visible_docs

        context.update({
            "dashboard_type": "deputy",
            "page_subtitle": "Supervise, review, and forward documents.",
            "card_1_title": "Assigned To Me",
            "card_1_value": deputy_docs.filter(assigned_to=staff_user).count(),
            "card_2_title": "Pending Reviews",
            "card_2_value": deputy_docs.filter(status="Pending").count(),
            "card_3_title": "Completed",
            "card_3_value": deputy_docs.filter(status="Completed").count(),
            "card_4_title": "Overdue",
            "card_4_value": deputy_docs.filter(due_date__lt=today).exclude(status="Completed").count(),
            "recent_documents": deputy_docs[:5],
            "deputy_stat_links": {
                "card_1": reverse("documents"),
                "card_2": reverse("documents") + "?status=Pending",
                "card_3": reverse("documents") + "?status=Completed",
                "card_4": reverse("documents") + "?status=Overdue",
                "queue": reverse("tracking"),
                "notices": reverse("notifications"),
                "gaps": reverse("documents"),
            },
            "deputy_overview_items": [
                {
                    "title": "Supervision scope",
                    "detail": "Review assigned work, clear pending reviews, and keep department documents moving.",
                    "icon": "fas fa-users-gear",
                    "url": reverse("tracking"),
                },
                {
                    "title": "Department reports",
                    "detail": "Open read-only reports and staff visibility for operational follow-up.",
                    "icon": "fas fa-chart-line",
                    "url": reverse("reports"),
                },
                {
                    "title": "Unread notices",
                    "detail": f"{Notification.objects.filter(recipient=staff_user, is_read=False).count()} notice(s) waiting for review.",
                    "icon": "fas fa-bell",
                    "url": reverse("notifications"),
                },
            ],
        })

    else:
        my_docs = visible_docs

        context.update({
            "dashboard_type": "staff",
            "page_subtitle": "Track your assigned work and deadlines.",
            "card_1_title": "My Documents",
            "card_1_value": my_docs.count(),
            "card_2_title": "Pending",
            "card_2_value": my_docs.filter(status="Pending").count(),
            "card_3_title": "Completed",
            "card_3_value": my_docs.filter(status="Completed").count(),
            "card_4_title": "Overdue",
            "card_4_value": my_docs.filter(due_date__lt=today).exclude(status="Completed").count(),
            "recent_documents": my_docs[:5],
        })

    if role != "Admin":
        alert_documents = visible_docs.exclude(status="Completed")
        context.update({
            "dashboard_unassigned_count": visible_docs.filter(assigned_to__isnull=True).count(),
            "dashboard_pending_actions_count": alert_documents.filter(status__in=["Pending", "In Progress"]).count(),
            "dashboard_unread_notifications_count": Notification.objects.filter(recipient=staff_user, is_read=False).exclude(notification_type='message').count(),
            "recent_document_activity": AuditLog.objects.filter(target_type="Document").select_related('actor')[:5],
        })
    else:
        context["dashboard_unread_notifications_count"] = Notification.objects.filter(recipient=staff_user, is_read=False).exclude(notification_type='message').count()

    if role in {"Director", "Deputy Director"}:
        context["overdue_by_department"] = list(
            visible_docs.filter(due_date__lt=today).exclude(status="Completed")
            .values('department').annotate(total=Count('id')).order_by('-total', 'department')[:5]
        )
        context["pending_by_officer"] = list(
            visible_docs.filter(status__in=["Pending", "In Progress"], assigned_to__isnull=False)
            .values('assigned_to__full_name').annotate(total=Count('id')).order_by('-total', 'assigned_to__full_name')[:5]
        )
        context["recent_staff_activity"] = AuditLog.objects.filter(actor__isnull=False).select_related('actor')[:5]

    if staff_user:
        access_events = [
            {
                "title": item.get_event_type_display(),
                "detail": f"Account {item.get_event_type_display().lower()} recorded.",
                "created_at": item.logged_in_at,
            }
            for item in LoginHistory.objects.filter(staff=staff_user)[:3]
        ]
        audit_events = [
            {
                "title": item.action,
                "detail": item.target_label,
                "created_at": item.created_at,
            }
            for item in AuditLog.objects.filter(actor=staff_user)[:4]
        ]
        personal_activity = sorted(
            access_events + audit_events,
            key=lambda item: item["created_at"],
            reverse=True,
        )[:5]
        context["recent_personal_activity"] = personal_activity

    return render(request, "coreapp/dashboard.html", context)


@role_required("Director", "Deputy Director", "Staff", "Registry", "Admin")
def documents(request):
    today = date.today()
    staff_user = get_logged_in_staff(request)
    require_permission(staff_user, "view_documents")

    base_qs = scoped_documents_queryset(staff_user, include_archived=True)
    documents_qs, filters = apply_document_filters(base_qs, request)
    active_documents_qs = base_qs.filter(is_archived=False)

    paginator = Paginator(documents_qs, 10)
    page_number = request.GET.get('page')
    documents = paginator.get_page(page_number)

    all_count = active_documents_qs.count()
    pending_count = active_documents_qs.filter(status="Pending").count()
    completed_count = active_documents_qs.filter(status="Completed").count()
    overdue_count = active_documents_qs.filter(due_date__lt=today).exclude(status="Completed").count()

    return render(request, "coreapp/documents.html", {
        **get_base_context(request),
        "documents": documents,
        **filters,
        "all_documents_count": all_count,
        "pending_documents_count": pending_count,
        "completed_documents_count": completed_count,
        "overdue_documents_count": overdue_count,
        "archived_documents_count": base_qs.filter(is_archived=True).count(),
        **document_filter_options(base_qs),
    })


@role_required("Director", "Deputy Director", "Staff", "Registry", "Admin")
def add_document(request):
    staff_user = get_logged_in_staff(request)
    require_permission(staff_user, "add_document", "You do not have permission to add documents.")

    if request.method == 'POST':
        form = DocumentForm(request.POST, request.FILES)
        if form.is_valid():
            document = form.save(commit=False)

            if staff_user.role == "Staff":
                document.assigned_to = staff_user
                document.department = staff_user.department

            if not document.assigned_to:
                document.assigned_to = staff_user

            if not document.department:
                document.department = (
                    document.assigned_to.department if document.assigned_to and document.assigned_to.department
                    else staff_user.department
                )

            document.save()
            log_audit_event(
                staff_user,
                "Document Added",
                "Document",
                document.reference_id,
                f"Created document {document.reference_id} - {document.subject}.",
            )

            if document.assigned_to == staff_user:
                create_notification(
                    recipient=staff_user,
                    message=f"Document {document.reference_id} was saved successfully.",
                    notification_type='general',
                    document=document
                )
            else:
                create_notification(
                    recipient=document.assigned_to,
                    message=f"New document {document.reference_id} has been assigned to you.",
                    notification_type='assignment',
                    document=document
                )

            messages.success(request, f"Document {document.reference_id} saved successfully.")
            return redirect('documents')
    else:
        form = DocumentForm()
        if staff_user.role == "Staff":
            form.fields['assigned_to'].initial = staff_user
            form.fields['department'].initial = staff_user.department

    return render(request, "coreapp/add_document.html", {
        **get_base_context(request),
        "form": form,
    })


@role_required("Director", "Deputy Director", "Staff", "Registry", "Admin")
def extract_document_scan(request):
    staff_user = get_logged_in_staff(request)
    require_permission(staff_user, "add_document", "You do not have permission to scan and prefill documents.")

    if request.method != "POST":
        return JsonResponse({"success": False, "error": "Only POST requests are allowed."}, status=405)

    uploaded_file = request.FILES.get("attachment")
    if not uploaded_file:
        return JsonResponse({"success": False, "error": "Choose a scanned file first."}, status=400)

    try:
        validate_uploaded_file(uploaded_file)
        extracted_text = extract_text_from_upload(uploaded_file)
        if not extracted_text.strip():
            return JsonResponse(
                {
                    "success": False,
                    "error": "No readable text was found in the uploaded file.",
                },
                status=422,
            )

        autofill_data = build_document_autofill(extracted_text)
        if not autofill_data:
            return JsonResponse(
                {
                    "success": False,
                    "error": "Text was found, but no form fields could be confidently suggested.",
                    "preview": build_preview(extracted_text),
                },
                status=422,
            )

        return JsonResponse(
            {
                "success": True,
                "data": autofill_data,
                "preview": build_preview(extracted_text),
                "message": "Scan complete. Suggested values were added to the empty fields.",
            }
        )
    except ValueError as exc:
        return JsonResponse({"success": False, "error": str(exc)}, status=400)
    except RuntimeError as exc:
        return JsonResponse({"success": False, "error": str(exc)}, status=503)
    except Exception:
        return JsonResponse(
            {
                "success": False,
                "error": "The scan could not be processed right now. Please try another file or save manually.",
            },
            status=500,
        )


@role_required("Director", "Deputy Director", "Staff", "Registry", "Admin")
def document_detail(request, pk):
    staff_user = get_logged_in_staff(request)
    require_permission(staff_user, "view_documents", "You do not have permission to view documents.")

    document = get_object_or_404(
        Document.objects.select_related('assigned_to'),
        pk=pk
    )

    if not can_access_document(staff_user, document):
        raise PermissionDenied("You do not have permission to view this document.")

    routing_history = document.routing_history.select_related('from_officer', 'to_officer').all()
    workflow_steps = get_workflow_steps(document)

    return render(request, "coreapp/document_detail.html", {
        **get_base_context(request),
        "document": document,
        "routing_history": routing_history,
        "workflow_steps": workflow_steps,
    })


@role_required("Director", "Deputy Director", "Staff", "Registry", "Admin")
def edit_document(request, pk):
    staff_user = get_logged_in_staff(request)
    document = get_object_or_404(Document, pk=pk)

    require_permission(staff_user, "edit_document", "You do not have permission to edit documents.")

    if not can_access_document(staff_user, document):
        raise PermissionDenied("You do not have permission to edit this document.")

    if document.is_archived:
        raise PermissionDenied("Restore this document before editing it.")

    if request.method == 'POST':
        form = DocumentForm(request.POST, request.FILES, instance=document)
        if form.is_valid():
            updated_document = form.save(commit=False)

            if staff_user.role == "Staff":
                updated_document.assigned_to = staff_user
                updated_document.department = staff_user.department

            if not updated_document.department and updated_document.assigned_to:
                updated_document.department = updated_document.assigned_to.department

            updated_document.save()
            log_audit_event(
                staff_user,
                "Document Updated",
                "Document",
                updated_document.reference_id,
                f"Updated document details for {updated_document.subject}.",
            )
            messages.success(request, f"Document {updated_document.reference_id} updated successfully.")
            return redirect('document_detail', pk=document.pk)
    else:
        form = DocumentForm(instance=document)

    return render(request, "coreapp/edit_document.html", {
        **get_base_context(request),
        "form": form,
        "document": document,
    })


@role_required("Director", "Deputy Director", "Staff", "Registry", "Admin")
def delete_document(request, pk):
    staff_user = get_logged_in_staff(request)
    document = get_object_or_404(Document, pk=pk)

    require_permission(staff_user, "delete_document", "You do not have permission to delete documents.")

    if not can_access_document(staff_user, document):
        raise PermissionDenied("You do not have permission to delete this document.")

    if request.method == "POST":
        confirmation = request.POST.get("confirm_reference", "").strip()
        if confirmation != document.reference_id:
            return render(request, "coreapp/delete_document.html", {
                **get_base_context(request),
                "document": document,
                "confirmation_error": "Type the exact document reference ID to confirm archiving.",
            })

        reference_id = document.reference_id
        subject = document.subject
        document.archive()
        log_audit_event(
            staff_user,
            "Document Archived",
            "Document",
            reference_id,
            f"Archived document {reference_id} - {subject}.",
        )
        messages.success(request, f"Document {reference_id} archived successfully.")
        return redirect("documents")

    return render(request, "coreapp/delete_document.html", {
        **get_base_context(request),
        "document": document,
    })


@role_required("Director", "Deputy Director", "Staff", "Registry", "Admin")
def restore_document(request, pk):
    staff_user = get_logged_in_staff(request)
    document = get_object_or_404(Document, pk=pk)

    require_permission(staff_user, "delete_document", "You do not have permission to restore documents.")

    if not can_access_document(staff_user, document):
        raise PermissionDenied("You do not have permission to restore this document.")

    document.restore()
    log_audit_event(
        staff_user,
        "Document Restored",
        "Document",
        document.reference_id,
        f"Restored archived document {document.reference_id}.",
    )
    messages.success(request, f"Document {document.reference_id} restored successfully.")
    return redirect("documents")


@role_required("Director", "Deputy Director", "Staff", "Registry", "Admin")
def route_document(request, pk):
    staff_user = get_logged_in_staff(request)
    document = get_object_or_404(Document, pk=pk)

    require_permission(staff_user, "route_document", "You do not have permission to route documents.")

    if not can_access_document(staff_user, document):
        raise PermissionDenied("You do not have permission to route this document.")

    if document.is_archived:
        raise PermissionDenied("Restore this document before routing it.")

    if request.method == 'POST':
        form = DocumentRoutingForm(request.POST, request.FILES)
        if form.is_valid():
            previous_assignee = document.assigned_to

            routing = form.save(commit=False)
            routing.document = document
            routing.save()

            document.assigned_to = routing.to_officer
            if routing.to_officer and routing.to_officer.department:
                document.department = routing.to_officer.department

            if routing.action == "Returned":
                document.status = "Pending"
            elif routing.action == "Forwarded":
                document.status = "In Progress"
            elif routing.action == "Completed":
                document.status = "Completed"
            elif routing.action == "Assigned":
                document.status = "Pending"

            document.save()
            log_audit_event(
                staff_user,
                "Document Routed",
                "Document",
                document.reference_id,
                f"Action: {routing.action}. To: {routing.to_officer.full_name if routing.to_officer else '-'}",
            )

            if routing.to_officer:
                notification_type = 'general'
                if routing.action == "Assigned":
                    notification_type = 'assignment'
                elif routing.action == "Forwarded":
                    notification_type = 'forwarded'
                elif routing.action == "Returned":
                    notification_type = 'returned'
                elif routing.action == "Completed":
                    notification_type = 'completed'

                create_notification(
                    recipient=routing.to_officer,
                    message=f"Document {document.reference_id} was {routing.action.lower()} to you.",
                    notification_type=notification_type,
                    document=document
                )

            if routing.action == "Completed" and previous_assignee and previous_assignee != routing.to_officer:
                create_notification(
                    recipient=previous_assignee,
                    message=f"Document {document.reference_id} has been marked completed.",
                    notification_type='completed',
                    document=document
                )

            messages.success(request, f"Document {document.reference_id} routed successfully.")
            return redirect('document_detail', pk=document.pk)
    else:
        form = DocumentRoutingForm(initial={'from_officer': document.assigned_to})

    return render(request, 'coreapp/route_document.html', {
        **get_base_context(request),
        'form': form,
        'document': document,
    })


@role_required("Director", "Deputy Director", "Staff", "Registry", "Admin")
def incoming(request):
    staff_user = get_logged_in_staff(request)
    require_permission(staff_user, "view_incoming", "You do not have permission to view incoming documents.")

    documents_qs, filters = apply_document_filters(
        scoped_documents_queryset(staff_user).filter(direction="Incoming"),
        request,
    )

    paginator = Paginator(documents_qs, 10)
    page_number = request.GET.get('page')
    documents = paginator.get_page(page_number)

    incoming_base = scoped_documents_queryset(staff_user).filter(direction="Incoming")

    return render(request, "coreapp/incoming.html", {
        **get_base_context(request),
        "documents": documents,
        **filters,
        "incoming_total_count": incoming_base.count(),
        "incoming_pending_count": incoming_base.filter(status="Pending").count(),
        "incoming_completed_count": incoming_base.filter(status="Completed").count(),
        "incoming_overdue_count": incoming_base.filter(due_date__lt=date.today()).exclude(status="Completed").count(),
    })


@role_required("Director", "Deputy Director", "Staff", "Registry", "Admin")
def outgoing(request):
    staff_user = get_logged_in_staff(request)
    require_permission(staff_user, "view_outgoing", "You do not have permission to view outgoing documents.")

    documents_qs, filters = apply_document_filters(
        scoped_documents_queryset(staff_user).filter(direction="Outgoing"),
        request,
    )

    paginator = Paginator(documents_qs, 10)
    page_number = request.GET.get('page')
    documents = paginator.get_page(page_number)

    outgoing_base = scoped_documents_queryset(staff_user).filter(direction="Outgoing")

    return render(request, "coreapp/outgoing.html", {
        **get_base_context(request),
        "documents": documents,
        **filters,
        "outgoing_total_count": outgoing_base.count(),
        "outgoing_pending_count": outgoing_base.filter(status="Pending").count(),
        "outgoing_completed_count": outgoing_base.filter(status="Completed").count(),
        "outgoing_overdue_count": outgoing_base.filter(due_date__lt=date.today()).exclude(status="Completed").count(),
    })


@role_required("Director", "Deputy Director", "Staff", "Registry", "Admin")
def tracking(request):
    staff_user = get_logged_in_staff(request)
    require_permission(staff_user, "view_tracking", "You do not have permission to view tracking history.")

    tracking_qs = DocumentRouting.objects.select_related(
        'document',
        'from_officer',
        'to_officer'
    ).all().order_by('-action_date')

    tracking_qs = tracking_qs.filter(document__is_archived=False)

    if staff_user.role not in ["Director", "Deputy Director"]:
        tracking_qs = tracking_qs.filter(document__assigned_to=staff_user)
    elif staff_user.role == "Deputy Director" and staff_user.department:
        tracking_qs = tracking_qs.filter(
            Q(document__department=staff_user.department) |
            Q(document__assigned_to=staff_user)
        ).distinct()

    search_query = request.GET.get('search', '')
    action_filter = request.GET.get('action', '')

    if search_query:
        tracking_qs = tracking_qs.filter(
            Q(document__reference_id__icontains=search_query) |
            Q(document__subject__icontains=search_query) |
            Q(from_officer__full_name__icontains=search_query) |
            Q(to_officer__full_name__icontains=search_query) |
            Q(note__icontains=search_query)
        )

    if action_filter:
        tracking_qs = tracking_qs.filter(action=action_filter)

    paginator = Paginator(tracking_qs, 10)
    page_number = request.GET.get('page')
    tracking_history = paginator.get_page(page_number)

    return render(request, "coreapp/tracking.html", {
        **get_base_context(request),
        "tracking_history": tracking_history,
        "search_query": search_query,
        "action_filter": action_filter,
        "tracking_total_count": tracking_qs.count(),
        "tracking_assigned_count": tracking_qs.filter(action="Assigned").count(),
        "tracking_forwarded_count": tracking_qs.filter(action="Forwarded").count(),
        "tracking_completed_count": tracking_qs.filter(action="Completed").count(),
    })


@role_required("Director", "Deputy Director", "Staff", "Registry", "Admin")
def reports_analytics(request):
    staff_user = get_logged_in_staff(request)
    require_permission(staff_user, "view_reports", "You do not have permission to view reports.")

    documents_qs, filters = apply_document_filters(scoped_documents_queryset(staff_user, include_archived=True), request)
    if filters["archive_filter"] == "all":
        report_base = documents_qs
    else:
        report_base = documents_qs

    status_data = list(
        report_base.values('status').annotate(total=Count('id')).order_by('status')
    )

    priority_data = list(
        report_base.values('priority').annotate(total=Count('id')).order_by('priority')
    )

    staff_data = list(
        Staff.objects.filter(is_archived=False).annotate(
            total_docs=Count('assigned_documents', filter=Q(assigned_documents__in=report_base))
        )
        .values('full_name', 'role', 'total_docs')
        .order_by('-total_docs')
    )

    department_data = list(
        report_base.exclude(department__isnull=True).exclude(department__exact='')
        .values('department').annotate(total=Count('id')).order_by('-total', 'department')
    )

    return render(request, "coreapp/reports.html", {
        **get_base_context(request),
        **filters,
        "department_options": document_filter_options(scoped_documents_queryset(staff_user, include_archived=True))["department_options"],
        "total_documents": report_base.count(),
        "pending_documents": report_base.filter(status="Pending").count(),
        "completed_documents": report_base.filter(status="Completed").count(),
        "overdue_documents": report_base.filter(status="Overdue").count(),
        "incoming_documents": report_base.filter(direction="Incoming").count(),
        "outgoing_documents": report_base.filter(direction="Outgoing").count(),
        "status_data": status_data,
        "priority_data": priority_data,
        "staff_data": staff_data,
        "department_data": department_data,
    })


@role_required("Director", "Deputy Director", "Staff", "Registry", "Admin")
def login_history(request):
    staff_user = get_logged_in_staff(request)
    require_permission(staff_user, "view_access_history", "You do not have permission to view access history.")

    search_query = request.GET.get('search', '').strip()
    event_filter = request.GET.get('event', '').strip()
    date_from = request.GET.get('date_from', '').strip()
    date_to = request.GET.get('date_to', '').strip()
    login_history_qs = LoginHistory.objects.select_related('staff').all()
    audit_logs_qs = AuditLog.objects.select_related('actor').all()
    suspicious_actions = ['Login Failed', 'Login Blocked', 'Two-Factor Failed', 'Two-Factor Blocked']

    if staff_user.role == "Deputy Director":
        if staff_user.department:
            department_filter = Q(staff__department=staff_user.department) | Q(staff=staff_user)
            actor_filter = Q(actor__department=staff_user.department) | Q(actor=staff_user)
        else:
            department_filter = Q(staff=staff_user)
            actor_filter = Q(actor=staff_user)
        login_history_qs = login_history_qs.filter(department_filter)
        audit_logs_qs = audit_logs_qs.filter(actor_filter)

    if search_query:
        login_history_qs = login_history_qs.filter(
            Q(username__icontains=search_query) |
            Q(role__icontains=search_query) |
            Q(ip_address__icontains=search_query) |
            Q(staff__full_name__icontains=search_query)
        )
        audit_logs_qs = audit_logs_qs.filter(
            Q(actor__full_name__icontains=search_query) |
            Q(action__icontains=search_query) |
            Q(target_type__icontains=search_query) |
            Q(target_label__icontains=search_query) |
            Q(details__icontains=search_query)
        )

    if event_filter:
        login_history_qs = login_history_qs.filter(event_type=event_filter)

    if date_from:
        login_history_qs = login_history_qs.filter(logged_in_at__date__gte=date_from)
        audit_logs_qs = audit_logs_qs.filter(created_at__date__gte=date_from)

    if date_to:
        login_history_qs = login_history_qs.filter(logged_in_at__date__lte=date_to)
        audit_logs_qs = audit_logs_qs.filter(created_at__date__lte=date_to)

    paginator = Paginator(login_history_qs, 12)
    page_number = request.GET.get('page')
    login_entries = paginator.get_page(page_number)

    today = date.today()
    seven_days_ago = today - timedelta(days=6)
    all_history = login_history_qs
    recent_audit_logs = audit_logs_qs[:12]
    suspicious_qs = audit_logs_qs.filter(action__in=suspicious_actions)
    recent_suspicious_logs = suspicious_qs[:8]

    return render(request, "coreapp/login_history.html", {
        **get_base_context(request),
        "search_query": search_query,
        "event_filter": event_filter,
        "date_from": date_from,
        "date_to": date_to,
        "login_entries": login_entries,
        "login_total_count": all_history.count(),
        "login_today_count": all_history.filter(logged_in_at__date=today, event_type='login').count(),
        "logout_today_count": all_history.filter(logged_in_at__date=today, event_type='logout').count(),
        "activity_week_count": all_history.filter(logged_in_at__date__gte=seven_days_ago).count(),
        "login_unique_users_count": all_history.values('username').distinct().count(),
        "failed_login_count": suspicious_qs.filter(action='Login Failed').count(),
        "blocked_login_count": suspicious_qs.filter(action='Login Blocked').count(),
        "two_factor_failed_count": suspicious_qs.filter(action='Two-Factor Failed').count(),
        "two_factor_blocked_count": suspicious_qs.filter(action='Two-Factor Blocked').count(),
        "recent_suspicious_logs": recent_suspicious_logs,
        "recent_audit_logs": recent_audit_logs,
        "audit_total_count": audit_logs_qs.count(),
    })


@role_required("Director", "Deputy Director", "Staff", "Registry", "Admin")
def export_documents_csv(request):
    staff_user = get_logged_in_staff(request)
    require_permission(staff_user, "view_documents", "You do not have permission to export document data.")

    documents_qs, _ = apply_document_filters(scoped_documents_queryset(staff_user, include_archived=True), request)

    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = 'attachment; filename="documents_export.csv"'

    writer = csv.writer(response)
    writer.writerow([
        'Reference ID', 'Subject', 'Direction', 'Document Type', 'Department', 'Origin',
        'Destination', 'Assigned To', 'Priority', 'Status', 'Date Received', 'Due Date', 'Lifecycle'
    ])
    for document in documents_qs:
        writer.writerow(serialize_document_row(document))

    return response


@role_required("Director", "Deputy Director", "Staff", "Registry", "Admin")
def export_reports_csv(request):
    staff_user = get_logged_in_staff(request)
    require_permission(staff_user, "view_reports", "You do not have permission to export reports.")

    report_base, _ = apply_document_filters(scoped_documents_queryset(staff_user, include_archived=True), request)
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = 'attachment; filename="reports_export.csv"'
    writer = csv.writer(response)
    writer.writerow(['Metric', 'Value'])
    writer.writerow(['Total Documents', report_base.count()])
    writer.writerow(['Pending', report_base.filter(status='Pending').count()])
    writer.writerow(['Completed', report_base.filter(status='Completed').count()])
    writer.writerow(['Overdue', report_base.filter(status='Overdue').count()])
    writer.writerow(['Incoming', report_base.filter(direction='Incoming').count()])
    writer.writerow(['Outgoing', report_base.filter(direction='Outgoing').count()])
    writer.writerow([])
    writer.writerow(['Department', 'Total'])
    for item in report_base.exclude(department__isnull=True).exclude(department__exact='').values('department').annotate(total=Count('id')).order_by('-total', 'department'):
        writer.writerow([item['department'], item['total']])
    return response


@role_required("Director", "Deputy Director", "Staff", "Registry", "Admin")
def export_login_history_csv(request):
    staff_user = get_logged_in_staff(request)
    require_permission(staff_user, "view_access_history", "You do not have permission to export access history.")

    search_query = request.GET.get('search', '').strip()
    event_filter = request.GET.get('event', '').strip()
    date_from = request.GET.get('date_from', '').strip()
    date_to = request.GET.get('date_to', '').strip()
    login_history_qs = LoginHistory.objects.select_related('staff').all()

    if staff_user.role == "Deputy Director":
        if staff_user.department:
            login_history_qs = login_history_qs.filter(Q(staff__department=staff_user.department) | Q(staff=staff_user))
        else:
            login_history_qs = login_history_qs.filter(staff=staff_user)

    if search_query:
        login_history_qs = login_history_qs.filter(
            Q(username__icontains=search_query) |
            Q(role__icontains=search_query) |
            Q(ip_address__icontains=search_query) |
            Q(staff__full_name__icontains=search_query)
        )

    if event_filter:
        login_history_qs = login_history_qs.filter(event_type=event_filter)
    if date_from:
        login_history_qs = login_history_qs.filter(logged_in_at__date__gte=date_from)
    if date_to:
        login_history_qs = login_history_qs.filter(logged_in_at__date__lte=date_to)

    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = 'attachment; filename="login_history_export.csv"'
    writer = csv.writer(response)
    writer.writerow(['Event', 'Staff', 'Username', 'Role', 'IP Address', 'User Agent', 'Time'])
    for item in login_history_qs.order_by('-logged_in_at'):
        writer.writerow([
            item.get_event_type_display(),
            item.staff.full_name if item.staff else '',
            item.username,
            item.role,
            item.ip_address,
            item.user_agent,
            item.logged_in_at.strftime('%Y-%m-%d %H:%M:%S'),
        ])
    return response


@role_required("Director", "Deputy Director", "Staff", "Registry", "Admin")
def export_audit_logs_csv(request):
    staff_user = get_logged_in_staff(request)
    require_permission(staff_user, "view_access_history", "You do not have permission to export audit logs.")

    search_query = request.GET.get('search', '').strip()
    date_from = request.GET.get('date_from', '').strip()
    date_to = request.GET.get('date_to', '').strip()
    audit_logs_qs = AuditLog.objects.select_related('actor').all()

    if staff_user.role == "Deputy Director":
        if staff_user.department:
            audit_logs_qs = audit_logs_qs.filter(Q(actor__department=staff_user.department) | Q(actor=staff_user))
        else:
            audit_logs_qs = audit_logs_qs.filter(actor=staff_user)

    if search_query:
        audit_logs_qs = audit_logs_qs.filter(
            Q(actor__full_name__icontains=search_query) |
            Q(action__icontains=search_query) |
            Q(target_type__icontains=search_query) |
            Q(target_label__icontains=search_query) |
            Q(details__icontains=search_query)
        )
    if date_from:
        audit_logs_qs = audit_logs_qs.filter(created_at__date__gte=date_from)
    if date_to:
        audit_logs_qs = audit_logs_qs.filter(created_at__date__lte=date_to)

    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = 'attachment; filename="audit_logs_export.csv"'
    writer = csv.writer(response)
    writer.writerow(['Actor', 'Action', 'Target Type', 'Target', 'Details', 'Time'])
    for item in audit_logs_qs.order_by('-created_at'):
        writer.writerow([
            item.actor.full_name if item.actor else '',
            item.action,
            item.target_type,
            item.target_label,
            item.details,
            item.created_at.strftime('%Y-%m-%d %H:%M:%S'),
        ])
    return response


@role_required("Admin")
def backup_restore_center(request):
    backup_root = Path(settings.BASE_DIR) / "backups"
    backup_folders = []

    if backup_root.exists():
        for folder in sorted([item for item in backup_root.iterdir() if item.is_dir()], reverse=True):
            db_exists = (folder / "db.sqlite3").exists()
            media_exists = (folder / "media").exists()
            backup_folders.append({
                "name": folder.name,
                "has_database": db_exists,
                "has_media": media_exists,
                "modified_at": timezone.make_aware(datetime.fromtimestamp(folder.stat().st_mtime), timezone.get_current_timezone()),
            })

    latest_backup = backup_folders[0] if backup_folders else None
    return render(request, "coreapp/backup_restore.html", {
        **get_base_context(request),
        "latest_backup": latest_backup,
        "backup_folders": backup_folders[:10],
    })


@role_required("Admin")
def it_admin_center(request):
    staff_user = get_logged_in_staff(request)
    backup_root = Path(settings.BASE_DIR) / "backups"
    backup_folders = []

    if backup_root.exists():
        for folder in sorted([item for item in backup_root.iterdir() if item.is_dir()], reverse=True):
            backup_folders.append({
                "name": folder.name,
                "has_database": (folder / "db.sqlite3").exists(),
                "has_media": (folder / "media").exists(),
                "modified_at": timezone.make_aware(datetime.fromtimestamp(folder.stat().st_mtime), timezone.get_current_timezone()),
            })

    if request.method == "POST":
        category = request.POST.get("category", "").strip()
        title = request.POST.get("title", "").strip()
        details = request.POST.get("details", "").strip()

        if not category or not title or not details:
            messages.error(request, "Category, title, and details are required for a maintenance log.")
        else:
            log_entry = ITMaintenanceLog.objects.create(
                category=category,
                title=title,
                details=details,
                logged_by=staff_user,
            )
            log_audit_event(
                staff_user,
                "IT Maintenance Logged",
                "IT Admin",
                log_entry.title,
                f"Category: {log_entry.category}",
            )
            messages.success(request, "IT maintenance log saved successfully.")
            return redirect("it_admin_center")

    technical_notes = [
        {
            "title": "Server and machine control",
            "detail": "Use this workspace to track server maintenance, Windows machine preparation, deployment readiness, and technical operational notes.",
        },
        {
            "title": "Backup operations",
            "detail": "Confirm recent backup folders exist and note when the database and media were copied off the primary machine.",
        },
        {
            "title": "Infrastructure readiness",
            "detail": "Track SMTP setup, Redis availability, dependency updates, firewall/network decisions, and patch windows.",
        },
    ]

    setup_guides = [
        {
            "title": "Server checklist",
            "steps": [
                "Keep Windows, Python, and installed dependencies patched.",
                "Restrict OS login access to trusted technical staff only.",
                "Document who changed the server and when.",
            ],
        },
        {
            "title": "Deployment checklist",
            "steps": [
                "Set the production environment file and verify allowed hosts.",
                "Confirm static files, backups, and email delivery before go-live.",
                "Record deployment date, version, and rollback plan in the maintenance log.",
            ],
        },
        {
            "title": "Backup checklist",
            "steps": [
                "Run backup-system.ps1 and confirm both database and media are included.",
                "Store backup copies away from the main machine.",
                "Log each backup or restore action in the maintenance history below.",
            ],
        },
    ]

    latest_backup = backup_folders[0] if backup_folders else None

    return render(request, "coreapp/it_admin_center.html", {
        **get_base_context(request),
        "latest_backup": latest_backup,
        "backup_folders": backup_folders[:8],
        "technical_notes": technical_notes,
        "setup_guides": setup_guides,
        "maintenance_logs": ITMaintenanceLog.objects.select_related('logged_by')[:12],
    })


@role_required("Admin")
def security_checklist(request):
    security_items = [
        {
            "title": "HTTPS enabled in production",
            "status": "Required",
            "detail": "Run behind a reverse proxy or web server with a real TLS certificate so passwords, cookies, and sessions are encrypted in transit.",
        },
        {
            "title": "Shared cache for login throttling",
            "status": "Recommended",
            "detail": "Set DJANGO_CACHE_BACKEND=redis and REDIS_URL so failed-login protection works across all production workers.",
        },
        {
            "title": "Email delivery configured",
            "status": "Recommended",
            "detail": "SMTP should be configured so alerts, password resets, and future verification features can be delivered reliably.",
        },
        {
            "title": "Strict host and secret configuration",
            "status": "Required",
            "detail": "Use environment variables only for DJANGO_SECRET_KEY, allowed hosts, email credentials, and Redis settings.",
        },
        {
            "title": "Backups scheduled",
            "status": "Required",
            "detail": "Run backup-system.ps1 on a schedule and copy backup folders off the server so SQLite data and attachments can be recovered.",
        },
        {
            "title": "Server access locked down",
            "status": "Required",
            "detail": "Only trusted administrators should have OS-level access to the Windows machine, Python environment, and backup files.",
        },
    ]

    setup_guides = [
        {
            "title": "Redis Setup",
            "steps": [
                "Install Redis on the production host or use a managed Redis service.",
                "Set DJANGO_CACHE_BACKEND=redis and REDIS_URL in the production environment file.",
                "Restart Django and verify login throttling works across all workers.",
            ],
        },
        {
            "title": "Email Setup",
            "steps": [
                "Configure EMAIL_BACKEND, EMAIL_HOST, EMAIL_PORT, EMAIL_HOST_USER, EMAIL_HOST_PASSWORD, EMAIL_USE_TLS, and DEFAULT_FROM_EMAIL.",
                "Make sure Director and Deputy Director staff records have valid email addresses.",
                "Use the Send Test Email page to confirm delivery before production go-live.",
            ],
        },
        {
            "title": "Backup Setup",
            "steps": [
                "Run backup-system.ps1 once to create a timestamped backup of db.sqlite3 and media.",
                "Create a Windows Task Scheduler job to run the script automatically.",
                "Copy the resulting backups folder to another machine or secure storage.",
            ],
        },
    ]

    return render(request, "coreapp/security_checklist.html", {
        **get_base_context(request),
        "security_items": security_items,
        "dependency_audit_notes": get_dependency_audit_notes(),
        "setup_guides": setup_guides,
        "redis_configured": getattr(settings, "CACHES", {}).get("default", {}).get("BACKEND", "").endswith("RedisCache"),
        "email_backend": getattr(settings, "EMAIL_BACKEND", ""),
    })


@role_required("Admin")
def send_test_email(request):
    staff_user = get_logged_in_staff(request)
    default_email = (staff_user.email if staff_user and staff_user.email else '') or (staff_user.user.email if staff_user and staff_user.user else '')

    if request.method == "POST":
        target_email = request.POST.get("target_email", "").strip()

        if not target_email:
            messages.error(request, "Enter an email address to receive the test message.")
        else:
            try:
                send_mail(
                    subject="PPBMED SMTP test email",
                    message=(
                        "This is a test email from the PPBMED Document Tracking System.\n\n"
                        "If you received this message, SMTP is configured and working for OTP and security notifications."
                    ),
                    from_email=getattr(settings, "DEFAULT_FROM_EMAIL", None),
                    recipient_list=[target_email],
                    fail_silently=False,
                )
            except Exception as exc:
                messages.error(request, f"Test email failed: {exc}")
                log_audit_event(
                    staff_user,
                    "Test Email Failed",
                    "Security",
                    target_email,
                    str(exc),
                )
            else:
                messages.success(request, f"Test email sent to {target_email}.")
                log_audit_event(
                    staff_user,
                    "Test Email Sent",
                    "Security",
                    target_email,
                    "Sent SMTP verification email from the security checklist.",
                )
                return redirect("send_test_email")

    return render(request, "coreapp/send_test_email.html", {
        **get_base_context(request),
        "default_email": default_email,
        "email_backend": getattr(settings, "EMAIL_BACKEND", ""),
        "default_from_email": getattr(settings, "DEFAULT_FROM_EMAIL", ""),
    })


@role_required("Admin")
def role_permissions(request):
    staff_user = get_logged_in_staff(request)
    manageable_roles = [role for role, _ in Staff.ROLE_CHOICES]

    if request.method == "POST":
        for role in manageable_roles:
            for permission_key, _, _ in PERMISSION_DEFINITIONS:
                enabled = request.POST.get(f"{role}__{permission_key}") == "on"
                RolePermission.objects.update_or_create(
                    role=role,
                    permission_key=permission_key,
                    defaults={"enabled": enabled},
                )

        log_audit_event(
            staff_user,
            "Role Permissions Updated",
            "Security",
            "Role Permissions",
            "Updated centralized role permission settings.",
        )
        messages.success(request, "Role permissions updated successfully.")
        return redirect("role_permissions")

    role_permission_rows = []
    for role in manageable_roles:
        permission_map = get_role_permission_map(role)
        role_permission_rows.append({
            "role": role,
            "permissions": [
                {
                    "key": permission_key,
                    "label": PERMISSION_META[permission_key]["label"],
                    "description": PERMISSION_META[permission_key]["description"],
                    "enabled": permission_map.get(permission_key, False),
                }
                for permission_key, _, _ in PERMISSION_DEFINITIONS
            ],
        })

    return render(request, "coreapp/role_permissions.html", {
        **get_base_context(request),
        "role_permission_rows": role_permission_rows,
        "permission_definitions": [
            {
                "key": permission_key,
                "label": label,
                "description": description,
            }
            for permission_key, label, description in PERMISSION_DEFINITIONS
        ],
    })


@role_required("Director", "Deputy Director", "Staff", "Registry", "Admin")
def download_document_attachment(request, pk):
    staff_user = get_logged_in_staff(request)
    document = get_object_or_404(Document.objects.select_related('assigned_to'), pk=pk)

    require_permission(staff_user, "view_document_attachment", "You do not have permission to access attachments.")

    if not can_access_document(staff_user, document):
        raise PermissionDenied("You do not have permission to access this attachment.")

    if not document.attachment:
        raise Http404("Attachment not found.")

    log_audit_event(
        staff_user,
        "Attachment Downloaded",
        "Document",
        document.reference_id,
        "Downloaded primary document attachment.",
    )
    return FileResponse(document.attachment.open('rb'), as_attachment=False, filename=document.attachment.name.split('/')[-1])


@role_required("Director", "Deputy Director", "Staff", "Registry", "Admin")
def download_routing_attachment(request, pk):
    staff_user = get_logged_in_staff(request)
    routing = get_object_or_404(
        DocumentRouting.objects.select_related('document', 'document__assigned_to'),
        pk=pk
    )

    require_permission(staff_user, "view_document_attachment", "You do not have permission to access attachments.")

    if not can_access_document(staff_user, routing.document):
        raise PermissionDenied("You do not have permission to access this attachment.")

    if not routing.attachment:
        raise Http404("Attachment not found.")

    log_audit_event(
        staff_user,
        "Attachment Downloaded",
        "Routing",
        routing.document.reference_id,
        f"Downloaded routing attachment for action {routing.action}.",
    )
    return FileResponse(routing.attachment.open('rb'), as_attachment=False, filename=routing.attachment.name.split('/')[-1])


@role_required("Director", "Deputy Director", "Staff", "Registry", "Admin")
def download_message_attachment(request, pk):
    staff_user = get_logged_in_staff(request)
    staff_message = get_object_or_404(
        StaffMessage.objects.select_related('sender'),
        pk=pk,
    )

    require_permission(staff_user, "view_messages", "You do not have permission to access message attachments.")

    is_participant = (
        staff_message.sender_id == staff_user.pk
        or StaffMessageRecipient.objects.filter(staff_message=staff_message, recipient=staff_user).exists()
    )
    if not is_participant:
        raise PermissionDenied("You do not have permission to access this message attachment.")

    if not staff_message.attachment:
        raise Http404("Attachment not found.")

    log_audit_event(
        staff_user,
        "Attachment Downloaded",
        "Message",
        staff_message.subject,
        "Downloaded message attachment.",
    )
    return FileResponse(
        staff_message.attachment.open('rb'),
        as_attachment=False,
        filename=Path(staff_message.attachment.name).name,
    )


@role_required("Director", "Deputy Director", "Staff", "Registry", "Admin")
def export_document_history_pdf(request, pk):
    staff_user = get_logged_in_staff(request)
    document = get_object_or_404(Document.objects.select_related('assigned_to'), pk=pk)

    require_permission(staff_user, "export_document_pdf", "You do not have permission to export document history.")

    if not can_access_document(staff_user, document):
        raise PermissionDenied("You do not have permission to export this document.")

    response = HttpResponse(content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="document_history_{document.reference_id}.pdf"'

    pdf = canvas.Canvas(response, pagesize=A4)
    width, height = A4
    y = height - 50

    pdf.setFont("Helvetica-Bold", 16)
    pdf.drawString(50, y, "PPBMED Document History Report")
    y -= 30

    pdf.setFont("Helvetica", 11)
    pdf.drawString(50, y, f"Reference ID: {document.reference_id}")
    y -= 18
    pdf.drawString(50, y, f"Subject: {document.subject}")
    y -= 18
    pdf.drawString(50, y, f"Status: {document.status}")
    y -= 18
    pdf.drawString(50, y, f"Priority: {document.priority}")
    y -= 18
    pdf.drawString(50, y, f"Origin: {document.origin}")
    y -= 18
    pdf.drawString(50, y, f"Destination: {document.destination}")
    y -= 18
    pdf.drawString(50, y, f"Assigned To: {document.assigned_to.full_name if document.assigned_to else '-'}")
    y -= 30

    pdf.setFont("Helvetica-Bold", 13)
    pdf.drawString(50, y, "Routing History")
    y -= 20

    pdf.setFont("Helvetica", 10)
    for item in document.routing_history.select_related('from_officer', 'to_officer').all():
        line = (
            f"{item.action_date.strftime('%Y-%m-%d %H:%M')} | "
            f"{item.action} | "
            f"From: {item.from_officer.full_name if item.from_officer else '-'} | "
            f"To: {item.to_officer.full_name if item.to_officer else '-'}"
        )
        pdf.drawString(50, y, line[:110])
        y -= 16

        if item.note:
            pdf.drawString(65, y, f"Note: {item.note[:100]}")
            y -= 16

        if y < 60:
            pdf.showPage()
            y = height - 50
            pdf.setFont("Helvetica", 10)

    pdf.save()
    return response


@role_required("Director", "Deputy Director", "Staff", "Registry", "Admin")
def staff(request):
    staff_user = get_logged_in_staff(request)
    require_permission(staff_user, "view_staff_directory", "You do not have permission to view the staff directory.")
    staff_qs = Staff.objects.select_related('user').all().order_by('full_name')
    archive_filter = request.GET.get('archive', 'active').strip() or 'active'

    if staff_user.role == "Deputy Director" and staff_user.department:
        staff_qs = staff_qs.filter(department=staff_user.department)

    search_query = request.GET.get('search', '')
    role_filter = request.GET.get('role', '')
    active_filter = request.GET.get('active', '')

    if archive_filter == 'archived':
        staff_qs = staff_qs.filter(is_archived=True)
    elif archive_filter == 'all':
        pass
    else:
        staff_qs = staff_qs.filter(is_archived=False)

    if search_query:
        staff_qs = staff_qs.filter(
            Q(full_name__icontains=search_query) |
            Q(role__icontains=search_query) |
            Q(department__icontains=search_query) |
            Q(email__icontains=search_query)
        )

    if role_filter:
        staff_qs = staff_qs.filter(role=role_filter)

    if active_filter == 'active':
        staff_qs = staff_qs.filter(is_active=True)
    elif active_filter == 'inactive':
        staff_qs = staff_qs.filter(is_active=False)

    paginator = Paginator(staff_qs, 10)
    page_number = request.GET.get('page')
    staff_members = paginator.get_page(page_number)
    visible_staff = Staff.objects.filter(is_archived=False)
    if staff_user.role == "Deputy Director" and staff_user.department:
        visible_staff = visible_staff.filter(department=staff_user.department)

    return render(request, "coreapp/staff.html", {
        **get_base_context(request),
        "staff_directory_read_only": not has_role_permission(staff_user, "manage_staff"),
        "staff_members": staff_members,
        "search_query": search_query,
        "role_filter": role_filter,
        "active_filter": active_filter,
        "archive_filter": archive_filter,
        "staff_total_count": visible_staff.count(),
        "staff_active_count": visible_staff.filter(is_active=True).count(),
        "staff_inactive_count": visible_staff.filter(is_active=False).count(),
        "staff_directors_count": visible_staff.filter(role="Director").count(),
        "staff_archived_count": Staff.objects.filter(is_archived=True).count(),
    })


@role_required("Director", "Deputy Director", "Staff", "Registry", "Admin")
def add_staff(request):
    staff_user = get_logged_in_staff(request)
    require_permission(staff_user, "manage_staff", "You do not have permission to add staff.")
    if request.method == 'POST':
        form = StaffForm(request.POST)
        if form.is_valid():
            new_staff = form.save(commit=False)
            create_login_account = form.cleaned_data.get('create_login_account')
            selected_user = form.cleaned_data.get('user')

            if create_login_account:
                username = form.cleaned_data.get('username')
                password = form.cleaned_data.get('password')
                email = form.cleaned_data.get('email')

                new_user = User.objects.create_user(
                    username=username,
                    password=password,
                    email=email
                )
                new_staff.user = new_user
            elif selected_user:
                new_staff.user = selected_user

            new_staff.save()
            log_audit_event(
                staff_user,
                "Staff Added",
                "Staff",
                new_staff.full_name,
                f"Created staff profile with role {new_staff.role}.",
            )
            messages.success(request, f"Staff {new_staff.full_name} added successfully.")
            return redirect('staff')
    else:
        form = StaffForm()

    return render(request, 'coreapp/add_staff.html', {
        **get_base_context(request),
        'form': form,
    })


@role_required("Director", "Deputy Director", "Staff", "Registry", "Admin")
def edit_staff(request, pk):
    staff_user = get_logged_in_staff(request)
    require_permission(staff_user, "manage_staff", "You do not have permission to edit staff.")
    staff_member = get_object_or_404(Staff, pk=pk)

    if request.method == 'POST':
        form = StaffForm(request.POST, instance=staff_member)
        if form.is_valid():
            updated_staff = form.save(commit=False)

            create_login_account = form.cleaned_data.get('create_login_account')
            selected_user = form.cleaned_data.get('user')
            username = form.cleaned_data.get('username')
            password = form.cleaned_data.get('password')
            email = form.cleaned_data.get('email')

            if create_login_account and not updated_staff.user:
                new_user = User.objects.create_user(
                    username=username,
                    password=password,
                    email=email
                )
                updated_staff.user = new_user
            elif selected_user:
                updated_staff.user = selected_user

            updated_staff.save()
            log_audit_event(
                staff_user,
                "Staff Updated",
                "Staff",
                updated_staff.full_name,
                f"Updated staff profile. Role: {updated_staff.role}. Active: {updated_staff.is_active}.",
            )
            messages.success(request, f"Staff {updated_staff.full_name} updated successfully.")
            return redirect('staff')
    else:
        form = StaffForm(instance=staff_member)

    return render(request, 'coreapp/edit_staff.html', {
        **get_base_context(request),
        'form': form,
        'staff_member': staff_member,
    })


@role_required("Director", "Deputy Director", "Staff", "Registry", "Admin")
def delete_staff(request, pk):
    staff_user = get_logged_in_staff(request)
    require_permission(staff_user, "manage_staff", "You do not have permission to delete staff.")
    staff_member = get_object_or_404(Staff, pk=pk)

    if request.method == 'POST':
        confirmation = request.POST.get("confirm_full_name", "").strip()
        if confirmation != staff_member.full_name:
            return render(request, 'coreapp/delete_staff.html', {
                **get_base_context(request),
                'staff_member': staff_member,
                'confirmation_error': "Type the exact full name to confirm staff archiving.",
            })

        full_name = staff_member.full_name
        staff_member.is_archived = True
        staff_member.archived_at = timezone.now()
        staff_member.is_active = False
        staff_member.save(update_fields=['is_archived', 'archived_at', 'is_active'])
        log_audit_event(
            staff_user,
            "Staff Archived",
            "Staff",
            full_name,
            f"Archived staff profile {full_name}.",
        )
        messages.success(request, f"Staff {full_name} archived successfully.")
        return redirect('staff')

    return render(request, 'coreapp/delete_staff.html', {
        **get_base_context(request),
        'staff_member': staff_member,
    })


@role_required("Director", "Deputy Director", "Staff", "Registry", "Admin")
def restore_staff(request, pk):
    staff_user = get_logged_in_staff(request)
    require_permission(staff_user, "manage_staff", "You do not have permission to restore staff.")
    staff_member = get_object_or_404(Staff, pk=pk)

    staff_member.is_archived = False
    staff_member.archived_at = None
    staff_member.is_active = True
    staff_member.save(update_fields=['is_archived', 'archived_at', 'is_active'])
    log_audit_event(
        staff_user,
        "Staff Restored",
        "Staff",
        staff_member.full_name,
        f"Restored archived staff profile {staff_member.full_name}.",
    )
    messages.success(request, f"Staff {staff_member.full_name} restored successfully.")
    return redirect('staff')


@role_required("Director", "Deputy Director", "Staff", "Registry", "Admin")
def messages_page(request):
    staff_user = get_logged_in_staff(request)
    require_permission(staff_user, "view_messages", "You do not have permission to view messages.")

    inbox_qs = (
        StaffMessageRecipient.objects
        .select_related('staff_message', 'staff_message__sender', 'recipient')
        .filter(recipient=staff_user)
        .order_by('-staff_message__created_at')
    )
    sent_links_qs = (
        StaffMessageRecipient.objects
        .select_related('staff_message', 'staff_message__sender', 'recipient')
        .filter(staff_message__sender=staff_user)
        .order_by('-staff_message__created_at')
    )
    unread_count = inbox_qs.filter(is_read=False).count()
    sent_message_count = StaffMessage.objects.filter(sender=staff_user).count()
    form = MessageComposeForm(sender=staff_user)

    if request.method == 'POST':
        form = MessageComposeForm(request.POST, request.FILES, sender=staff_user)

        if form.is_valid():
            message_record = form.save(commit=False)
            message_record.sender = staff_user
            message_record.save()

            recipients = form.cleaned_data['recipients']
            recipient_links = [
                StaffMessageRecipient(staff_message=message_record, recipient=recipient)
                for recipient in recipients
            ]
            StaffMessageRecipient.objects.bulk_create(recipient_links)

            log_audit_event(
                staff_user,
                "Message Sent",
                "Message",
                message_record.subject,
                f"Sent message to {recipients.count()} recipient(s).",
            )
            messages.success(request, "Message sent successfully.")
            first_recipient = recipients.first()
            return redirect(get_messages_redirect(counterpart=first_recipient))

    conversation_map = {}

    def get_conversation(counterpart):
        if counterpart.pk not in conversation_map:
            conversation_map[counterpart.pk] = {
                "counterpart": counterpart,
                "entries": [],
                "unread_count": 0,
                "last_at": None,
                "last_preview": "",
                "last_subject": "",
                "last_direction": "incoming",
            }
        return conversation_map[counterpart.pk]

    def update_conversation(conversation, subject, body, attachment_data, created_at, direction):
        if conversation["last_at"] is None or created_at > conversation["last_at"]:
            conversation["last_at"] = created_at
            conversation["last_preview"] = build_message_preview(body, attachment_data)
            conversation["last_subject"] = subject
            conversation["last_direction"] = direction

    for item in inbox_qs:
        counterpart = item.staff_message.sender
        conversation = get_conversation(counterpart)
        attachment_data = build_message_attachment_data(item.staff_message)
        conversation["entries"].append({
            "pk": item.pk,
            "direction": "incoming",
            "subject": item.staff_message.subject,
            "body": item.staff_message.body,
            "attachment": attachment_data,
            "created_at": item.staff_message.created_at,
            "is_read": item.is_read,
        })
        if not item.is_read:
            conversation["unread_count"] += 1
        update_conversation(
            conversation,
            item.staff_message.subject,
            item.staff_message.body,
            attachment_data,
            item.staff_message.created_at,
            "incoming",
        )

    for item in sent_links_qs:
        counterpart = item.recipient
        conversation = get_conversation(counterpart)
        attachment_data = build_message_attachment_data(item.staff_message)
        conversation["entries"].append({
            "pk": item.pk,
            "direction": "outgoing",
            "subject": item.staff_message.subject,
            "body": item.staff_message.body,
            "attachment": attachment_data,
            "created_at": item.staff_message.created_at,
            "is_read": True,
        })
        update_conversation(
            conversation,
            item.staff_message.subject,
            item.staff_message.body,
            attachment_data,
            item.staff_message.created_at,
            "outgoing",
        )

    conversations = sorted(
        conversation_map.values(),
        key=lambda item: item["last_at"] or timezone.now(),
        reverse=True,
    )

    active_conversation = None
    selected_counterpart_id = request.GET.get('with')
    if selected_counterpart_id and selected_counterpart_id.isdigit():
        active_conversation = conversation_map.get(int(selected_counterpart_id))
    if not active_conversation and conversations:
        active_conversation = conversations[0]

    for conversation in conversations:
        conversation["entries"] = sorted(conversation["entries"], key=lambda item: item["created_at"])
        conversation["is_selected"] = (
            active_conversation is not None
            and conversation["counterpart"].pk == active_conversation["counterpart"].pk
        )

    active_messages = active_conversation["entries"][-60:] if active_conversation else []

    return render(request, "coreapp/messages.html", {
        **get_base_context(request),
        "form": form,
        "conversation_list": conversations,
        "conversation_count": len(conversations),
        "active_conversation": active_conversation,
        "active_messages": active_messages,
        "unread_message_count": unread_count,
        "sent_message_count": sent_message_count,
        "can_manage_messages": has_role_permission(staff_user, "manage_messages"),
        "can_start_messages": True,
        "message_attachment_accept": UPLOAD_ACCEPT_ATTR,
        "show_compose_panel": (
            request.method == 'POST' or
            request.GET.get('compose') == '1' or not conversations
        ),
    })


@role_required("Director", "Deputy Director", "Staff", "Registry", "Admin")
def send_chat_message(request, staff_pk):
    staff_user = get_logged_in_staff(request)
    require_permission(staff_user, "view_messages", "You do not have permission to send messages.")

    if request.method != 'POST':
        return redirect('messages')

    counterpart = get_object_or_404(
        Staff.objects.filter(is_active=True, is_archived=False),
        pk=staff_pk,
    )
    if counterpart.pk == staff_user.pk:
        messages.error(request, "You cannot send a message to yourself.")
        return redirect(get_messages_redirect())

    reply_form = MessageReplyForm(request.POST, request.FILES)
    if not reply_form.is_valid():
        messages.error(request, reply_form.non_field_errors()[0] if reply_form.non_field_errors() else reply_form.errors.get('body', ['Enter a message.'])[0])
        return redirect(get_messages_redirect(counterpart=counterpart))

    latest_incoming = (
        StaffMessageRecipient.objects
        .select_related('staff_message')
        .filter(recipient=staff_user, staff_message__sender=counterpart)
        .order_by('-staff_message__created_at')
        .first()
    )
    latest_outgoing = (
        StaffMessageRecipient.objects
        .select_related('staff_message')
        .filter(recipient=counterpart, staff_message__sender=staff_user)
        .order_by('-staff_message__created_at')
        .first()
    )
    latest_subject = ""
    if latest_incoming and latest_outgoing:
        latest_subject = (
            latest_incoming.staff_message.subject
            if latest_incoming.staff_message.created_at >= latest_outgoing.staff_message.created_at
            else latest_outgoing.staff_message.subject
        )
    elif latest_incoming:
        latest_subject = latest_incoming.staff_message.subject
    elif latest_outgoing:
        latest_subject = latest_outgoing.staff_message.subject

    subject = build_chat_subject(latest_subject, counterpart)
    had_prior_exchange = bool(latest_incoming or latest_outgoing)

    send_single_staff_message(
        sender=staff_user,
        recipient=counterpart,
        subject=subject,
        body=reply_form.cleaned_data['body'],
        attachment=reply_form.cleaned_data.get('attachment'),
        actor_notice=f"Message sent to {counterpart.full_name}.",
        audit_action="Message Reply Sent" if had_prior_exchange else "Message Sent",
    )

    StaffMessageRecipient.objects.filter(
        recipient=staff_user,
        staff_message__sender=counterpart,
        is_read=False,
    ).update(is_read=True, read_at=timezone.now())
    Notification.objects.filter(
        recipient=staff_user,
        staff_message__sender=counterpart,
        notification_type='message',
        is_read=False,
    ).update(is_read=True)

    messages.success(request, "Message sent successfully.")
    return redirect(get_messages_redirect(counterpart=counterpart))


@role_required("Director", "Deputy Director", "Staff", "Registry", "Admin")
def reply_message(request, pk):
    staff_user = get_logged_in_staff(request)
    require_permission(staff_user, "view_messages", "You do not have permission to reply to messages.")

    if request.method != 'POST':
        return redirect('messages')

    original_link = get_object_or_404(
        StaffMessageRecipient.objects.select_related('staff_message', 'staff_message__sender', 'recipient'),
        pk=pk,
        recipient=staff_user,
    )
    reply_form = MessageReplyForm(request.POST, request.FILES)

    if not reply_form.is_valid():
        messages.error(request, reply_form.non_field_errors()[0] if reply_form.non_field_errors() else reply_form.errors.get('body', ['Enter a reply message.'])[0])
        return redirect('messages')

    reply_recipient = original_link.staff_message.sender
    if reply_recipient == staff_user:
        messages.error(request, "You cannot reply to your own message.")
        return redirect(get_messages_redirect())

    original_link.mark_read()

    send_single_staff_message(
        sender=staff_user,
        recipient=reply_recipient,
        subject=build_chat_subject(original_link.staff_message.subject, reply_recipient),
        body=reply_form.cleaned_data['body'],
        attachment=reply_form.cleaned_data.get('attachment'),
        actor_notice=f"Reply sent to {reply_recipient.full_name}.",
        audit_action="Message Reply Sent",
    )
    messages.success(request, "Reply sent successfully.")
    return redirect(get_messages_redirect(counterpart=reply_recipient))


@role_required("Director", "Deputy Director", "Staff", "Registry", "Admin")
def mark_message_read(request, pk):
    staff_user = get_logged_in_staff(request)
    recipient_link = get_object_or_404(
        StaffMessageRecipient.objects.select_related('staff_message', 'recipient'),
        pk=pk,
        recipient=staff_user,
    )
    recipient_link.mark_read()
    Notification.objects.filter(
        recipient=staff_user,
        staff_message=recipient_link.staff_message,
        notification_type='message',
        is_read=False,
    ).update(is_read=True)
    messages.success(request, "Message marked as read.")
    counterpart_id = request.GET.get('with')
    if counterpart_id and counterpart_id.isdigit():
        return redirect(f"{reverse('messages')}?with={counterpart_id}")
    return redirect('messages')


@role_required("Director", "Deputy Director", "Staff", "Registry", "Admin")
def notifications_page(request):
    staff_user = get_logged_in_staff(request)
    notifications_qs = (
        Notification.objects
        .select_related('document', 'staff_message', 'staff_message__sender')
        .filter(recipient=staff_user)
        .exclude(notification_type='message')
        .order_by('-created_at')
    )
    unread_notifications = notifications_qs.filter(is_read=False)

    paginator = Paginator(notifications_qs, 10)
    page_number = request.GET.get('page')
    notifications = paginator.get_page(page_number)

    return render(request, "coreapp/notifications.html", {
        **get_base_context(request),
        "notifications": notifications,
        "all_notifications_count": notifications_qs.count(),
        "unread_notifications_total": unread_notifications.count(),
        "read_notifications_total": notifications_qs.filter(is_read=True).count(),
        "document_notifications_total": notifications_qs.filter(document__isnull=False).count(),
    })


@role_required("Director", "Deputy Director", "Staff", "Registry", "Admin")
def open_notification(request, pk):
    staff_user = get_logged_in_staff(request)
    notification = get_object_or_404(Notification.objects.select_related('document', 'staff_message'), pk=pk, recipient=staff_user)

    if not notification.is_read:
        notification.is_read = True
        notification.save()

    if notification.document:
        return redirect('document_detail', pk=notification.document.pk)

    if notification.staff_message:
        StaffMessageRecipient.objects.filter(
            staff_message=notification.staff_message,
            recipient=staff_user,
        ).update(is_read=True, read_at=timezone.now())
        return redirect('messages')

    return redirect('notifications')


@role_required("Director", "Deputy Director", "Staff", "Registry", "Admin")
def mark_notification_read(request, pk):
    staff_user = get_logged_in_staff(request)
    notification = get_object_or_404(Notification, pk=pk, recipient=staff_user)
    notification.is_read = True
    notification.save()
    messages.success(request, "Notification marked as read.")
    return redirect('notifications')


@role_required("Director", "Deputy Director", "Staff", "Registry", "Admin")
def mark_all_notifications_read(request):
    staff_user = get_logged_in_staff(request)
    Notification.objects.filter(recipient=staff_user, is_read=False).exclude(notification_type='message').update(is_read=True)
    messages.success(request, "All notifications marked as read.")
    return redirect('notifications')


@role_required("Director", "Deputy Director", "Staff", "Registry", "Admin")
def settings_page(request):
    staff_user = get_logged_in_staff(request)
    preferences, _ = SystemPreference.objects.get_or_create(staff=staff_user)
    permission_map = get_role_permission_map(staff_user.role)

    profile_form = ProfileSettingsForm(instance=staff_user)
    preference_form = PreferenceSettingsForm(instance=preferences)
    password_form = PasswordChangeCustomForm(request.user)

    if request.method == "POST":
        action = request.POST.get("action")

        if action == "profile":
            profile_form = ProfileSettingsForm(request.POST, instance=staff_user)
            preference_form = PreferenceSettingsForm(instance=preferences)
            password_form = PasswordChangeCustomForm(request.user)

            if profile_form.is_valid():
                updated_staff = profile_form.save(commit=False)

                if staff_user.user and updated_staff.email:
                    staff_user.user.email = updated_staff.email
                    staff_user.user.save()

                updated_staff.save()
                log_audit_event(
                    staff_user,
                    "Profile Updated",
                    "Settings",
                    staff_user.full_name,
                    "Updated profile settings.",
                )
                messages.success(request, "Profile settings saved successfully.")
                return redirect("settings")

        elif action == "preferences":
            profile_form = ProfileSettingsForm(instance=staff_user)
            preference_form = PreferenceSettingsForm(request.POST, instance=preferences)
            password_form = PasswordChangeCustomForm(request.user)

            if preference_form.is_valid():
                preference_form.save()
                log_audit_event(
                    staff_user,
                    "Preferences Updated",
                    "Settings",
                    staff_user.full_name,
                    "Updated notification or interface preferences.",
                )
                messages.success(request, "System preferences saved successfully.")
                return redirect("settings")

        elif action == "password":
            profile_form = ProfileSettingsForm(instance=staff_user)
            preference_form = PreferenceSettingsForm(instance=preferences)
            password_form = PasswordChangeCustomForm(request.user, request.POST)

            if password_form.is_valid():
                new_password = password_form.cleaned_data["new_password"]
                request.user.set_password(new_password)
                request.user.save()
                log_audit_event(
                    staff_user,
                    "Password Changed",
                    "Settings",
                    staff_user.full_name,
                    "Changed account password.",
                )
                messages.success(request, "Password changed successfully. Please log in again.")
                return redirect("login")

    return render(request, "coreapp/settings.html", {
        **get_base_context(request),
        "profile_form": profile_form,
        "preference_form": preference_form,
        "password_form": password_form,
        "preferences": preferences,
        "role_access_summary": get_role_access_summary(staff_user.role),
        "control_governance_summary": get_control_governance_summary(),
        "enabled_permission_items": [
            {
                "key": permission_key,
                "label": PERMISSION_META[permission_key]["label"],
                "description": PERMISSION_META[permission_key]["description"],
            }
            for permission_key, _, _ in PERMISSION_DEFINITIONS
            if permission_map.get(permission_key)
        ],
    })

def welcome(request):
    return render(request, "coreapp/welcome.html")
