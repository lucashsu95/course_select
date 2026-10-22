from django.conf import settings
from django.db import models


class Teacher(models.Model):
    name = models.CharField("姓名", max_length=50)
    email = models.EmailField("信箱", blank=True)

    def __str__(self):
        return self.name


class Course(models.Model):
    DAYS = [(1, "週一"), (2, "週二"), (3, "週三"), (4, "週四"), (5, "週五")]

    code = models.CharField("課號", max_length=20, unique=True)
    name = models.CharField("課名", max_length=100)
    teacher = models.ForeignKey(Teacher, on_delete=models.PROTECT, verbose_name="老師")
    credits = models.PositiveSmallIntegerField("學分", default=3)
    day = models.PositiveSmallIntegerField("星期", choices=DAYS)
    start_period = models.PositiveSmallIntegerField("起始節次")
    end_period = models.PositiveSmallIntegerField("結束節次")
    room = models.CharField("教室", max_length=30, blank=True)
    capacity = models.PositiveSmallIntegerField("名額", default=40)
    syllabus = models.TextField("課程大綱", blank=True)

    class Meta:
        ordering = ["code"]

    def __str__(self):
        return f"{self.code} {self.name}"

    @property
    def time_display(self):
        return f"{self.get_day_display()} 第{self.start_period}-{self.end_period}節"

    @property
    def periods(self):
        return self.end_period - self.start_period + 1

    def conflicts_with(self, other):
        return (self.day == other.day and self.start_period <= other.end_period
                and other.start_period <= self.end_period)


class Enrollment(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    course = models.ForeignKey(Course, on_delete=models.CASCADE)
    created = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["user", "course"], name="one_per_course")]

    def __str__(self):
        return f"{self.user} - {self.course}"
