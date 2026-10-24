from django.contrib.auth import get_user_model
from django.urls import reverse

from ..models import Course
from .base import CourseTestCase


class PrereqLimitTests(CourseTestCase):
    """先修課至多 2 門；走 admin 的新增與編輯頁面。"""

    def setUp(self):
        super().setUp()
        self.client.force_login(get_user_model().objects.create_superuser("root", password="pw"))

    def course_data(self, code, *prereq_codes):
        return {"term": self.term.pk, "code": code, "name": "測試課", "teacher": self.teacher.pk,
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
