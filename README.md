# 選課系統

Django + Google 登入的迷你選課系統：瀏覽課程、加退選（自動擋衝堂、額滿、超學分）、週課表。

## 功能

- **課程列表** — 關鍵字搜尋課名／課號／老師，依星期篩選，顯示已選人數與剩餘名額。
- **加退選** — 加選前檢查衝堂、名額、學分上限；已加選的課會標示。
- **我的課表** — 週一至週五、第 1–10 節網格，附總學分。
- **登入** — 只開放 Google（django-allauth）。課程瀏覽免登入，加選才需要。

## 快速開始

需要 Python 3.12+ 與 [uv](https://docs.astral.sh/uv/)。

```bash
uv sync                        # 建 .venv 並安裝依賴
cp .env.example .env           # 填入 Google OAuth 憑證，見下一節
uv run manage.py migrate
uv run manage.py seed          # 載入 10 門範例課程，可重複執行
uv run --env-file .env manage.py runserver
```

開 <http://localhost:8000>。要進 `/admin/` 先跑一次 `uv run manage.py createsuperuser`。

## Google 登入設定

1. Google Cloud Console → 建立 OAuth 用戶端，類型選「網頁應用程式」。
2. Authorized redirect URI 填 `http://localhost:8000/accounts/google/login/callback/`。
3. Client ID 與 Secret 寫進 `.env`：

   ```dotenv
   GOOGLE_CLIENT_ID=...
   GOOGLE_CLIENT_SECRET=...
   ```

沒填憑證時課程頁仍可瀏覽，只有登入會失敗。

## 測試

```bash
uv run manage.py test
```

涵蓋加選的衝堂／額滿／退選流程，以及三個頁面可正常渲染。

## 專案結構

```
config/     settings、根路由（/admin/、/accounts/、courses）
courses/    models（Term / Teacher / Course / Enrollment）、services、views、urls、templates、static
courses/management/commands/seed.py    範例學期與課程資料
```

## 可調設定

| 位置 | 項目 |
| --- | --- |
| `config/settings.py` | `MAX_CREDITS = 25`：每學期學分上限 |
| `.env` | `SECRET_KEY`、`DEBUG`、`ALLOWED_HOSTS`（上線時設 `DEBUG=0` 且填 `ALLOWED_HOSTS`） |

## 已知限制

- 名額檢查在 SQLite 上取不到列鎖，高併發下可能超收；換 PostgreSQL 後 `select_for_update()` 才會真正生效（`courses/views.py`）。
- 資料庫為 SQLite，定位是本地開發與 demo。
