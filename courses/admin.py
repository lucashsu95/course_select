from django.contrib import admin
from .models import Comment, Course, Enrollment, Teacher, Term


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
    list_display = ["code", "name", "term", "teacher", "credits", "day", "start_period", "end_period", "capacity"]
    list_filter = ["term", "day", "teacher"]
    search_fields = ["code", "name"]


@admin.register(Enrollment)
class EnrollmentAdmin(admin.ModelAdmin):
    list_display = ["user", "course", "created"]
    list_filter = ["course__term", "course"]
    list_select_related = ["user", "course"]


@admin.register(Comment)
class CommentAdmin(admin.ModelAdmin):
    list_display = ["user", "course", "body", "created"]
    list_filter = ["course__term", "course"]
    search_fields = ["body", "user__username"]
    list_select_related = ["user", "course"]
