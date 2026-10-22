# 貢獻流程

## 1. 開發流程

1. 從 `main` 切功能分支：`feat/<主題>` 或 `fix/<主題>`
2. 實作＋寫測試（新功能必須有對應測試）
3. Push 後開 PR，body 說明改動與驗證方式
4. 審查通過後合併（`main` 有 branch protection，禁止 force push）

## 2. 合併前必做（PR 審查會逐項查）

- [ ] `uv run manage.py check` 零 error
- [ ] `uv run manage.py test` 全綠（含新功能測試）
- [ ] 涉及 migration 時：用**已有資料的 DB** 實跑 migrate 驗證不丟資料
- [ ] README 的功能說明、測試說明與實際行為一致
- [ ] **若改動業務行為：`docs/business-rules.md` 已同步更新（見下條）**

## 3. 業務規則文件同步（強制）

`docs/business-rules.md` 是系統業務邏輯的單一事實來源。**任何改動業務行為的 PR，合併前必須回修該文件**，規則：

- 加選規則、衝堂判定、學分計算、退選行為、角色權限、安全邊界有變 → 改對應章節
- 新增功能（如日曆同步、等待名單、選課時間窗、先修檢查）→ 加新章節，並從該功能的 issue 把「決策點」的定案寫進去
- 移除功能 → 刪對應章節，不留死文件
- 文件標頭有「最後對齊」日期與 commit——更新時一併更新
- 文件與程式碼不一致時，**以程式碼為準**並立即回修文件（文件是說明，不是規格來源）

判斷標準：PR 的 diff 如果讓 `services.py` 的規則、`models.py` 的 constraint、或 view 的權限/重定向行為改變，就是「改動業務行為」，必須回修。純 UI、樣式、重構（行為不變）不用。

## 4. Commit 格式

- 標題：`<type>: <簡短描述>`（type：feat / fix / docs / test / refactor / chore / style）
- 一個 commit 一個邏輯變更；「而且／同時」連著的兩件事拆開
- 內文用數字條列寫清楚改了什麼、為什麼
- 繁體中文

## 5. 測試

- 框架：Django 內建（`courses/tests.py`）
- 新規則要測「被擋」與「放行」兩邊（如先修未修被擋、已修可選）
- 視圖行為用 `self.client` 測狀態碼與訊息，不要只測 model
