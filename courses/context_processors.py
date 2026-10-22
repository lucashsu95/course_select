"""模板 context processors。"""
from django.utils import timezone

from .models import Waitlist


def waitlist_banner(request):
    """遞補成功通知：顯示一次（讀過就清 promoted_seen_at）。"""
    user = request.user
    if not user.is_authenticated:
        return {}
    items = list(Waitlist.objects.filter(
        user=user, promoted_at__isnull=False, promoted_seen_at__isnull=True,
    ).select_related("section__course"))
    if items:
        Waitlist.objects.filter(pk__in=[w.pk for w in items]).update(promoted_seen_at=timezone.now())
        return {"waitlist_banner": [f"{w.section.course.name} {w.section.label_display}" for w in items]}
    return {}
