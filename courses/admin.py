from django import forms
from django.contrib import admin
from .models import (AcademicCatalog, AcademicClassGroup, AcademicDepartment,
                     AcademicProgramType, Course, Enrollment, Section, Teacher,
                     Term, Waitlist)


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
class CourseAdmin(admin.ModelAdmin):
    form = CourseAdminForm
    list_display = ["code", "name", "term", "teacher", "credits"]
    list_filter = ["term", "teacher"]
    search_fields = ["code", "name"]


@admin.register(Section)
class SectionAdmin(admin.ModelAdmin):
    list_display = ["label", "course", "day", "start_period", "end_period", "room", "capacity"]
    list_filter = ["course__term", "day"]
    search_fields = ["course__code", "course__name"]


@admin.register(Enrollment)
class EnrollmentAdmin(admin.ModelAdmin):
    list_display = ["user", "section", "created"]
    list_filter = ["section__course__term"]
    list_select_related = ["user", "section", "section__course"]


@admin.register(Waitlist)
class WaitlistAdmin(admin.ModelAdmin):
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
class AcademicDepartmentAdmin(admin.ModelAdmin):
    list_display = ["code", "name_zh", "program_type", "catalog", "is_registration_selectable", "is_active"]
    list_filter = ["catalog", "program_type", "is_registration_selectable", "is_active"]
    search_fields = ["code", "name_zh"]
    autocomplete_fields = ["catalog", "program_type"]


@admin.register(AcademicClassGroup)
class AcademicClassGroupAdmin(admin.ModelAdmin):
    list_display = ["code", "name_zh", "department", "grade_no", "section_code",
                    "group_type", "is_registration_selectable", "is_active"]
    list_filter = ["catalog", "department__program_type", "group_type",
                   "is_registration_selectable", "is_active", "grade_no"]
    search_fields = ["code", "name_zh", "department__code", "department__name_zh"]
    autocomplete_fields = ["catalog", "department"]
