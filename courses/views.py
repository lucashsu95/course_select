from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import Count, Q, Sum
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from .models import Course, Enrollment


def _my_course_ids(user):
    if not user.is_authenticated:
        return set()
    return set(Enrollment.objects.filter(user=user).values_list("course_id", flat=True))


def _redirect_next(request, fallback, *args):
    """表單帶的 next 只接受同一站台的網址，避免變成開放轉址。"""
    nxt = request.POST.get("next", "")
    if nxt and url_has_allowed_host_and_scheme(nxt, allowed_hosts={request.get_host()}):
        return redirect(nxt)
    return redirect(fallback, *args)


def course_list(request):
    q = request.GET.get("q", "").strip()
    day = request.GET.get("day", "")
    courses = Course.objects.select_related("teacher").annotate(enrolled=Count("enrollment"))
    if q:
        courses = courses.filter(Q(name__icontains=q) | Q(code__icontains=q) | Q(teacher__name__icontains=q))
    if day.isdigit():
        courses = courses.filter(day=int(day))
    mine = _my_course_ids(request.user)
    courses = list(courses)
    for c in courses:
        c.is_mine = c.pk in mine
    full_count = sum(1 for c in courses if c.is_full)
    return render(request, "courses/list.html", {
        "courses": courses, "q": q, "day": day, "days": Course.DAYS, "full_count": full_count,
    })


def course_detail(request, pk):
    course = get_object_or_404(Course.objects.select_related("teacher").annotate(enrolled=Count("enrollment")), pk=pk)
    return render(request, "courses/detail.html", {
        "course": course, "is_mine": course.pk in _my_course_ids(request.user),
    })


@login_required
@require_POST
def enroll(request, pk):
    with transaction.atomic():
        # shortcut: sqlite 不支援列鎖，名額在高併發下可能超收；換 PostgreSQL 時 select_for_update 才會生效
        course = get_object_or_404(Course.objects.select_for_update(), pk=pk)
        mine = list(Course.objects.filter(enrollment__user=request.user))
        total = sum(c.credits for c in mine) + course.credits
        if course in mine:
            messages.info(request, "你已經加選過這門課了。")
        elif (clash := next((c for c in mine if c.conflicts_with(course)), None)):
            messages.error(request, f"衝堂：和「{clash.name}」時間重疊。")
        elif course.is_full:
            messages.error(request, "名額已滿。")
        elif total > settings.MAX_CREDITS:
            messages.error(request, f"超過學分上限 {settings.MAX_CREDITS}。")
        else:
            Enrollment.objects.create(user=request.user, course=course)
            messages.success(request, f"已加選「{course.name}」。")
    return _redirect_next(request, "course_detail", pk)


@login_required
@require_POST
def drop(request, pk):
    deleted, _ = Enrollment.objects.filter(user=request.user, course_id=pk).delete()
    if deleted:
        messages.success(request, "已退選。")
    else:
        messages.info(request, "你沒有選這門課。")
    return _redirect_next(request, "my_schedule")


@login_required
def my_schedule(request):
    mine = list(Course.objects.filter(enrollment__user=request.user).select_related("teacher"))
    grid = {(c.day, p): c for c in mine for p in range(c.start_period, c.end_period + 1)}
    last_period = max((c.end_period for c in mine), default=10)
    rows = [(p, [grid.get((d, p)) for d, _ in Course.DAYS]) for p in range(1, last_period + 1)]
    return render(request, "courses/schedule.html", {
        "mine": mine, "rows": rows, "days": [label for _, label in Course.DAYS],
        "total": sum(c.credits for c in mine), "max": settings.MAX_CREDITS,
    })
