from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('courses', '0006_alter_section_options'),
    ]

    operations = [
        migrations.AddField(
            model_name='term',
            name='enroll_close',
            field=models.DateTimeField(blank=True, null=True, verbose_name='選課截止時間'),
        ),
        migrations.AddField(
            model_name='term',
            name='enroll_open',
            field=models.DateTimeField(blank=True, null=True, verbose_name='選課開放時間'),
        ),
    ]
