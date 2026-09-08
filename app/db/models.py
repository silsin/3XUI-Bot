from __future__ import annotations

import enum
from datetime import datetime, timezone

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class OrderStatus(str, enum.Enum):
    AWAITING_RECEIPT = "awaiting_receipt"
    AWAITING_APPROVAL = "awaiting_approval"
    APPROVED = "approved"
    REJECTED = "rejected"
    CANCELLED = "cancelled"


class OrderKind(str, enum.Enum):
    NEW = "new"
    RENEW = "renew"


class ServiceStatus(str, enum.Enum):
    ACTIVE = "active"
    EXPIRED = "expired"
    DISABLED = "disabled"


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    username: Mapped[str | None] = mapped_column(String(64))
    first_name: Mapped[str | None] = mapped_column(String(128))
    points: Mapped[int] = mapped_column(Integer, default=0)
    trial_used: Mapped[bool] = mapped_column(Boolean, default=False)
    is_blocked: Mapped[bool] = mapped_column(Boolean, default=False)
    referrer_id: Mapped[int | None] = mapped_column(BigInteger, index=True)
    referral_rewarded: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    services: Mapped[list["Service"]] = relationship(back_populates="user")
    orders: Mapped[list["Order"]] = relationship(back_populates="user")


class Setting(Base):
    """تنظیمات قابل ویرایش توسط ادمین (متن‌ها، شماره کارت، ...)."""

    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str] = mapped_column(Text, default="")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class Duration(Base):
    """مدت زمان اشتراک - از پنل ادمین تعریف می‌شود."""

    __tablename__ = "durations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    days: Mapped[int] = mapped_column(Integer)
    title: Mapped[str] = mapped_column(String(64))
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    packages: Mapped[list["Package"]] = relationship(
        back_populates="duration", cascade="all, delete-orphan"
    )


class Package(Base):
    """پکیج (حجم/قیمت) زیر یک مدت زمان مشخص."""

    __tablename__ = "packages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    duration_id: Mapped[int] = mapped_column(
        ForeignKey("durations.id", ondelete="CASCADE"), index=True
    )
    title: Mapped[str] = mapped_column(String(128))
    traffic_mb: Mapped[int] = mapped_column(Integer, default=0)  # مگابایت، 0 = نامحدود
    price: Mapped[int] = mapped_column(BigInteger)  # تومان
    device_limit: Mapped[int] = mapped_column(Integer, default=1)
    inbound_id: Mapped[int] = mapped_column(Integer, default=1)
    description: Mapped[str] = mapped_column(Text, default="")
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    duration: Mapped[Duration] = relationship(back_populates="packages")


class Order(Base):
    __tablename__ = "orders"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    package_id: Mapped[int | None] = mapped_column(ForeignKey("packages.id"))
    renew_service_id: Mapped[int | None] = mapped_column(ForeignKey("services.id"))

    kind: Mapped[OrderKind] = mapped_column(Enum(OrderKind), default=OrderKind.NEW)
    status: Mapped[OrderStatus] = mapped_column(
        Enum(OrderStatus), default=OrderStatus.AWAITING_RECEIPT, index=True
    )

    # اسنپ‌شات اطلاعات پکیج در لحظه خرید
    amount: Mapped[int] = mapped_column(BigInteger, default=0)
    days: Mapped[int] = mapped_column(Integer, default=0)
    traffic_mb: Mapped[int] = mapped_column(Integer, default=0)
    title: Mapped[str] = mapped_column(String(196), default="")
    points_used: Mapped[int] = mapped_column(Integer, default=0)

    # تخفیف اعمال‌شده
    offer_id: Mapped[int | None] = mapped_column(ForeignKey("offers.id", ondelete="SET NULL"), nullable=True)
    discount_amount: Mapped[int] = mapped_column(Integer, default=0)    # مبلغ تخفیف (تومان)
    bonus_traffic_mb: Mapped[int] = mapped_column(Integer, default=0)   # گیگ اضافه

    receipt_file_id: Mapped[str | None] = mapped_column(String(256))
    receipt_is_document: Mapped[bool] = mapped_column(Boolean, default=False)
    # پیام‌های رسید ارسال‌شده به ادمین‌ها: JSON از [[chat_id, message_id], ...]
    notify_msgs: Mapped[str] = mapped_column(Text, default="")
    admin_id: Mapped[int | None] = mapped_column(BigInteger)
    admin_note: Mapped[str | None] = mapped_column(Text)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    user: Mapped[User] = relationship(back_populates="orders")
    package: Mapped[Package | None] = relationship()


class ServiceSource(str, enum.Enum):
    """منبع ایجاد سرویس."""
    BOUGHT = "bought"                    # خریده شده
    SPLIT_FROM_SELF = "split_from_self"  # جدا شده برای خودم
    SPLIT_FROM_OTHER = "split_from_other" # دریافتی از کاربر دیگر


