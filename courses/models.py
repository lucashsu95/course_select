from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models


class Teacher(models.Model):
    name = models.CharField("姓名", max_length=50)
    email = models.EmailField("信箱", blank=True)
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
                                related_name="teacher_profile", verbose_name="登入帳號")

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
    term = models.ForeignKey(Term, on_delete=models.PROTECT, related_name="courses", verbose_name="學期")
    code = models.CharField("課號", max_length=20)
    name = models.CharField("課名", max_length=100)
    teacher = models.ForeignKey(Teacher, on_delete=models.PROTECT, verbose_name="老師")
    credits = models.PositiveSmallIntegerField("學分", default=3)
    syllabus = models.TextField("課程大綱", blank=True)

    class Meta:
        ordering = ["code"]
        constraints = [
            models.UniqueConstraint(fields=["term", "code"], name="course_code_per_term"),
        ]

    def __str__(self):
        return f"{self.code} {self.name}"


class Section(models.Model):
    """課程的一個班別：有自己的時間、教室、名額。學生加選的對象是班別，不是課程。"""

    DAYS = [(1, "週一"), (2, "週二"), (3, "週三"), (4, "週四"), (5, "週五")]

    course = models.ForeignKey(Course, on_delete=models.CASCADE, related_name="sections", verbose_name="課程")
    label = models.CharField("班別", max_length=10)  # 例如 A / B / C
    day = models.PositiveSmallIntegerField("星期", choices=DAYS)
    start_period = models.PositiveSmallIntegerField("起始節次")
    end_period = models.PositiveSmallIntegerField("結束節次")
    room = models.CharField("教室", max_length=30, blank=True)
    capacity = models.PositiveSmallIntegerField("名額", default=40)

    class Meta:
        ordering = ["course__code", "label"]
        constraints = [
            models.UniqueConstraint(fields=["course", "label"], name="section_label_per_course"),
            models.CheckConstraint(
                condition=models.Q(start_period__gte=1) & models.Q(end_period__gte=models.F("start_period")),
                name="section_periods_valid",
            ),
        ]

    def clean(self):
        if self.start_period and self.end_period and self.end_period < self.start_period:
            raise ValidationError({"end_period": "結束節次不可早於起始節次。"})

    def __str__(self):
        return f"{self.course} {self.label}班"

    @property
    def time_display(self):
        return f"{self.get_day_display()} 第{self.start_period}-{self.end_period}節"

    @property
    def periods(self):
        return self.end_period - self.start_period + 1

    @property
    def label_display(self):
        return f"{self.label} 班"

    @property
    def enrolled_count(self):
        annotated = getattr(self, "enrolled", None)  # 有 annotate 就用現成的，沒有才查
        return self.enrollment_set.count() if annotated is None else annotated

    @property
    def is_full(self):
        return self.enrolled_count >= self.capacity

    def conflicts_with(self, other):
        """兩個班別的時段是否重疊（同一天的節次範圍相交）。"""
        return (self.day == other.day and self.start_period <= other.end_period
                and other.start_period <= self.end_period)


class Enrollment(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    section = models.ForeignKey(Section, on_delete=models.CASCADE, related_name="enrollments", verbose_name="班別")
    created = models.DateTimeField(auto_now_add=True)

    class Meta:
        # 同一班別只選一次；一門課可以有幾個班別，但加選規則只允許進一班（見 services.register）
        constraints = [models.UniqueConstraint(fields=["user", "section"], name="one_per_section")]

    def __str__(self):
        return f"{self.user} - {self.section}"
