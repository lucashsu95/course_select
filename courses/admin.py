from django import forms
from django.contrib import admin, messages
from django.contrib.auth.models import Group, User
from django.contrib.sites.models import Site
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models import Prefetch, Q
from django.http import HttpResponseRedirect
from django.template.response import TemplateResponse
from django.urls import path, reverse
from django.utils import timezone
from django.utils.html import format_html

from allauth.account.models import EmailAddress
from allauth.socialaccount.models import SocialAccount, SocialApp, SocialToken

from .maintainer import (can_manage_policy, can_manage_section, grant_maintainer_access,
                          is_maintainer, is_superuser, revoke_maintainer_access,
                          scoped_class_groups, scoped_courses, scoped_departments,
                          scoped_sections)
from .maintainer_assignment_forms import (BulkClassAssignmentForm,
                                          BulkClassAssignmentSelectForm)
from .models import (AcademicCatalog, AcademicClassGroup, AcademicDepartment,
                     AcademicProgramType, Course, CourseMaintainerScope, Enrollment,
                     NtubCurriculumRecommendation, NtubOfferingAmbiguity,
                     NtubOfferingSource, NtubRecommendationCandidate,
                     NtubTimetableEntry, NtubTimetableSnapshot, Section,
                     SectionClassPolicy, StudentAcademicProfile, Teacher, Term, Waitlist)


class CourseAdminForm(forms.ModelForm):
    class Meta:
        model = Course
        fields = "__all__"

    def clean_prerequisites(self):
        # 只能在表單驗證：full_clean() 跑在 save_m2m() 之前，model 層讀不到表單送出的 M2M
        qs = self.cleaned_data["prerequisites"]
        if qs.count() > 2:
            raise forms.ValidationError("先修課程最多設 2 門。")
        return qs


class MaintainerScopedAdmin(admin.ModelAdmin):
    """課程維護員在後台只看得到自己負責系所的資料。

    這是伺服器端的第一道過濾：changelist、搜尋、autocomplete、ForeignKey
    下拉選單全部從這裡的 queryset 出去，所以維護員連「猜 id」都猜不到別系的
    資料。各個 ModelAdmin 只需實作 `scope_queryset`。
    """

    def scope_queryset(self, request, queryset):
        """回傳這個使用者看得到的資料子集（superuser 走原 queryset）。"""
        return queryset

    def get_queryset(self, request):
        queryset = super().get_queryset(request)
        if is_superuser(request.user):
            return queryset
        return self.scope_queryset(request, queryset)


class SuperuserOnlyAdmin(admin.ModelAdmin):
    """只有 superuser 能動的介面（選課、候補、學生學籍）。

    維護員群組本來就沒有這些模型權限，這裡再釘死一次：就算日後有人手動加權限，
    維護員也不會碰到學生的選課與學籍資料。
    """

    def has_view_permission(self, request, obj=None):
        return is_superuser(request.user)

    def has_add_permission(self, request):
        return is_superuser(request.user)

    def has_change_permission(self, request, obj=None):
        return is_superuser(request.user)

    def has_delete_permission(self, request, obj=None):
        return is_superuser(request.user)


@admin.register(Term)
class TermAdmin(admin.ModelAdmin):
    list_display = ["code", "is_current", "enroll_open", "enroll_close"]
    list_filter = ["is_current"]
    date_hierarchy = "enroll_open"
    fields = ["code", "is_current", "enroll_open", "enroll_close"]


@admin.register(Teacher)
class TeacherAdmin(admin.ModelAdmin):
    list_display = ["name", "email", "user"]
    search_fields = ["name"]
    autocomplete_fields = ["user"]


@admin.register(Course)
class CourseAdmin(MaintainerScopedAdmin):
    form = CourseAdminForm
    list_display = ["code", "name", "term", "teacher", "credits"]
    list_filter = ["term", "teacher"]
    search_fields = ["code", "name"]

    def scope_queryset(self, request, queryset):
        return queryset.filter(pk__in=scoped_courses(request.user).values("pk"))


