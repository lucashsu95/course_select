from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models


class Teacher(models.Model):
    name = models.CharField("姓名", max_length=50)
    email = models.EmailField("信箱", blank=True)

    def __str__(self):
        return self.name


class Term(models.Model):
    code = models.CharField("學期", max_length=20, unique=True)  # 例如 114-1
    is_current = models.BooleanField("當前學期", default=False)

    class Meta:
        ordering = ["-code"]

    def __str__(self):
        return self.code

    @classmethod
    def current(cls):
        """選課與課表都以當前學期為準；沒有標記時取最新的。"""
        return cls.objects.filter(is_current=True).first() or cls.objects.first()


class Course(models.Model):
    DAYS = [(1, "週一"), (2, "週二"), (3, "週三"), (4, "週四"), (5, "週五")]

    term = models.ForeignKey(Term, on_delete=models.PROTECT, related_name="courses", verbose_name="學期")
    code = models.CharField("課號", max_length=20)
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
        constraints = [
            models.UniqueConstraint(fields=["term", "code"], name="course_code_per_term"),
            models.CheckConstraint(
                condition=models.Q(start_period__gte=1) & models.Q(end_period__gte=models.F("start_period")),
                name="course_periods_valid",
            ),
        ]

    def clean(self):
        if self.start_period and self.end_period and self.end_period < self.start_period:
            raise ValidationError({"end_period": "結束節次不可早於起始節次。"})

    def __str__(self):
        return f"{self.code} {self.name}"

    @property
    def time_display(self):
        return f"{self.get_day_display()} 第{self.start_period}-{self.end_period}節"

    @property
    def periods(self):
        return self.end_period - self.start_period + 1

    @property
    def enrolled_count(self):
        annotated = getattr(self, "enrolled", None)  # 有 annotate 就用現成的，沒有才查
        return self.enrollment_set.count() if annotated is None else annotated

    @property
    def is_full(self):
        return self.enrolled_count >= self.capacity

    def conflicts_with(self, other):
        return (self.day == other.day and self.start_period <= other.end_period
                and other.start_period <= self.end_period)


class Enrollment(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    course = models.ForeignKey(Course, on_delete=models.CASCADE)
    created = models.DateTimeField(auto_now_add=True)

    class Meta:
        # 同一門課在新學期是一筆新的 Course，所以 (user, course) 已經等於 (user, course, term)
        constraints = [models.UniqueConstraint(fields=["user", "course"], name="one_per_course")]

    def __str__(self):
        return f"{self.user} - {self.course}"
