from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('coreapp', '0004_systempreference'),
    ]

    operations = [
        migrations.CreateModel(
            name='LoginHistory',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('username', models.CharField(max_length=150)),
                ('role', models.CharField(blank=True, max_length=50)),
                ('ip_address', models.CharField(blank=True, max_length=100)),
                ('user_agent', models.TextField(blank=True)),
                ('logged_in_at', models.DateTimeField(auto_now_add=True)),
                ('staff', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='login_history', to='coreapp.staff')),
            ],
            options={
                'verbose_name_plural': 'Login history',
                'ordering': ['-logged_in_at'],
            },
        ),
    ]