@admin.register(Section)
class SectionAdmin(MaintainerScopedAdmin):
    list_display = ["label", "course", "day", "start_period", "end_period", "room", "capacity"]
    list_filter = ["course__term", "day"]
    search_fields = ["course__code", "course__name"]

    def scope_queryset(self, request, queryset):
        return queryset.filter(pk__in=scoped_sections(request.user).values("pk"))


@admin.register(Enrollment)
class EnrollmentAdmin(SuperuserOnlyAdmin):
    list_display = ["user", "section", "created"]
    list_filter = ["section__course__term"]
    list_select_related = ["user", "section", "section__course"]


@admin.register(Waitlist)
class WaitlistAdmin(SuperuserOnlyAdmin):
    list_display = ["user", "section", "queued_at", "promoted_at"]
    list_filter = ["section__course__term"]
    list_select_related = ["user", "section", "section__course"]


@admin.register(AcademicCatalog)
class AcademicCatalogAdmin(admin.ModelAdmin):
    list_display = ["version", "source_key", "status", "source_file_name",
                    "class_group_count", "selectable_class_group_count", "imported_at"]
    list_filter = ["source_key", "status"]
    search_fields = ["version", "source_file_name", "file_sha256"]
    date_hierarchy = "imported_at"
    readonly_fields = ["source_file_name", "file_sha256", "source_row_count",
                       "program_count", "department_count", "class_group_count",
                       "selectable_class_group_count"]


@admin.register(AcademicProgramType)
class AcademicProgramTypeAdmin(admin.ModelAdmin):
    list_display = ["code", "name_zh", "catalog", "is_registration_selectable", "is_active", "sort_order"]
    list_filter = ["catalog", "is_registration_selectable", "is_active"]
    search_fields = ["code", "name_zh"]
    autocomplete_fields = ["catalog"]


@admin.register(AcademicDepartment)
class AcademicDepartmentAdmin(MaintainerScopedAdmin):
    list_display = ["code", "name_zh", "program_type", "catalog", "is_registration_selectable", "is_active"]
    list_filter = ["catalog", "program_type", "is_registration_selectable", "is_active"]
    search_fields = ["code", "name_zh"]
    autocomplete_fields = ["catalog", "program_type"]

    def scope_queryset(self, request, queryset):
        return queryset.filter(pk__in=scoped_departments(request.user).values("pk"))


@admin.register(StudentAcademicProfile)
class StudentAcademicProfileAdmin(SuperuserOnlyAdmin):
    list_display = ["user", "class_group", "department", "program_type", "grade_no", "completed_at"]
    list_filter = ["class_group__department__program_type", "class_group__grade_no"]
    search_fields = ["user__email", "user__username", "class_group__code", "class_group__name_zh"]
    list_select_related = ["class_group__department__program_type", "user"]
    autocomplete_fields = ["user"]

    @admin.display(description="系所", ordering="class_group__department__name_zh")
    def department(self, obj):
        return obj.class_group.department

    @admin.display(description="學制", ordering="class_group__department__program_type__sort_order")
    def program_type(self, obj):
        return obj.class_group.department.program_type

    @admin.display(description="年級", ordering="class_group__grade_no")
    def grade_no(self, obj):
        return obj.class_group.grade_no


@admin.register(AcademicClassGroup)
class AcademicClassGroupAdmin(MaintainerScopedAdmin):
    list_display = ["code", "name_zh", "department", "grade_no", "section_code",
                    "group_type", "is_registration_selectable", "is_active"]
    list_filter = ["catalog", "department__program_type", "group_type",
                   "is_registration_selectable", "is_active", "grade_no"]
    search_fields = ["code", "name_zh", "department__code", "department__name_zh"]
    autocomplete_fields = ["catalog", "department"]

    def scope_queryset(self, request, queryset):
        return queryset.filter(pk__in=scoped_class_groups(request.user).values("pk"))


class ReadOnlyTimetableAdmin(admin.ModelAdmin):
    """官方班級課表只能由匯入指令寫入，管理介面一律唯讀。"""

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


class ScopedReadOnlyAdmin(ReadOnlyTimetableAdmin, MaintainerScopedAdmin):
    """官方來源資料：唯讀，而且只看得到自己系所的部分。"""

    def scope_queryset(self, request, queryset):
        return queryset


