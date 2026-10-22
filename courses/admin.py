from django.contrib import admin
from .models import Course, Enrollment, Section, Teacher, Term


@admin.register(Term)
class TermAdmin(admin.ModelAdmin):
    list_display = ["code", "is_current"]
    list_filter = ["is_current"]


@admin.register(Teacher)
class TeacherAdmin(admin.ModelAdmin):
    list_display = ["name", "email", "user"]
    search_fields = ["name"]
    autocomplete_fields = ["user"]


@admin.register(Course)
class CourseAdmin(admin.ModelAdmin):
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