class Service(Base):
    """یک کانفیگ فعال متعلق به کاربر."""

    __tablename__ = "services"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    order_id: Mapped[int | None] = mapped_column(ForeignKey("orders.id"))
    parent_service_id: Mapped[int | None] = mapped_column(
        ForeignKey("services.id", ondelete="SET NULL"), index=True
    )

    title: Mapped[str] = mapped_column(String(196), default="")
    inbound_id: Mapped[int] = mapped_column(Integer, default=1)
    client_uuid: Mapped[str] = mapped_column(String(64), index=True)
    email: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    sub_id: Mapped[str] = mapped_column(String(64), default="")

    config_link: Mapped[str] = mapped_column(Text, default="")
    sub_link: Mapped[str] = mapped_column(Text, default="")

    traffic_mb: Mapped[int] = mapped_column(Integer, default=0)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    is_trial: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[ServiceStatus] = mapped_column(
        Enum(ServiceStatus), default=ServiceStatus.ACTIVE, index=True
    )
    source: Mapped[ServiceSource] = mapped_column(
        Enum(ServiceSource), default=ServiceSource.BOUGHT
    )

    # آخرین مصرف خوانده‌شده از پنل (بایت) — مجموع همه کلاینت‌ها
    used_bytes: Mapped[int] = mapped_column(BigInteger, default=0)
    expiry_notified: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    user: Mapped[User] = relationship(back_populates="services")
    clients: Mapped[list["ServiceClient"]] = relationship(
        back_populates="service", cascade="all, delete-orphan"
    )
    parent: Mapped["Service | None"] = relationship(
        foreign_keys=[parent_service_id], remote_side=[id], viewonly=True
    )


class ServiceClient(Base):
    """یک کانفیگ پروتکل مشخص متعلق به یک سرویس (روی یک inbound).

    چند کلاینت زیر یک سرویس، همگی متعلق به یک کاربر با سهمیه و انقضای مشترک
    هستند؛ سهمیه به‌صورت جمع مصرف همه‌ی آن‌ها در سطح ربات کنترل می‌شود.
    """

    __tablename__ = "service_clients"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    service_id: Mapped[int] = mapped_column(
        ForeignKey("services.id", ondelete="CASCADE"), index=True
    )
    inbound_id: Mapped[int] = mapped_column(Integer)
    protocol: Mapped[str] = mapped_column(String(32), default="")
    label: Mapped[str] = mapped_column(String(64), default="")
    client_uuid: Mapped[str] = mapped_column(String(64), index=True)
    email: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    config_link: Mapped[str] = mapped_column(Text, default="")
    used_bytes: Mapped[int] = mapped_column(BigInteger, default=0)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    service: Mapped[Service] = relationship(back_populates="clients")


class PointsEntry(Base):
    """دفتر امتیازات - هر تغییر امتیاز یک رکورد."""

    __tablename__ = "points_entries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    delta: Mapped[int] = mapped_column(Integer)
    reason: Mapped[str] = mapped_column(String(64))
    ref_user_id: Mapped[int | None] = mapped_column(BigInteger)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class TrialClaim(Base):
    """جلوگیری از گرفتن چندباره تست رایگان."""

    __tablename__ = "trial_claims"
    __table_args__ = (UniqueConstraint("user_id", name="uq_trial_user"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(BigInteger, index=True)
    service_id: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class UserActivity(Base):
    """لاگ فعالیت کاربران برای ردیابی رفتار در ربات."""

    __tablename__ = "user_activities"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    action: Mapped[str] = mapped_column(String(64), index=True)
    details: Mapped[str | None] = mapped_column(Text, default=None)  # JSON رشته
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)

    user: Mapped["User"] = relationship(viewonly=True)


class OfferType(str, enum.Enum):
    """نوع تخفیف."""
    PERCENT = "percent"       # درصد تخفیف از قیمت
    FIXED = "fixed"           # مبلغ ثابت تخفیف (تومان)
    EXTRA_TRAFFIC = "extra_traffic"  # گیگ اضافه بدون تخفیف قیمت


class Offer(Base):
    """تخفیف‌ها و پیشنهادهای ویژه."""

    __tablename__ = "offers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    # کد تخفیف — None یعنی اعمال خودکار بدون نیاز به کد
    code: Mapped[str | None] = mapped_column(String(32), unique=True, index=True, default=None)

    title: Mapped[str] = mapped_column(String(128))  # عنوان نمایشی
    description: Mapped[str] = mapped_column(Text, default="")  # توضیح برای کاربر

    # نوع و مقدار تخفیف
    offer_type: Mapped[OfferType] = mapped_column(Enum(OfferType), default=OfferType.PERCENT)
    value: Mapped[int] = mapped_column(Integer, default=0)
    # برای PERCENT: عدد ۱ تا ۱۰۰ (درصد)
    # برای FIXED: مبلغ به تومان
    # برای EXTRA_TRAFFIC: مگابایت اضافه

    # محدودیت استفاده
    max_uses: Mapped[int] = mapped_column(Integer, default=0)   # 0 = نامحدود
    used_count: Mapped[int] = mapped_column(Integer, default=0)
    per_user: Mapped[int] = mapped_column(Integer, default=0)   # حداکثر استفاده هر کاربر (0=نامحدود)

    # فیلتر بر روی بسته/مدت — None یعنی روی همه اعمال می‌شود
    package_id: Mapped[int | None] = mapped_column(ForeignKey("packages.id", ondelete="SET NULL"), nullable=True)
    duration_id: Mapped[int | None] = mapped_column(ForeignKey("durations.id", ondelete="SET NULL"), nullable=True)

    # بازه زمانی اعتبار
    valid_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    valid_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)

    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    package: Mapped["Package | None"] = relationship(viewonly=True)
    duration: Mapped["Duration | None"] = relationship(viewonly=True)


class OfferUse(Base):
    """سابقه استفاده از کدهای تخفیف توسط کاربران."""

    __tablename__ = "offer_uses"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    offer_id: Mapped[int] = mapped_column(ForeignKey("offers.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    order_id: Mapped[int | None] = mapped_column(ForeignKey("orders.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    offer: Mapped["Offer"] = relationship(viewonly=True)