@admin.register(NtubTimetableSnapshot)
class NtubTimetableSnapshotAdmin(ScopedReadOnlyAdmin):
    list_display = ["term", "class_group", "class_name", "source_url",
                    "retrieved_at", "entry_count"]
    list_filter = ["term", "class_group__department__program_type"]
    search_fields = ["class_group__code", "class_group__name_zh", "class_name"]
    list_select_related = ["class_group", "term"]
    date_hierarchy = "retrieved_at"

    def scope_queryset(self, request, queryset):
        return queryset.filter(class_group__in=scoped_class_groups(request.user))

    @admin.display(description="節數")
    def entry_count(self, obj):
        return obj.entries.count()


@admin.register(NtubTimetableEntry)
class NtubTimetableEntryAdmin(ScopedReadOnlyAdmin):
    list_display = ["snapshot", "entry_type", "weekday", "start_period", "end_period",
                    "course_code", "official_serial", "course_name", "teacher_name",
                    "classroom"]
    list_filter = ["entry_type", "weekday", "snapshot__term"]
    search_fields = ["course_code", "course_name", "teacher_name", "classroom",
                     "snapshot__class_group__code"]
    list_select_related = ["snapshot", "snapshot__class_group", "snapshot__term"]

    def scope_queryset(self, request, queryset):
        return queryset.filter(snapshot__class_group__in=scoped_class_groups(request.user))


@admin.register(NtubOfferingSource)
class NtubOfferingSourceAdmin(ScopedReadOnlyAdmin):
    """官方開課來源：只能由匯入指令寫入，管理介面一律唯讀。"""

    list_display = ["source_key", "course_code", "course_name", "class_group",
                    "official_serial", "teacher_name", "day_label", "time_range",
                    "classroom_code", "official_capacity", "official_enrolled",
                    "local_enrolled", "term"]
    list_filter = ["term", "class_group__department__program_type", "elective_category"]
    search_fields = ["source_key", "course_code", "course_name", "teacher_name",
                     "class_group__code", "classroom_code", "classroom_name"]
    list_select_related = ["term", "class_group", "course", "section", "teacher"]
    date_hierarchy = "retrieved_at"

    def scope_queryset(self, request, queryset):
        return queryset.filter(class_group__in=scoped_class_groups(request.user))

    @admin.display(description="星期", ordering="applied_day")
    def day_label(self, obj):
        labels = {1: "週一", 2: "週二", 3: "週三", 4: "週四",
                  5: "週五", 6: "週六", 7: "週日"}
        return labels.get(obj.applied_day, "")

    @admin.display(description="節次")
    def time_range(self, obj):
        if not obj.applied_start_period:
            return ""
        return f"{obj.applied_start_period}-{obj.applied_end_period}"

    @admin.display(description="本地加選人數")
    def local_enrolled(self, obj):
        return obj.section.enrollments.count()


@admin.register(NtubCurriculumRecommendation)
class NtubCurriculumRecommendationAdmin(ScopedReadOnlyAdmin):
    """課綱推薦：來源資料只能由匯入指令寫入，管理介面一律唯讀。

    `course_name_only` 的推薦在這裡只是「疑義」，不會因為有人在這裡看過
    就變成開放加選；真正開放要走 SectionClassPolicy。
    """

    list_display = ["admission_year", "track", "class_code", "course_name",
                    "match_status", "matched_offering_class_code", "is_ambiguous",
                    "offering"]
    list_filter = ["match_status", "is_ambiguous", "track", "admission_year"]
    search_fields = ["class_code", "course_name", "matched_offering_class_code",
                     "matched_course_code"]
    list_select_related = ["offering", "course", "class_group"]

    def scope_queryset(self, request, queryset):
        return queryset.filter(
            Q(class_group__in=scoped_class_groups(request.user))
            | Q(department_code__in=scoped_departments(request.user).values("code"))
        )

    @admin.display(description="候選開課")
    def candidate_count(self, obj):
        return obj.candidates.count()


