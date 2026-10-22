from django.urls import path
from . import views

urlpatterns = [
    path("", views.course_list, name="course_list"),
    path("course/<int:pk>/", views.course_detail, name="course_detail"),
    path("course/<int:pk>/enroll/", views.enroll, name="enroll"),
    path("course/<int:pk>/drop/", views.drop, name="drop"),
    path("course/<int:pk>/comment/", views.add_comment, name="add_comment"),
    path("my/", views.my_schedule, name="my_schedule"),
    path("teaching/", views.teaching_courses, name="teaching"),
    path("course/<int:pk>/roster/", views.course_roster, name="course_roster"),
]
