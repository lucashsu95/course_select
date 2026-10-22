import django.db.models.deletion
from django.db import migrations, models


def assign_default_term(apps, schema_editor):
    """只回填已存在的課程；全新資料庫由 seed 建立學期。"""
    Course = apps.get_model("courses", "Course")
    if not Course.objects.exists():
        return
    Term = apps.get_model("courses", "Term")
    term = Term.objects.create(code="114-1", is_current=True)
    Course.objects.update(term=term)


class Migration(migrations.Migration):

    dependencies = [("courses", "0002_course_course_periods_valid")]

    operations = [
        migrations.CreateModel(
            name="Term",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("code", models.CharField(max_length=20, unique=True, verbose_name="學期")),
                ("is_current", models.BooleanField(default=False, verbose_name="當前學期")),
            ],
            options={"ordering": ["-code"]},
        ),
        migrations.AddField(
            model_name="course",
            name="term",
            field=models.ForeignKey(null=True, on_delete=django.db.models.deletion.PROTECT,
                                    related_name="courses", to="courses.term", verbose_name="學期"),
        ),
        migrations.RunPython(assign_default_term, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="course",
            name="term",
            field=models.ForeignKey(on_delete=django.db.models.deletion.PROTECT,
                                    related_name="courses", to="courses.term", verbose_name="學期"),
        ),
        migrations.AlterField(
            model_name="course",
            name="code",
            field=models.CharField(max_length=20, verbose_name="課號"),
        ),
        migrations.AddConstraint(
            model_name="course",
            constraint=models.UniqueConstraint(fields=("term", "code"), name="course_code_per_term"),
        ),
    ]
