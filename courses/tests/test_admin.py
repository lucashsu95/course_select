from django.contrib import admin
from django.contrib.auth import get_user_model
from django.test import RequestFactory
from django.urls import reverse

from ..models import (AcademicCatalog, AcademicClassGroup, AcademicDepartment,
                      AcademicProgramType, Course, NtubTimetableEntry,
                      NtubTimetableSnapshot, OfficialCourseCredit, Teacher, Term)
from .base import CourseTestCase


class PrereqLimitTests(CourseTestCase):
    """先修課至多 2 門；走 admin 的新增與編輯頁面。"""

    def setUp(self):
        super().setUp()
        self.client.force_login(get_user_model().objects.create_superuser("root", password="pw"))

    def course_data(self, code, *prereq_codes):
        catalog, _ = AcademicCatalog.objects.get_or_create(version="prereq-admin")
        program, _ = AcademicProgramType.objects.get_or_create(
            catalog=catalog, code="4",
            defaults={"name_zh": "四技日間部"},
        )
        department, _ = AcademicDepartment.objects.get_or_create(
            catalog=catalog, program_type=program, code="406",
            defaults={"name_zh": "資管系"},
        )
        return {"term": self.term.pk, "owning_department": department.pk,
                "code": code, "name": "測試課", "teacher": self.teacher.pk,
                "credits": 3, "syllabus": "",
                "prerequisites": [self.course(c).pk for c in prereq_codes]}

    def test_add_course_with_two_prereqs_saves(self):
        r = self.client.post(reverse("admin:courses_course_add"), self.course_data("CS999", "CS101", "CS202"))
        self.assertEqual(r.status_code, 302)
        self.assertEqual(Course.objects.get(term=self.term, code="CS999").prerequisites.count(), 2)

    def test_add_course_with_three_prereqs_is_rejected(self):
        r = self.client.post(reverse("admin:courses_course_add"),
                             self.course_data("CS999", "CS101", "CS202", "CS303"))
        self.assertContains(r, "先修課程最多設 2 門。")
        self.assertFalse(Course.objects.filter(term=self.term, code="CS999").exists())

    def test_edit_course_to_three_prereqs_is_rejected(self):
        target = self.course("CS999")
        target.prerequisites.set([self.course("CS101"), self.course("CS202")])
        r = self.client.post(reverse("admin:courses_course_change", args=[target.pk]),
                             self.course_data("CS999", "CS101", "CS202", "CS303"))
        self.assertContains(r, "先修課程最多設 2 門。")
        self.assertEqual(target.prerequisites.count(), 2)


class OfficialCourseCreditAdminTests(CourseTestCase):
    def setUp(self):
        super().setUp()
        catalog = AcademicCatalog.objects.create(version="admin-credit")
        program = AcademicProgramType.objects.create(
            catalog=catalog, code="4", name_zh="四技日間部")
        department = AcademicDepartment.objects.create(
            catalog=catalog, program_type=program, code="406", name_zh="資管系")
        self.class_group = AcademicClassGroup.objects.create(
            catalog=catalog, department=department, code="40630B",
            name_zh="資管三年乙班", grade_no=3)
        self.snapshot = NtubTimetableSnapshot.objects.create(
            class_group=self.class_group, term=self.term)
        self.entry = NtubTimetableEntry.objects.create(
            snapshot=self.snapshot, entry_type="course", course_code="PE301",
            course_name="體育三（上）", weekday=1, start_period=1, end_period=2)
        self.admin_user = get_user_model().objects.create_superuser(
            "credit-admin", "credit@example.com", "password")
        self.client.force_login(self.admin_user)

    def test_existing_credit_is_prefilled_and_zero_is_saved(self):
        credit = OfficialCourseCredit.objects.create(
            term=self.term, class_group=self.class_group,
            course_code="PE301", credits=0, source_note="學制核對")
        model_admin = admin.site._registry[NtubTimetableEntry]
        request = RequestFactory().get("/")
        request.user = self.admin_user
        form_class = model_admin.get_form(request, self.entry)
        form = form_class(instance=self.entry)
        self.assertEqual(form.initial["confirmed_credits"], 0)
        self.assertEqual(form.initial["credit_source_note"], "學制核對")
        self.assertIn("confirmed_credits", form.fields)
        self.assertEqual(credit.credits, 0)

        bound = form_class(
            data={"confirmed_credits": "0", "credit_source_note": "重新核對"},
            instance=self.entry)
        self.assertTrue(bound.is_valid(), bound.errors)
        model_admin.save_model(request, self.entry, bound, change=True)
        credit.refresh_from_db()
        self.assertEqual(credit.credits, 0)
        self.assertEqual(credit.source_note, "重新核對")

        unchanged = form_class(data={
            "confirmed_credits": "", "credit_source_note": "",
        }, instance=self.entry)
        self.assertTrue(unchanged.is_valid(), unchanged.errors)
        model_admin.save_model(request, self.entry, unchanged, change=True)
        credit.refresh_from_db()
        self.assertEqual(credit.credits, 0)

    def test_adding_entry_can_create_credit_in_same_save(self):
        model_admin = admin.site._registry[NtubTimetableEntry]
        request = RequestFactory().get("/")
        request.user = self.admin_user
        form_class = model_admin.get_form(request)
        form = form_class(data={
            "snapshot": self.snapshot.pk,
            "entry_type": "course",
            "course_code": "OS301",
            "official_serial": "",
            "course_name": "作業系統",
            "teacher_name": "",
            "classroom": "",
            "weekday": 1,
            "start_period": 3,
            "end_period": 4,
            "periods": "[]",
            "raw_text": "",
            "course_href": "",
            "confirmed_credits": "3",
            "credit_source_note": "人工核對",
        })
        self.assertTrue(form.is_valid(), form.errors)
        entry = form.save(commit=False)
        model_admin.save_model(request, entry, form, change=False)
        self.assertTrue(OfficialCourseCredit.objects.filter(
            term=self.term, class_group=self.class_group,
            course_code="OS301", credits=3).exists())

    def test_sync_official_page_handles_class_without_grade(self):
        AcademicClassGroup.objects.create(
            catalog=self.class_group.catalog,
            department=self.class_group.department,
            code="406XX",
            name_zh="未設定年級班級",
            grade_no=None,
        )
        response = self.client.get(
            reverse("admin:courses_ntubtimetablesnapshot_sync_official"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "未設定年級")
