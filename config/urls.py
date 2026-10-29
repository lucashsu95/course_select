from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.urls import include, path

urlpatterns = [
    path("admin/", admin.site.urls),
    # 登出改用 Django 內建（POST-only）；Google OAuth 在 feat/google-oauth 分支
    path("logout/", auth_views.LogoutView.as_view(), name="logout"),
    path("", include("courses.urls")),
]
