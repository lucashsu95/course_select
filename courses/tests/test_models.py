from django.db import IntegrityError, transaction

from ..models import Term
from .base import CourseTestCase


class SectionConstraintTests(CourseTestCase):
    def test_end_before_start_is_rejected(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            self.section("BAD", "A", 5, 3)

    def test_same_code_allowed_in_another_term(self):
        self.section("CS101", "A", 1, 2)
        self.section("CS101", "A", 1, 2, term=Term.objects.create(code="114-2"))

    def test_duplicate_label_in_same_course_is_rejected(self):
        self.section("A", "A", 1, 2)
        with self.assertRaises(IntegrityError), transaction.atomic():
            self.section("A", "A", 4, 5)
