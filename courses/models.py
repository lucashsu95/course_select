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


# --- NTUB 學籍目錄 ---------------------------------------------------------------
# 來源：ntubook_academic_missing_rows_restore.sql（NTUB 校方下發的學籍班級清單）
# 三層結構：學制（AcademicProgramType）→ 系所（AcademicDepartment）→ 班級（AcademicClassGroup），
# 全部掛在一次匯入批次（AcademicCatalog）底下，讓每筆資料都能回溯來源檔名與雜湊。


class AcademicCatalog(models.Model):
    """一次學籍目錄匯入批次：對應來源 SQL 的 academic_catalogs / academic_catalog_sources。"""

    version = models.CharField("版本", max_length=100, unique=True)  # 例如 ntub-20260724-755fe94f
    source_key = models.CharField("來源代碼", max_length=50, default="ntub")
    source_name = models.CharField("來源名稱", max_length=100, blank=True)
    last_successful_sync_at = models.DateTimeField("最後成功同步時間", null=True, blank=True)
    schema_version = models.PositiveSmallIntegerField("結構版本", default=1)
    source_file_name = models.CharField("來源檔名", max_length=255, blank=True)
    file_sha256 = models.CharField("來源檔雜湊", max_length=64, blank=True)
    academic_year = models.CharField("學年度", max_length=20, null=True, blank=True)
    term = models.CharField("學期", max_length=20, null=True, blank=True)
    status = models.CharField("狀態", max_length=20, default="ACTIVE")
    fetched_at = models.DateTimeField("擷取時間", null=True, blank=True)
    imported_at = models.DateTimeField("匯入時間", null=True, blank=True)
    source_row_count = models.PositiveIntegerField("來源列數", default=0)
    program_count = models.PositiveIntegerField("學制數", default=0)
    department_count = models.PositiveIntegerField("系所數", default=0)
    class_group_count = models.PositiveIntegerField("班級數", default=0)
    selectable_class_group_count = models.PositiveIntegerField("可選班級數", default=0)

    class Meta:
        ordering = ["-version"]
        verbose_name = "學籍目錄批次"

    def __str__(self):
        return self.version


class AcademicProgramType(models.Model):
    """學制：例如 碩士班 / 四技日間部 / 二年制進修部。"""

    catalog = models.ForeignKey(AcademicCatalog, on_delete=models.CASCADE,
                                 related_name="program_types", verbose_name="目錄批次")
    code = models.CharField("學制代碼", max_length=20)  # 例如 1 / 4 / S
    name_zh = models.CharField("學制名稱", max_length=100, blank=True)
    name_en = models.CharField("學制英文名稱", max_length=100, blank=True)
    is_active = models.BooleanField("有效", default=True)
    is_registration_selectable = models.BooleanField("可註冊", default=True)
    sort_order = models.PositiveIntegerField("排序", default=0)
    source_last_seen_at = models.DateTimeField("來源最後出現時間", null=True, blank=True)

    class Meta:
        ordering = ["sort_order", "code"]
        verbose_name = "學制"
        verbose_name_plural = "學制"
        constraints = [
            models.UniqueConstraint(fields=["code"], name="academic_program_type_code_unique"),
        ]

    def __str__(self):
        return f"{self.code} {self.name_zh}".strip()


class AcademicDepartment(models.Model):
    """系所：隸屬於某個學制，例如 資訊管理系（406）隸屬四技日間部。"""

    catalog = models.ForeignKey(AcademicCatalog, on_delete=models.CASCADE,
                                 related_name="departments", verbose_name="目錄批次")
    program_type = models.ForeignKey(AcademicProgramType, on_delete=models.PROTECT,
                                     related_name="departments", verbose_name="學制")
    code = models.CharField("系所代碼", max_length=20)  # 例如 406
    name_zh = models.CharField("系所名稱", max_length=100, blank=True)
    name_en = models.CharField("系所英文名稱", max_length=100, blank=True)
    is_active = models.BooleanField("有效", default=True)
    is_registration_selectable = models.BooleanField("可註冊", default=True)
    sort_order = models.PositiveIntegerField("排序", default=0)
    unit_type = models.CharField("單位類型", max_length=32, blank=True)  # 例如 ACADEMIC
    source_last_seen_at = models.DateTimeField("來源最後出現時間", null=True, blank=True)

    class Meta:
        ordering = ["program_type__sort_order", "code"]
        verbose_name = "系所"
        verbose_name_plural = "系所"
        constraints = [
            models.UniqueConstraint(fields=["code"], name="academic_department_code_unique"),
        ]

    def __str__(self):
        return f"{self.code} {self.name_zh}".strip()


class AcademicClassGroup(models.Model):
    """班級：學校開的班，學生選課時的單位，例如 40620A（四技資管二年甲班）。"""

    GROUP_TYPES = [
        ("COHORT", "一般班級"),
        ("GENERAL_EDUCATION", "通識教育"),
        ("PHYSICAL_EDUCATION", "體育"),
        ("MILITARY_EDUCATION", "軍訓"),
    ]

    catalog = models.ForeignKey(AcademicCatalog, on_delete=models.CASCADE,
                                 related_name="class_groups", verbose_name="目錄批次")
    department = models.ForeignKey(AcademicDepartment, on_delete=models.CASCADE,
                                   related_name="class_groups", verbose_name="系所")
    code = models.CharField("班級代碼", max_length=20)  # 例如 40620A
    name_zh = models.CharField("班級名稱", max_length=100, blank=True)
    grade_no = models.PositiveSmallIntegerField("年級", null=True, blank=True)
    section_code = models.CharField("班級類型", max_length=10, null=True, blank=True)  # A / B / C / D
    group_type = models.CharField("群組類型", max_length=32, choices=GROUP_TYPES, blank=True)
    is_active = models.BooleanField("有效", default=True)
    is_registration_selectable = models.BooleanField("可選", default=False)
    sort_order = models.PositiveIntegerField("排序", default=0)
    source_payload = models.JSONField("來源原始資料", default=dict, blank=True)

    class Meta:
        ordering = ["department__code", "code"]
        verbose_name = "班級"
        verbose_name_plural = "班級"
        constraints = [
            models.UniqueConstraint(fields=["code"], name="academic_class_group_code_unique"),
        ]

    def __str__(self):
        return f"{self.code} {self.name_zh}".strip()
