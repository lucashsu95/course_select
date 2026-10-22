from django.core.management.base import BaseCommand
from courses.models import Course, Teacher, Term

DATA = [
    ("CS101", "程式設計", "王大明", 3, 1, 1, 3, "A101", "變數、流程控制、函式、基礎資料結構。\n評分：作業 40%、期中 30%、期末 30%"),
    ("CS201", "資料結構", "王大明", 3, 2, 2, 4, "A102", "陣列、鏈結串列、堆疊、佇列、樹與圖。"),
    ("CS301", "資料庫系統", "李小華", 3, 3, 3, 5, "B201", "關聯式模型、SQL、正規化、交易。"),
    ("CS302", "網頁程式設計", "李小華", 3, 3, 6, 8, "B202", "HTTP、Django、模板與 ORM，期末繳交小型專題。"),
    ("CS401", "機器學習", "陳美玲", 3, 4, 2, 4, "C301", "監督式學習、評估指標、簡單神經網路。"),
    ("MA101", "微積分", "林志明", 3, 1, 2, 4, "D101", "極限、微分、積分與應用。"),
    ("MA201", "線性代數", "林志明", 3, 5, 1, 3, "D102", "向量空間、矩陣、特徵值。"),
    ("EN101", "英文閱讀與寫作", "Sarah Chen", 2, 4, 6, 7, "E101", "學術閱讀與短文寫作練習。"),
    ("PE101", "游泳", "張大偉", 1, 5, 6, 7, "體育館", "基礎泳姿與水中安全。"),
    ("GE101", "設計思考", "陳美玲", 2, 2, 6, 7, "E202", "以小組專案練習同理、發想與原型。"),
]


class Command(BaseCommand):
    help = "載入範例課程（可重複執行）"

    def handle(self, *args, **opts):
        term, _ = Term.objects.get_or_create(code="114-1", defaults={"is_current": True})
        for code, name, teacher, cr, day, s, e, room, syl in DATA:
            t, _ = Teacher.objects.get_or_create(name=teacher)
            Course.objects.update_or_create(term=term, code=code, defaults=dict(
                name=name, teacher=t, credits=cr, day=day, start_period=s, end_period=e, room=room, syllabus=syl))
        self.stdout.write(f"已載入 {len(DATA)} 門課到 {term.code}")