@admin.register(NtubRecommendationCandidate)
class NtubRecommendationCandidateAdmin(ScopedReadOnlyAdmin):
    list_display = ["recommendation", "offering_key", "course_code", "class_code",
                    "course_name", "offering"]
    search_fields = ["offering_key", "course_code", "class_code", "course_name"]
    list_select_related = ["recommendation", "offering"]

    def scope_queryset(self, request, queryset):
        return queryset.filter(
            Q(offering__class_group__in=scoped_class_groups(request.user))
            | Q(recommendation__class_group__in=scoped_class_groups(request.user))
        )


@admin.register(NtubOfferingAmbiguity)
class NtubOfferingAmbiguityAdmin(ScopedReadOnlyAdmin):
    list_display = ["kind", "message", "offering", "recommendation"]
    list_filter = ["kind"]
    search_fields = ["message"]
    list_select_related = ["offering", "recommendation"]

    def scope_queryset(self, request, queryset):
        return queryset.filter(
            Q(offering__class_group__in=scoped_class_groups(request.user))
            | Q(recommendation__class_group__in=scoped_class_groups(request.user))
        )


def restrict_to_superuser(*models):
    """把已註冊的 ModelAdmin 限制成只有 superuser 能動（保留原本的欄位設定）。

    用在 OAuth 設定（allauth）、使用者與群組權限（auth）、站台設定（sites）這幾個
    介面上：維護員本來就沒有這些模型權限，這裡再釘死一次，避免日後有人手動加權限
    就讓維護員碰到 OAuth／帳號權限／系統設定。
    """
    for model in models:
        existing = admin.site._registry.get(model)
        if existing is None:
            continue
        admin.site.unregister(model)
        admin.site.register(
            model,
            type(f"SuperuserOnly{type(existing).__name__}",
                 (type(existing), SuperuserOnlyAdmin), {}),
        )


restrict_to_superuser(
    User, Group, EmailAddress, SocialAccount, SocialApp, SocialToken, Site,
)


class PolicyTermFilter(admin.SimpleListFilter):
    """依「學期」篩選修課政策。

    學期是從 section → course → term 推導出來的，模型上沒有可直接篩選的欄位，
    所以自己寫一支 SimpleListFilter。選項只列出 **目前使用者看得到的政策**
    所涉及的學期（走 ModelAdmin.get_queryset()），維護員不會從篩選清單看到
    別系政策的存在。
    """

    title = "學期"
    parameter_name = "policy_term"

    def lookups(self, request, model_admin):
        queryset = model_admin.get_queryset(request).prefetch_related(None)
        codes = (queryset.order_by()
                 .values_list("section__course__term__code", flat=True)
                 .distinct())
        return [(code, code) for code in codes if code]

    def queryset(self, request, queryset):
        value = self.value()
        if not value:
            return queryset
        return queryset.filter(section__course__term__code=value)


class ApplicableClassGroupFilter(admin.SimpleListFilter):
    """依「適用學生班級」篩選修課政策。

    選項只列出 **目前使用者看得到的政策** 所涉及的班級：篩選器本身走的是
    ModelAdmin.get_queryset()，所以 Course Maintainer 只會看到自己授權系所的
    班級，不會因為篩選清單就看到別系的班級。

    篩選用班級代碼（class_group__code）而不是主鍵：代碼是維護員在課表上
    認得的東西，而且同一個班級代碼在不同匯入批次可能對到不同主鍵。
    """

    title = "適用學生班級"
    parameter_name = "policy_class_group"

    def lookups(self, request, model_admin):
        # prefetch_related(None)：values_list 不需要預載，而且 Django 不允許
        # 對 values() 結果做 prefetch。
        queryset = model_admin.get_queryset(request).prefetch_related(None)
        pairs = (queryset.order_by()
                 .values_list("class_group__code", "class_group__name_zh")
                 .distinct())
        return [(code, f"{code} {name}".strip())
                for code, name in pairs if code]

    def queryset(self, request, queryset):
        value = self.value()
        if not value:
            return queryset
        return queryset.filter(class_group__code=value)


