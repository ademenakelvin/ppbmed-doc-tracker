from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('coreapp', '0005_loginhistory'),
    ]

    operations = [
        migrations.AddField(
            model_name='loginhistory',
            name='event_type',
            field=models.CharField(
                choices=[('login', 'Login'), ('logout', 'Logout')],
                default='login',
                max_length=20,
            ),
        ),
    ]
