from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from .models import Course, Enrollment, Section, Term
from .services import register


def _my_section_ids(user):
    if not user.is_authenticated:
        return set()
    return set(Enrollment.objects.filter(user=user).values_list("section_id", flat=True))


def _redirect_next(request, fallback, *args):
    """表單帶的 next 只接受同一站台的網址，避免變成開放轉址。"""
    nxt = request.POST.get("next", "")
    if nxt and url_has_allowed_host_and_scheme(nxt, allowed_hosts={request.get_host()}):
        return redirect(nxt)
    return redirect(fallback, *args)


def course_list(request):
    """課程列表：每行是一個班別。"""
    q = request.GET.get("q", "").strip()
    day = request.GET.get("day", "")
    term = Term.current()
    sections = (Section.objects.filter(course__term=term)
                .select_related("course__teacher")
                .annotate(enrolled=Count("enrollments")))
    if q:
        sections = sections.filter(Q(course__name__icontains=q) | Q(course__code__icontains=q)
                                   | Q(course__teacher__name__icontains=q))
    if day.isdigit():
        sections = sections.filter(day=int(day))
    mine = _my_section_ids(request.user)
    sections = list(sections)
    for s in sections:
        s.is_mine = s.pk in mine
    full_count = sum(1 for s in sections if s.is_full)
    return render(request, "courses/list.html", {
        "sections": sections, "q": q, "day": day, "days": Section.DAYS, "full_count": full_count,
    })


def course_detail(request, pk):
    course = get_object_or_404(Course.objects.select_related("teacher"), pk=pk)
    sections = list(Section.objects.filter(course=course).annotate(enrolled=Count("enrollments")))
    mine = _my_section_ids(request.user)
    for s in sections:
        s.is_mine = s.pk in mine
    my_section = next((s for s in sections if s.is_mine), None)
    # 匿名使用者的 id 與 teacher.user_id 都可能是 None，先擋掉未登入
    is_teacher = request.user.is_authenticated and course.teacher.user_id == request.user.id
    related = list(Course.objects.filter(teacher=course.teacher, term=course.term).exclude(pk=pk)
                   .select_related("teacher")[:4])
    return render(request, "courses/detail.html", {
        "course": course, "sections": sections, "my_section": my_section, "is_teacher": is_teacher, "related": related,
    })


@login_required
@require_POST
def enroll(request, pk):
    section = get_object_or_404(Section.objects.select_related("course"), pk=pk)
    result = register(request.user, section)
    if result.ok:
        messages.success(request, result.message)
    elif result.code == "already":
        messages.info(request, result.message)
    else:
        messages.error(request, result.message)
    return _redirect_next(request, "course_detail", section.course_id)


@login_required
@require_POST
def drop(request, pk):
    section = get_object_or_404(Section.objects.select_related("course"), pk=pk)
    deleted, _ = Enrollment.objects.filter(user=request.user, section_id=pk).delete()
    if deleted:
        messages.success(request, f"已退選「{section.course.name} {section.label_display}」。")
    else:
        messages.info(request, "你沒有選這個班別。")
    return _redirect_next(request, "my_schedule")


@login_required
def my_schedule(request):
    mine = list(Section.objects.filter(enrollments__user=request.user, course__term=Term.current())
                .select_related("course__teacher"))
    grid = {(s.day, p): s for s in mine for p in range(s.start_period, s.end_period + 1)}
    last_period = max(8, max((s.end_period for s in mine), default=8))
    rows = [(p, [grid.get((d, p)) for d, _ in Section.DAYS]) for p in range(1, last_period + 1)]
    for s in mine:
        s.is_mine = True
    return render(request, "courses/schedule.html", {
        "mine": mine, "rows": rows, "days": [label for _, label in Section.DAYS],
        "total": sum({s.course_id: s.course.credits for s in mine}.values()), "max": settings.MAX_CREDITS,
    })


@login_required
def teaching_courses(request):
    courses = list(Course.objects.filter(teacher__user=request.user, term=Term.current())
                   .select_related("teacher"))
    by_course = {}
    for s in (Section.objects.filter(course__teacher__user=request.user, course__term=Term.current())
              .select_related("course").annotate(enrolled=Count("enrollments"))):
        by_course.setdefault(s.course_id, []).append(s)
    for c in courses:
        c.section_list = by_course.get(c.pk, [])
    return render(request, "courses/teaching.html", {"courses": courses})


@login_required
def course_roster(request, pk):
    course = get_object_or_404(Course.objects.select_related("teacher"), pk=pk, teacher__user=request.user)
    sections = list(Section.objects.filter(course=course).annotate(enrolled=Count("enrollments")))
    enrollments = (Enrollment.objects.filter(section__course=course)
                   .select_related("user", "section").order_by("created"))
    return render(request, "courses/roster.html", {
        "course": course, "sections": sections, "enrollments": enrollments,
    })
