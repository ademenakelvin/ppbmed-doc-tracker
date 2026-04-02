from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("coreapp", "0011_document_department_archive_fields"),
    ]

    operations = [
        migrations.CreateModel(
            name="ITMaintenanceLog",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("category", models.CharField(max_length=80)),
                ("title", models.CharField(max_length=255)),
                ("details", models.TextField()),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("logged_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="it_maintenance_logs", to="coreapp.staff")),
            ],
            options={
                "ordering": ["-created_at"],
            },
        ),
    ]
