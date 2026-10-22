from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone


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
    enroll_open = models.DateTimeField("選課開放時間", null=True, blank=True)  # null = 不限
    enroll_close = models.DateTimeField("選課截止時間", null=True, blank=True)

    class Meta:
        ordering = ["-code"]

    def __str__(self):
        return self.code

    @classmethod
    def current(cls):
        """選課與課表都以當前學期為準；沒有標記時取最新的。"""
        return cls.objects.filter(is_current=True).first() or cls.objects.first()

    @property
    def has_window(self):
        return bool(self.enroll_open or self.enroll_close)

    @property
    def enrollment_state(self):
        """選課階段：not_open / open / closed（兩欄皆空＝永遠 open）。"""
        now = timezone.now()
        if self.enroll_open and now < self.enroll_open:
            return "not_open"
        if self.enroll_close and now > self.enroll_close:
            return "closed"
        return "open"


class Course(models.Model):
    term = models.ForeignKey(Term, on_delete=models.PROTECT, related_name="courses", verbose_name="學期")
    code = models.CharField("課號", max_length=20)
    name = models.CharField("課名", max_length=100)
    teacher = models.ForeignKey(Teacher, on_delete=models.PROTECT, verbose_name="老師")
    credits = models.PositiveSmallIntegerField("學分", default=3)
    syllabus = models.TextField("課程大綱", blank=True)
    prerequisites = models.ManyToManyField(
        "self", symmetrical=False, related_name="dependent_courses",
        blank=True, verbose_name="先修課程")  # 1–2 門，admin 表單 clean_prerequisites() 把關

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
    # 課程列表的時段篩選：以班別 start_period 為準
    PERIOD_SLOTS = [("am", "上午(1-3)"), ("midday", "中午(4-6)"), ("pm", "下午(7-9)"), ("evening", "晚上(10+)")]
    PERIOD_SLOT_RANGES = {"am": (1, 3), "midday": (4, 6), "pm": (7, 9), "evening": (10, None)}

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
        return self.enrollments.count() if annotated is None else annotated

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


class Waitlist(models.Model):
    """額滿班別的等待名單：依 queued_at 順序，退選釋出名額時自動遞補。"""

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="waitlists")
    section = models.ForeignKey(Section, on_delete=models.CASCADE, related_name="waitlists", verbose_name="班別")
    queued_at = models.DateTimeField("排隊時間", auto_now_add=True)
    promoted_at = models.DateTimeField("遞補時間", null=True, blank=True)
    promoted_seen_at = models.DateTimeField("遞補通知已讀", null=True, blank=True)

    class Meta:
        ordering = ["queued_at"]
        verbose_name = "等待名單"
        constraints = [models.UniqueConstraint(fields=["user", "section"], name="waitlist_one_per_section")]

    def __str__(self):
        return f"{self.user} 等 {self.section}"

    @property
    def position(self):
        """目前順位（從 1 起，只算還沒遞補的）。"""
        return self.section.waitlists.filter(promoted_at__isnull=True, queued_at__lt=self.queued_at).count() + 1
