from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("coreapp", "0007_auditlog"),
    ]

    operations = [
        migrations.CreateModel(
            name="RolePermission",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                (
                    "role",
                    models.CharField(
                        choices=[
                            ("Director", "Director"),
                            ("Deputy Director", "Deputy Director"),
                            ("Staff", "Staff"),
                            ("Registry", "Registry"),
                            ("Admin", "Admin"),
                        ],
                        max_length=50,
                    ),
                ),
                ("permission_key", models.CharField(max_length=100)),
                ("enabled", models.BooleanField(default=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "ordering": ["role", "permission_key"],
                "unique_together": {("role", "permission_key")},
            },
        ),
    ]