@admin.register(SectionClassPolicy)
class SectionClassPolicyAdmin(admin.ModelAdmin):
    """跨班修課政策：這個開課班別對哪個學生班級是什麼屬性、能不能自行加選。

    「管理員必須先指定適用班級」：政策一定要綁一個 AcademicClassGroup，
    不存在只靠課名自動開放的路徑。

    權限全部在伺服器端檢查，任何一層單獨失效都不會失守：

    1. changelist / 搜尋 → 只列出授權系所的政策（get_queryset）。
    2. ForeignKey 下拉與 autocomplete → 只給授權系所的班別與相關班別
       （formfield_for_foreignkey，autocomplete 走相關 ModelAdmin 的 get_queryset）。
    3. 物件層級檢查 → 別系的政策連編輯頁都開不了（has_change_permission）。
    4. 儲存時再檢查一次 → 即使偽造 POST 送出別系的班別，也會被擋下來
       （save_model），而且不會寫入任何資料。
    """

    # --- 清單欄位 -----------------------------------------------------------
    # 欄位順序對應維護員的判讀順序：這是誰的課、哪一門課、什麼屬性、有沒有開放。
    list_display = [
        "term_display",
        "applicable_class_group_display",
        "course_code_display",
        "course_name_display",
        "source_class_group_display",
        "course_category_display",
        "can_enroll_display",
        "status_display",
        "confirmed_by_display",
        "confirmed_at_display",
    ]
    # 點課號進到該筆政策的編輯頁（學期欄只是說明用的文字，不做成連結）。
    list_display_links = ("course_code_display",)
    # 篩選：學期 / 適用班級 / 發布狀態，加上維護員原本就在用的分類與加選旗標。
    list_filter = [
        "section__course__term",
        ApplicableClassGroupFilter,
        "status",
        "course_category",
        "can_enroll",
    ]
    # 搜尋：課號、課名、班級代碼。
    search_fields = ["section__course__code", "section__course__name",
                     "class_group__code", "class_group__name_zh"]
    list_select_related = ["section__course__term", "class_group__department", "confirmed_by"]
    list_per_page = 50
    # 排序：最新的學期優先，然後課號、班別、班級代碼。
    ordering = ["-section__course__term__code", "section__course__code",
                "section__label", "class_group__code"]
    autocomplete_fields = ["section", "class_group"]
    fields = ["section", "class_group", "course_category", "can_enroll", "status",
              "notes", "confirmed_by", "confirmed_at"]
    # 確認帳號與時間由系統寫入，表單裡不可編輯（避免偽造稽核紀錄）
    readonly_fields = ["confirmed_by", "confirmed_at"]
    actions = ["publish_selected_policies", "withdraw_selected_policies"]
    # 批次安排入口的連結放在名單頁的 object-tools 區塊（見下方模板）。
    change_list_template = "admin/courses/sectionclasspolicy_change_list.html"

    # --- 清單欄位的顯示邏輯 -------------------------------------------------

    @admin.display(description="學期", ordering="section__course__term__code")
    def term_display(self, obj):
        """學期來自 section → course → term，不另外存一份。"""
        return obj.section.course.term.code

    @admin.display(description="適用學生班級", ordering="class_group__code")
    def applicable_class_group_display(self, obj):
        """適用的學生班級：班級代碼 + 班級名稱。"""
        group = obj.class_group
        name = group.name_zh or ""
        return f"{group.code} {name}".strip()

    @admin.display(description="課號", ordering="section__course__code")
    def course_code_display(self, obj):
        return obj.section.course.code

    @admin.display(description="課名", ordering="section__course__name")
    def course_name_display(self, obj):
        return obj.section.course.name

    @admin.display(description="來源開課班級")
    def source_class_group_display(self, obj):
        """官方來源對應到的開課班級代碼（沒有官方來源時顯示「—」）。

        同一個 Section 可能對應到多筆官方來源（不同來源鍵），所以把代碼
        去重後用「、」串起來；沒有資料時不顯示空白，讓維護員一眼看出
        「這筆政策沒有官方來源」。
        """
        codes = sorted({source.class_group.code
                        for source in obj.section.ntub_offering_sources.all()
                        if source.class_group_id})
        if not codes:
            return "—"
        return "、".join(codes)

    @admin.display(description="修課分類", ordering="course_category")
    def course_category_display(self, obj):
        return obj.get_course_category_display()

    @admin.display(description="可否自行加選", ordering="can_enroll")
    def can_enroll_display(self, obj):
        """以顏色區分是否可自行加選。"""
        if obj.can_enroll:
            return format_html(
                '<span style="color:#1a7f37;font-weight:600;">{}</span>',
                "可自行加選",
            )
        return format_html(
            '<span style="color:#6c757d;font-weight:600;">{}</span>',
            "不可自行加選",
        )

    @admin.display(description="發布狀態", ordering="status")
    def status_display(self, obj):
        """以標籤區分已發布與草稿。"""
        if obj.status == SectionClassPolicy.Status.PUBLISHED:
            return format_html(
                '<span style="color:#1a7f37;font-weight:700;'
                'background:#e3f3e6;padding:1px 8px;border-radius:10px;">'
                '{}</span>',
                "已發布",
            )
        return format_html(
            '<span style="color:#6c757d;font-weight:600;'
            'background:#f1f1f1;padding:1px 8px;border-radius:10px;">'
            '{}</span>',
            "草稿",
        )

    @admin.display(description="確認人", ordering="confirmed_by__username")
    def confirmed_by_display(self, obj):
        """誰確認了這筆政策（沒確認過就是「—」）。"""
        user = obj.confirmed_by
        if user is None:
            return "—"
        return user.email or user.get_username()

    @admin.display(description="確認時間", ordering="confirmed_at")
    def confirmed_at_display(self, obj):
        """確認時間（台北時區；沒有確認過就是「—」）。"""
        if obj.confirmed_at is None:
            return "—"
        return timezone.localtime(obj.confirmed_at).strftime("%Y-%m-%d %H:%M")

    def get_urls(self):
        """額外掛一個「批次安排班級課程」的獨立頁面。

        自訂網址放在 `super().get_urls()` **前面**：Django 內建的
        `<path:object_id>/` 會吃掉任何第一層路徑，必須先比對才不會把
        「bulk-assign/」當成物件 id。

        這條網頁用 `admin_site.admin_view()` 包住：未登入／非 staff 會被導到
        登入頁（沿用 Django Admin 自己的登入、CSRF 與權限機制）。
        """
        custom = [
            path("bulk-assign/",
                 self.admin_site.admin_view(self.bulk_assign_view),
                 name="courses_sectionclasspolicy_bulk_assign"),
        ]
        return custom + super().get_urls()

    # --- 批次安排班級課程 ----------------------------------------------------

    def _bulk_assign_permission(self, request):
        """批次功能的伺服器端權限檢查。

        三層：必須是課程維護員（群組）、必須有有效的授權系所範圍、
        必須有新增修課政策的模型權限。任何一層不過就 403。
        """
        user = request.user
        if not is_maintainer(user):
            raise PermissionDenied("只有課程維護員可以使用批次安排功能。")
        if not user.has_perm("courses.add_sectionclasspolicy"):
            raise PermissionDenied("你沒有新增修課政策的權限。")
        if not is_superuser(user) and not scoped_departments(user).exists():
            raise PermissionDenied("你尚未被授權任何系所，無法批次安排課程。")

    def bulk_assign_view(self, request):
        """批次安排班級課程。

        流程：GET 選學期 + 學生班級 → 勾選多門來源開課 + 選修課分類 →
        POST 後批次建立 DRAFT 政策（已存在的不覆寫，只回報略過筆數）。
        """
        self._bulk_assign_permission(request)
        user = request.user

        context = {
            **self.admin_site.each_context(request),
            "title": "批次安排班級課程",
            "opts": self.model._meta,
            "media": self.media,
            "changelist_url": reverse("admin:courses_sectionclasspolicy_changelist"),
        }

        # 第一步的表單：有帶參數才綁定，避免初次開頁面就顯示「必填」錯誤。
        select_data = request.GET if (request.method == "GET" and request.GET) else None
        select_form = BulkClassAssignmentSelectForm(select_data, user=user)
        bulk_form = None
        selected_term = request.POST.get("term") if request.method == "POST" else None
        selected_class_group = (request.POST.get("class_group")
                                if request.method == "POST" else None)

        if request.method == "POST":
            # 先用 POST 裡的學期收斂來源班別範圍，欄位驗證仍會再檢查一次。
            term = Term.objects.filter(pk=request.POST.get("term")).first()
            bulk_form = BulkClassAssignmentForm(request.POST, user=user, term=term)
            if bulk_form.is_valid():
                created, skipped = self._create_bulk_policies(bulk_form)
                self.message_user(
                    request,
                    f"批次安排完成：建立 {created} 筆草稿政策；已存在而略過 {skipped} 筆。")
                return HttpResponseRedirect(
                    reverse("admin:courses_sectionclasspolicy_changelist"))
        elif select_form.is_valid():
            term = select_form.cleaned_data["term"]
            class_group = select_form.cleaned_data["class_group"]
            selected_term = term.pk
            selected_class_group = class_group.pk
            bulk_form = BulkClassAssignmentForm(
                user=user, term=term,
                initial={"term": term.pk, "class_group": class_group.pk})

        context["select_form"] = select_form
        context["bulk_form"] = bulk_form
        context["selected_term"] = selected_term
        context["selected_class_group"] = selected_class_group
        return TemplateResponse(request, "admin/courses/bulk_class_assignment.html", context)

    def _create_bulk_policies(self, form):
        """批次建立政策：全部在單一 transaction 裡，已存在的不覆寫。

        已存在的政策（同一 section + class_group）會被安全略過：既有的
        修課分類、發布狀態、確認者都不會被改動，只回報略過筆數。
        """
        class_group = form.cleaned_data["class_group"]
        category = form.cleaned_data["course_category"]
        can_enroll = form.cleaned_data["can_enroll"]
        sections = form.cleaned_data["sections"]

        created = 0
        skipped = 0
        with transaction.atomic():
            for section in sections:
                _, was_created = SectionClassPolicy.objects.get_or_create(
                    section=section,
                    class_group=class_group,
                    defaults={
                        "course_category": category,
                        "can_enroll": can_enroll,
                        "status": SectionClassPolicy.Status.DRAFT,
                        "notes": "批次安排班級課程建立",
                    },
                )
                if was_created:
                    created += 1
                else:
                    skipped += 1
        return created, skipped

    def get_queryset(self, request):
        queryset = super().get_queryset(request)
        if is_superuser(request.user):
            return queryset.prefetch_related(
                Prefetch("section__ntub_offering_sources",
                         queryset=NtubOfferingSource.objects.select_related("class_group")))
        # 政策屬於「適用班級」那個系所：跨班政策由學生端的系所負責維護。
        return queryset.filter(
            class_group__department__in=scoped_departments(request.user)
        ).prefetch_related(
            Prefetch("section__ntub_offering_sources",
                     queryset=NtubOfferingSource.objects.select_related("class_group")))

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        # 下拉選單（與 autocomplete）只給授權系所的資料：偽造 POST 也選不到別系的班級。
        if db_field.name == "class_group":
            kwargs["queryset"] = scoped_class_groups(request.user)
        elif db_field.name == "section":
            kwargs["queryset"] = scoped_sections(request.user)
        return super().formfield_for_foreignkey(db_field, request, **kwargs)

    def has_view_permission(self, request, obj=None):
        if not super().has_view_permission(request, obj):
            return False
        if obj is None or is_superuser(request.user):
            return True
        return can_manage_policy(request.user, obj)

    def has_change_permission(self, request, obj=None):
        if not super().has_change_permission(request, obj):
            return False
        if obj is None or is_superuser(request.user):
            return True
        return can_manage_policy(request.user, obj)

    def has_delete_permission(self, request, obj=None):
        if not super().has_delete_permission(request, obj):
            return False
        if obj is None or is_superuser(request.user):
            return True
        return can_manage_policy(request.user, obj)

    def save_model(self, request, obj, form, change):
        user = request.user
        if not is_superuser(user):
            # 伺服器端最後一道：適用班級必須在授權系所底下，開課班別必須跟自己的系所相關。
            if not scoped_departments(user).filter(pk=obj.class_group.department_id).exists():
                raise PermissionDenied("你只能管理授權系所的班級修課政策。")
            if not can_manage_section(user, obj.section):
                raise PermissionDenied("你只能管理自己系所相關的開課班別。")
        if obj.status == SectionClassPolicy.Status.PUBLISHED:
            previous = None
            if change:
                previous = (SectionClassPolicy.objects.filter(pk=obj.pk)
                            .values_list("status", flat=True).first())
            if previous != obj.status or obj.confirmed_by_id is None:
                # 發布＝維護員確認：記下是誰、何時確認的。
                obj.confirmed_by = user
                obj.confirmed_at = timezone.now()
        super().save_model(request, obj, form, change)

    @admin.action(description="發布選定的修課政策（記錄確認帳號與時間）")
    def publish_selected_policies(self, request, queryset):
        published = 0
        for policy in queryset:
            if not (is_superuser(request.user) or can_manage_policy(request.user, policy)):
                continue
            policy.status = SectionClassPolicy.Status.PUBLISHED
            policy.confirmed_by = request.user
            policy.confirmed_at = timezone.now()
            policy.save(update_fields=["status", "confirmed_by", "confirmed_at", "updated_at"])
            published += 1
        self.message_user(request, f"已發布 {published} 筆修課政策。")

    @admin.action(description="撤回選定的修課政策（回到草稿，不開放加選）")
    def withdraw_selected_policies(self, request, queryset):
        withdrawn = 0
        for policy in queryset:
            if not (is_superuser(request.user) or can_manage_policy(request.user, policy)):
                continue
            policy.status = SectionClassPolicy.Status.DRAFT
            policy.save(update_fields=["status", "updated_at"])
            withdrawn += 1
        self.message_user(request, f"已撤回 {withdrawn} 筆修課政策。")


