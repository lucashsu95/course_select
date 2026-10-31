"""後台側邊欄（AdminLTE 4 `admin_menu`）的中文分類與權限過濾測試。

涵蓋的驗收條件：

1. 側邊欄確實使用官方 `ADMINLTE["admin_menu"]`，並呈現五個中文分類。
2. 所有既有管理入口都還在側邊欄（沒有一個被拿掉）。
3. Course Maintainer 看不到學生選課紀錄、候補紀錄、使用者權限、維護員授權。
4. 權限過濾不是只看模型 view 權限：`SuperuserOnlyAdmin` 的限制即使權限被
   手動加給維護員也仍然有效。
5. 維護員的授權範圍（`CourseMaintainerScope`）有影響：沒有有效範圍時，
   受範圍限制的入口不會出現。
"""

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.test import RequestFactory, TestCase
from django_adminlte4.conf import get_config
from django_adminlte4.templatetags.adminlte import adminlte_admin_menu

from ..maintainer import grant_maintainer_access
from ..models import (AcademicCatalog, AcademicClassGroup, AcademicDepartment,
                      AcademicProgramType, CourseMaintainerScope)


def build_menu(user, path="/admin/"):
    """用官方模板標籤產生某個使用者看到的側邊欄選單。"""
    request = RequestFactory().get(path)
    request.user = user
    return adminlte_admin_menu({"request": request})


def category_titles(menu):
    return [item["text"] for item in menu]


def item_texts(menu):
    """把選單展開成所有項目文字（分類本身也含在內）。"""
    texts = []
    for item in menu:
        texts.append(item["text"])
        for child in item.get("submenu", []):
            texts.append(child["text"])
    return texts


class AdminMenuStructureTests(TestCase):
    """驗收 1、2：五個中文分類、既有入口一個都沒少。"""

    def test_uses_official_admin_menu_setting(self):
        cfg = get_config()
        self.assertIsNotNone(cfg.get("admin_menu"))
        self.assertTrue(cfg["admin_menu"], "ADMINLTE['admin_menu'] 不可為空")

    def test_has_required_chinese_categories(self):
        menu = build_menu(self.superuser())
        self.assertEqual(category_titles(menu), [
            "管理總覽", "課程規劃", "班級固定課表", "官方資料查核",
            "學籍與班級", "選課與候補", "系統管理",
        ])

    def test_expected_items_are_present(self):
        texts = item_texts(build_menu(self.superuser()))
        for expected in ("班別修課政策", "批次安排課程", "課程資料", "開課班別",
                         "學制", "系所", "班級", "學生學籍",
                         "官方開課來源", "官方班級課表", "官方課表明細", "課綱推薦",
                         "候選開課", "開課疑義",
                         "加選紀錄", "候補名單",
                         "學期", "教師", "學籍目錄", "維護員授權",
                         "使用者", "群組", "電子郵件", "站台設定"):
            self.assertIn(expected, texts)

    def test_every_registered_admin_model_has_a_menu_entry(self):
        """所有註冊在 Django Admin 的模型都還在側邊欄裡（既有入口全部保留）。"""
        from django.contrib import admin

        cfg = get_config()
        routes = set()
        for category in cfg["admin_menu"]:
            for child in category.get("submenu", []):
                if child.get("route"):
                    routes.add(child["route"])

        for model in admin.site._registry:
            wanted = (f"admin:{model._meta.app_label}_"
                      f"{model._meta.model_name}_changelist")
            self.assertIn(wanted, routes,
                          msg=f"側邊欄少了 {model._meta.label} 的入口")

    def test_category_icons_use_bootstrap_icons(self):
        for item in build_menu(self.superuser()):
            self.assertTrue(item["icon"].startswith("bi bi-"), msg=item["text"])

    def superuser(self):
        return get_user_model().objects.create_superuser(
            "root", email="root@example.com", password="pw")


