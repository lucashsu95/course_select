"""模板 context processors。"""
from . import waitlist
from .models import Term


def ui_shell(request):
    """App shell 需要的顯示資料（學期代碼）。不改業務邏輯。"""
    if request.path.startswith("/admin/"):
        return {}
    return {"current_term": Term.current()}


def waitlist_banner(request):
    """遞補成功通知：只 SELECT、不寫庫（GET 不該有狀態變更）。

    清除「已讀」由明確的 POST ack_promotion 處理，任何模板渲染
    （含 admin、allauth）都不會吃掉通知。
    """
    user = request.user
    if not user.is_authenticated:
        return {}
    items = list(waitlist.unread_promotions(user).select_related("section__course"))
    if not items:
        return {}
    return {"waitlist_banner": [f"{w.section.course.name} {w.section.label_display}" for w in items]}