@admin.register(CourseMaintainerScope)
class CourseMaintainerScopeAdmin(admin.ModelAdmin):
    """維護員權限範圍：只有 superuser 能新增、修改、刪除。

    一般維護員連這個頁面都開不了（不是把欄位藏起來而已），所以維護員
    無法自己擴大權限、也無法把自己升成 superuser。
    """

    list_display = ["user", "department", "is_active", "updated_at"]
    list_filter = ["is_active", "department"]
    search_fields = ["user__email", "user__username", "department__code", "department__name_zh"]
    autocomplete_fields = ["user", "department"]
    actions = ["grant_selected_scopes", "revoke_selected_scopes"]

    def has_module_permission(self, request):
        return is_superuser(request.user)

    def has_view_permission(self, request, obj=None):
        return is_superuser(request.user)

    def has_add_permission(self, request):
        return is_superuser(request.user)

    def has_change_permission(self, request, obj=None):
        return is_superuser(request.user)

    def has_delete_permission(self, request, obj=None):
        return is_superuser(request.user)

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        # 授權的當下就把帳號放進維護員群組並開啟 staff，維護員才能進 /admin/。
        if obj.is_active:
            grant_maintainer_access(obj.user)
        else:
            revoke_maintainer_access(obj.user)

    def delete_model(self, request, obj):
        user = obj.user
        super().delete_model(request, obj)
        revoke_maintainer_access(user)

    @admin.action(description="啟用選定的權限範圍（並同步維護員權限）")
    def grant_selected_scopes(self, request, queryset):
        granted = 0
        for scope in queryset:
            scope.is_active = True
            scope.save(update_fields=["is_active", "updated_at"])
            grant_maintainer_access(scope.user)
            granted += 1
        self.message_user(request, f"已啟用 {granted} 筆維護員權限範圍。")

    @admin.action(description="停用選定的權限範圍（並收回維護員權限）")
    def revoke_selected_scopes(self, request, queryset):
        revoked = 0
        for scope in queryset:
            scope.is_active = False
            scope.save(update_fields=["is_active", "updated_at"])
            revoke_maintainer_access(scope.user)
            revoked += 1
        self.message_user(request, f"已停用 {revoked} 筆維護員權限範圍。")
