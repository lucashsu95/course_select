from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('courses', '0005_section'),
    ]

    operations = [
        migrations.AlterModelOptions(
            name='section',
            options={'ordering': ['course__code', 'label']},
        ),
    ]
