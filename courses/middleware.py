"""還沒做過首次學籍設定的學生，一律先導到 /onboarding/。

判斷只針對「用 Google 登入的學生」：
- 老師、staff、以及本機帳號（本機建立的 demo／測試帳號）不受影響。
- 匿名瀏覽者照常看課程列表，不跳。

導向清單（不跳、避免 Redirect Loop）：
- /onboarding/        首次學籍設定頁本身
- /me/profile/        個人資料頁（設定完成後才有內容，但導過去也安全）
- /accounts/...       allauth 的 OAuth 登入／回呼／登出
- /admin/...          Django Admin
- /logout/            登出
- 靜態資源與登入頁
"""

from django.shortcuts import redirect
from django.urls import reverse

from .academic import needs_academic_profile

# 這些路徑不導向 onboarding（保持登入、回呼、登出、Admin、靜態資源正常）
ALLOWED_PREFIXES = (
    "/onboarding/",
    "/me/profile/",
    "/accounts/",
    "/admin/",
    "/logout/",
    "/static/",
    "/media/",
    "/login/",
    "/favicon.ico",
    "/health",
)


class AcademicProfileRequiredMiddleware:
    """未完成首次學籍設定的 Google 學生，只能停留在 onboarding 與個人資料頁。"""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = getattr(request, "user", None)
        if user is not None and user.is_authenticated and needs_academic_profile(user):
            path = request.path
            if not path.startswith(ALLOWED_PREFIXES):
                return redirect(reverse("onboarding"))
        return self.get_response(request)
