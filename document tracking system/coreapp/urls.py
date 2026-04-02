from django.urls import path
from . import views

urlpatterns = [
    path("", views.welcome, name="welcome"),
    path("dashboard/", views.dashboard, name="dashboard"),

    path("documents/", views.documents, name="documents"),
    path("documents/add/", views.add_document, name="add_document"),
    path("documents/extract-scan/", views.extract_document_scan, name="extract_document_scan"),
    path("documents/<int:pk>/attachment/", views.download_document_attachment, name="download_document_attachment"),
    path("documents/<int:pk>/", views.document_detail, name="document_detail"),
    path("documents/<int:pk>/edit/", views.edit_document, name="edit_document"),
    path("documents/<int:pk>/delete/", views.delete_document, name="delete_document"),
    path("documents/<int:pk>/restore/", views.restore_document, name="restore_document"),
    path("documents/<int:pk>/route/", views.route_document, name="route_document"),
    path("documents/<int:pk>/export-pdf/", views.export_document_history_pdf, name="export_document_history_pdf"),
    path("documents/export/csv/", views.export_documents_csv, name="export_documents_csv"),

    path("messages/", views.messages_page, name="messages"),
    path("messages/<int:pk>/attachment/", views.download_message_attachment, name="download_message_attachment"),
    path("messages/chat/<int:staff_pk>/send/", views.send_chat_message, name="send_chat_message"),
    path("messages/<int:pk>/reply/", views.reply_message, name="reply_message"),
    path("messages/<int:pk>/read/", views.mark_message_read, name="mark_message_read"),

    path("incoming/", views.incoming, name="incoming"),
    path("outgoing/", views.outgoing, name="outgoing"),
    path("tracking/", views.tracking, name="tracking"),
    path("tracking/<int:pk>/attachment/", views.download_routing_attachment, name="download_routing_attachment"),

    path("reports/", views.reports_analytics, name="reports"),
    path("reports/export/csv/", views.export_reports_csv, name="export_reports_csv"),
    path("login-history/", views.login_history, name="login_history"),
    path("login-history/export/logins/", views.export_login_history_csv, name="export_login_history_csv"),
    path("login-history/export/audit/", views.export_audit_logs_csv, name="export_audit_logs_csv"),
    path("role-permissions/", views.role_permissions, name="role_permissions"),
    path("security-checklist/", views.security_checklist, name="security_checklist"),
    path("security-test-email/", views.send_test_email, name="send_test_email"),
    path("backups/", views.backup_restore_center, name="backup_restore_center"),
    path("it-admin/", views.it_admin_center, name="it_admin_center"),

    path("staff/", views.staff, name="staff"),
    path("staff/add/", views.add_staff, name="add_staff"),
    path("staff/<int:pk>/edit/", views.edit_staff, name="edit_staff"),
    path("staff/<int:pk>/delete/", views.delete_staff, name="delete_staff"),
    path("staff/<int:pk>/restore/", views.restore_staff, name="restore_staff"),

    path("notifications/", views.notifications_page, name="notifications"),
    path("notifications/<int:pk>/open/", views.open_notification, name="open_notification"),
    path("notifications/<int:pk>/read/", views.mark_notification_read, name="mark_notification_read"),
    path("notifications/read-all/", views.mark_all_notifications_read, name="mark_all_notifications_read"),

    path("settings/", views.settings_page, name="settings"),

    
]
