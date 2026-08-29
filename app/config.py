from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    """پیکربندی از فایل .env خوانده می‌شود."""

    model_config = SettingsConfigDict(
        env_file=BASE_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    bot_token: str = Field(alias="BOT_TOKEN")
    # به‌صورت رشته خوانده و در admin_ids پارس می‌شود (اجتناب از JSON-decode پیش‌فرض)
    admin_ids_raw: str = Field(default="", alias="ADMIN_IDS")
    receipts_chat_id: int | None = Field(default=None, alias="RECEIPTS_CHAT_ID")

    database_url: str = Field(
        default="sqlite+aiosqlite:///./data/bot.db", alias="DATABASE_URL"
    )

    # legacy = x-ui 1.x (vaxilu) ، panel = 3x-ui (MHSanaei)
    xui_variant: str = Field(default="legacy", alias="XUI_VARIANT")
    xui_base_url: str = Field(default="", alias="XUI_BASE_URL")
    xui_web_base_path: str = Field(default="", alias="XUI_WEB_BASE_PATH")
    xui_username: str = Field(default="", alias="XUI_USERNAME")
    xui_password: str = Field(default="", alias="XUI_PASSWORD")
    xui_node_host: str = Field(default="", alias="XUI_NODE_HOST")
    xui_sub_base_url: str = Field(default="", alias="XUI_SUB_BASE_URL")
    xui_verify_ssl: bool = Field(default=False, alias="XUI_VERIFY_SSL")

    # سرور اشتراک داخلی ربات (base64 همه کانفیگ‌های یک سرویس)
    sub_port: int = Field(default=8080, alias="SUB_PORT")
    sub_public_url: str = Field(default="", alias="SUB_PUBLIC_URL")
    # مسیر گواهی TLS داخل کانتینر؛ اگر تنظیم شود سرور اشتراک HTTPS می‌شود
    sub_tls_cert: str = Field(default="", alias="SUB_TLS_CERT")
    sub_tls_key: str = Field(default="", alias="SUB_TLS_KEY")

    timezone: str = Field(default="Asia/Tehran", alias="TIMEZONE")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")

    @field_validator("receipts_chat_id", mode="before")
    @classmethod
    def _parse_receipts_chat(cls, value: object) -> object:
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @property
    def admin_ids(self) -> list[int]:
        return [
            int(part)
            for part in self.admin_ids_raw.replace(" ", "").split(",")
            if part
        ]

    @property
    def receipts_target(self) -> int | None:
        """اولین مقصد رسید (سازگاری با کد قدیمی)."""
        targets = self.receipts_targets
        return targets[0] if targets else None

    @property
    def receipts_targets(self) -> list[int]:
        """همه مقصدهای دریافت رسید. اگر چت اختصاصی تعیین شده باشد فقط همان،
        در غیر این صورت همه ادمین‌ها."""
        if self.receipts_chat_id:
            return [self.receipts_chat_id]
        return list(self.admin_ids)

    def is_admin(self, user_id: int | None) -> bool:
        return user_id is not None and user_id in self.admin_ids


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
