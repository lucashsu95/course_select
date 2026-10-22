from django.contrib import admin
from .models import Course, Enrollment, Teacher


@admin.register(Teacher)
class TeacherAdmin(admin.ModelAdmin):
    search_fields = ["name"]


@admin.register(Course)
class CourseAdmin(admin.ModelAdmin):
    list_display = ["code", "name", "teacher", "credits", "day", "start_period", "end_period", "capacity"]
    list_filter = ["day", "teacher"]
    search_fields = ["code", "name"]


@admin.register(Enrollment)
class EnrollmentAdmin(admin.ModelAdmin):
    list_display = ["user", "course", "created"]
    list_filter = ["course"]
