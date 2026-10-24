from django.contrib.auth import get_user_model
from django.test import TestCase

from ..models import Course, Enrollment, Section, Teacher, Term


class CourseTestCase(TestCase):
    def setUp(self):
        self.term = Term.objects.create(code="114-1", is_current=True)
        self.teacher = Teacher.objects.create(name="T")
        self.u = get_user_model().objects.create_user("u")

    def course(self, code, term=None):
        c, _ = Course.objects.get_or_create(term=term or self.term, code=code,
                                             defaults=dict(name=code, teacher=self.teacher))
        return c

    def section(self, code, label, start, end, capacity=40, day=1, term=None):
        return Section.objects.create(
            course=self.course(code, term=term),
            label=label, day=day, start_period=start, end_period=end, capacity=capacity)

    def my_sections(self):
        return list(Section.objects.filter(enrollments__user=self.u))

    def mine(self):
        return Enrollment.objects.filter(user=self.u).count()
