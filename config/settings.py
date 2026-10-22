import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
SECRET_KEY = os.environ.get("SECRET_KEY", "dev-only-change-me")
DEBUG = os.environ.get("DEBUG", "1") == "1"
ALLOWED_HOSTS = ["*"] if DEBUG else os.environ.get("ALLOWED_HOSTS", "").split(",")

INSTALLED_APPS = [
    "django.contrib.admin", "django.contrib.auth", "django.contrib.contenttypes",
    "django.contrib.sessions", "django.contrib.messages", "django.contrib.staticfiles",
    "django.contrib.sites",
    "allauth", "allauth.account", "allauth.socialaccount",
    "allauth.socialaccount.providers.google",
    "courses",
]
MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "allauth.account.middleware.AccountMiddleware",
]
ROOT_URLCONF = "config.urls"
TEMPLATES = [{
    "BACKEND": "django.template.backends.django.DjangoTemplates",
    "DIRS": [], "APP_DIRS": True,
    "OPTIONS": {"context_processors": [
        "django.template.context_processors.request",
        "django.contrib.auth.context_processors.auth",
        "django.contrib.messages.context_processors.messages",
    ]},
}]
DATABASES = {"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": BASE_DIR / "db.sqlite3"}}
LANGUAGE_CODE = "zh-hant"
TIME_ZONE = "Asia/Taipei"
USE_TZ = True
STATIC_URL = "static/"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# --- 登入：只開 Google ---
AUTHENTICATION_BACKENDS = [
    "django.contrib.auth.backends.ModelBackend",
    "allauth.account.auth_backends.AuthenticationBackend",
]
SITE_ID = 1
LOGIN_URL = "/accounts/google/login/"
LOGIN_REDIRECT_URL = "/"
LOGOUT_REDIRECT_URL = "/"
SOCIALACCOUNT_LOGIN_ON_GET = True  # 點登入直接跳 Google，不多一頁確認
ACCOUNT_EMAIL_VERIFICATION = "none"
SOCIALACCOUNT_PROVIDERS = {"google": {
    "APP": {"client_id": os.environ.get("GOOGLE_CLIENT_ID", ""),
            "secret": os.environ.get("GOOGLE_CLIENT_SECRET", ""), "key": ""},
    "SCOPE": ["profile", "email"],
}}

MAX_CREDITS = 25  # 學分上限

# --- ngrok demo：只在 USE_NGROK=1 時生效 ---
# 不寫死 *.ngrok-free.app，那是公共命名空間，別人的頁面也會被當成可信任 origin；
# X-Forwarded-Proto 任何客戶端也都能自己帶。上線前不要把這兩行留著生效。
if os.environ.get("USE_NGROK") == "1":
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    CSRF_TRUSTED_ORIGINS = [o.strip() for o in os.environ.get("NGROK_ORIGIN", "").split(",") if o.strip()]
