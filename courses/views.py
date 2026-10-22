from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from .models import Course, Enrollment, Term
from .services import register


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
    term = Term.current()
    courses = Course.objects.filter(term=term).select_related("teacher").annotate(enrolled=Count("enrollment"))
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
    mine = _my_course_ids(request.user)
    # 匿名使用者的 id 與 teacher.user_id 都可能是 None，先擋掉未登入
    is_teacher = request.user.is_authenticated and course.teacher.user_id == request.user.id
    related = list(Course.objects.filter(teacher=course.teacher, term=course.term).exclude(pk=pk)
                   .select_related("teacher").annotate(enrolled=Count("enrollment"))[:4])
    for c in related:
        c.is_mine = c.pk in mine
    return render(request, "courses/detail.html", {
        "course": course, "is_mine": course.pk in mine, "is_teacher": is_teacher, "related": related,
        "days": Course.DAYS,
    })


@login_required
@require_POST
def enroll(request, pk):
    course = get_object_or_404(Course, pk=pk)
    result = register(request.user, course)
    if result.ok:
        messages.success(request, result.message)
    elif result.code == "already":
        messages.info(request, result.message)
    else:
        messages.error(request, result.message)
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
    mine = list(Course.objects.filter(enrollment__user=request.user, term=Term.current())
                .select_related("teacher").annotate(enrolled=Count("enrollment")))
    grid = {(c.day, p): c for c in mine for p in range(c.start_period, c.end_period + 1)}
    last_period = max(8, max((c.end_period for c in mine), default=8))
    rows = [(p, [grid.get((d, p)) for d, _ in Course.DAYS]) for p in range(1, last_period + 1)]
    for c in mine:
        c.is_mine = True
    return render(request, "courses/schedule.html", {
        "mine": mine, "rows": rows, "days": [label for _, label in Course.DAYS],
        "total": sum(c.credits for c in mine), "max": settings.MAX_CREDITS,
    })


@login_required
def teaching_courses(request):
    courses = (Course.objects.filter(teacher__user=request.user, term=Term.current())
               .select_related("teacher").annotate(enrolled=Count("enrollment")))
    return render(request, "courses/teaching.html", {"courses": courses})


@login_required
def course_roster(request, pk):
    course = get_object_or_404(
        Course.objects.select_related("teacher").annotate(enrolled=Count("enrollment")),
        pk=pk, teacher__user=request.user)
    return render(request, "courses/roster.html", {
        "course": course, "enrollments": course.enrollment_set.select_related("user").order_by("created"),
    })
