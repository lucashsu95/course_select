from django.urls import path
from . import views

urlpatterns = [
    path("login/", views.demo_login, name="demo_login"),
    path("", views.course_list, name="course_list"),
    path("course/<int:pk>/", views.course_detail, name="course_detail"),
    path("section/<int:pk>/enroll/", views.enroll, name="enroll"),
    path("section/<int:pk>/drop/", views.drop, name="drop"),
    path("section/<int:pk>/cancel-wait/", views.cancel_wait, name="cancel_wait"),
    path("ack-promotion/", views.ack_promotion, name="ack_promotion"),
    path("my/", views.my_schedule, name="my_schedule"),
    path("teaching/", views.teaching_courses, name="teaching"),
    path("course/<int:pk>/roster/", views.course_roster, name="course_roster"),
]