class AdminMenuPermissionTests(TestCase):
    """驗收 3、4、5：維護員看不到敏感入口，且過濾考慮 SuperuserOnlyAdmin 與授權範圍。"""

    def setUp(self):
        User = get_user_model()
        self.superuser = User.objects.create_superuser("root", email="root@example.com",
                                                       password="pw")
        self.maintainer = User.objects.create_user("maintainer", email="m@ntub.edu.tw",
                                                   password="pw")
        self.catalog = AcademicCatalog.objects.create(version="menu-test")
        self.program_type = AcademicProgramType.objects.create(
            catalog=self.catalog, code="4", name_zh="四技日間部")
        self.department = AcademicDepartment.objects.create(
            catalog=self.catalog, program_type=self.program_type, code="406",
            name_zh="資訊管理系")
        self.class_group = AcademicClassGroup.objects.create(
            catalog=self.catalog, department=self.department, code="40620A",
            name_zh="資管二年甲班", grade_no=2)
        CourseMaintainerScope.objects.create(user=self.maintainer,
                                             department=self.department)
        grant_maintainer_access(self.maintainer)

    def test_maintainer_does_not_see_sensitive_entries(self):
        texts = item_texts(build_menu(self.maintainer))
        for hidden in ("加選紀錄", "候補名單", "使用者", "群組", "維護員授權"):
            self.assertNotIn(hidden, texts)

    def test_maintainer_does_not_see_sensitive_category(self):
        self.assertNotIn("選課與候補", category_titles(build_menu(self.maintainer)))

    def test_maintainer_does_not_see_student_academic_profile(self):
        """學生學籍是 SuperuserOnlyAdmin，維護員本來就開不了那個頁面。"""
        texts = item_texts(build_menu(self.maintainer))
        self.assertNotIn("學生學籍", texts)

    def test_maintainer_still_sees_allowed_entries(self):
        texts = item_texts(build_menu(self.maintainer))
        for visible in ("班別修課政策", "批次安排課程", "課程資料", "開課班別",
                        "學制", "系所", "班級",
                        "官方開課來源", "官方班級課表", "課綱推薦"):
            self.assertIn(visible, texts)

    def test_superuser_sees_everything(self):
        texts = item_texts(build_menu(self.superuser))
        for visible in ("加選紀錄", "候補名單", "使用者", "群組", "維護員授權",
                        "學生學籍", "站台設定"):
            self.assertIn(visible, texts)

    def test_view_permission_alone_does_not_reveal_sensitive_entries(self):
        """就算手動把 view 權限加給維護員，SuperuserOnlyAdmin 的限制仍然有效。"""
        group = Group.objects.get(name="Course Maintainer")
        for codename in ("view_enrollment", "view_waitlist", "view_studentacademicprofile"):
            permission = Permission.objects.get(codename=codename)
            group.permissions.add(permission)
        self.maintainer = get_user_model().objects.get(pk=self.maintainer.pk)

        texts = item_texts(build_menu(self.maintainer))
        for hidden in ("加選紀錄", "候補名單", "學生學籍"):
            self.assertNotIn(hidden, texts)

    def test_maintainer_scope_is_active_shows_scoped_entries(self):
        texts = item_texts(build_menu(self.maintainer))
        self.assertIn("課程資料", texts)
        self.assertIn("官方開課來源", texts)

    def test_maintainer_without_scope_hides_scoped_entries(self):
        """沒有任何有效授權範圍時，受範圍限制的入口不出現。"""
        CourseMaintainerScope.objects.filter(user=self.maintainer).update(is_active=False)
        texts = item_texts(build_menu(self.maintainer))
        for hidden in ("課程資料", "開課班別", "官方開課來源", "班別修課政策"):
            self.assertNotIn(hidden, texts)

    def test_bulk_assign_entry_requires_scope(self):
        CourseMaintainerScope.objects.filter(user=self.maintainer).update(is_active=False)
        texts = item_texts(build_menu(self.maintainer))
        self.assertNotIn("批次安排課程", texts)
