from django.db import migrations, models
import django.db.models.deletion


def _backfill_sections(apps, schema_editor):
    """每門既有 Course 產生一個 A 班，時間／教室／名額原樣帶過去。"""
    Course = apps.get_model("courses", "Course")
    Section = apps.get_model("courses", "Section")
    for c in Course.objects.iterator():
        Section.objects.create(
            course=c, label="A", day=c.day, start_period=c.start_period,
            end_period=c.end_period, room=c.room, capacity=c.capacity,
        )


def _repoint_enrollments(apps, schema_editor):
    """既有加選紀錄對到該課程的 A 班。"""
    Enrollment = apps.get_model("courses", "Enrollment")
    Section = apps.get_model("courses", "Section")
    for e in Enrollment.objects.select_related("course").iterator():
        section = e.course.sections.first()
        if section:
            e.section = section
            e.save(update_fields=["section"])


class Migration(migrations.Migration):

    dependencies = [
        ("auth", "0012_alter_user_first_name_max_length"),
        ("courses", "0004_teacher_user"),
    ]

    operations = [
        # 1. 新增 Section（欄位先 nullable，讓 0001 的資料還在 Course 上時能建立）
        migrations.CreateModel(
            name="Section",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("label", models.CharField(max_length=10, verbose_name="班別")),
                ("day", models.PositiveSmallIntegerField(choices=[(1, "週一"), (2, "週二"), (3, "週三"), (4, "週四"), (5, "週五")], null=True, verbose_name="星期")),
                ("start_period", models.PositiveSmallIntegerField(null=True, verbose_name="起始節次")),
                ("end_period", models.PositiveSmallIntegerField(null=True, verbose_name="結束節次")),
                ("room", models.CharField(blank=True, max_length=30, verbose_name="教室")),
                ("capacity", models.PositiveSmallIntegerField(default=40, verbose_name="名額")),
                ("course", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="sections", to="courses.course", verbose_name="課程")),
            ],
        ),
        # 2. 舊資料 → A 班
        migrations.RunPython(_backfill_sections, migrations.RunPython.noop),
        # 3. Enrollment 加 section（暫時 nullable），舊資料對到 A 班
        migrations.AddField(
            model_name="enrollment",
            name="section",
            field=models.ForeignKey(null=True, on_delete=django.db.models.deletion.CASCADE, related_name="enrollments", to="courses.section", verbose_name="班別"),
        ),
        migrations.RunPython(_repoint_enrollments, migrations.RunPython.noop),
        # 4. 收緊：Enrollment 去掉 course、section 必填
        #    注意：RemoveConstraint 必須在 RemoveField 之前——移除欄位會連帶移除引用它的 constraint
        migrations.RemoveConstraint(model_name="enrollment", name="one_per_course"),
        migrations.RemoveField(model_name="enrollment", name="course"),
        migrations.AlterField(
            model_name="enrollment",
            name="section",
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="enrollments", to="courses.section", verbose_name="班別"),
        ),
        migrations.AddConstraint(
            model_name="enrollment",
            constraint=models.UniqueConstraint(fields=["user", "section"], name="one_per_section"),
        ),
        # 5. Section 欄位收緊 + 唯一 (course, label)
        migrations.AlterField(model_name="section", name="day", field=models.PositiveSmallIntegerField(choices=[(1, "週一"), (2, "週二"), (3, "週三"), (4, "週四"), (5, "週五")], verbose_name="星期")),
        migrations.AlterField(model_name="section", name="start_period", field=models.PositiveSmallIntegerField(verbose_name="起始節次")),
        migrations.AlterField(model_name="section", name="end_period", field=models.PositiveSmallIntegerField(verbose_name="結束節次")),
        migrations.AddConstraint(
            model_name="section",
            constraint=models.UniqueConstraint(fields=["course", "label"], name="section_label_per_course"),
        ),
        migrations.AddConstraint(
            model_name="section",
            constraint=models.CheckConstraint(condition=models.Q(("start_period__gte", 1)) & models.Q(("end_period__gte", models.F("start_period"))), name="section_periods_valid"),
        ),
        # 6. Course 去掉已移到 Section 的欄位（constraint 先刪，理由同上）
        migrations.RemoveConstraint(model_name="course", name="course_periods_valid"),
        migrations.RemoveField(model_name="course", name="day"),
        migrations.RemoveField(model_name="course", name="start_period"),
        migrations.RemoveField(model_name="course", name="end_period"),
        migrations.RemoveField(model_name="course", name="room"),
        migrations.RemoveField(model_name="course", name="capacity"),
    ]
