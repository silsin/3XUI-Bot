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
    traffic_gb: Mapped[int] = mapped_column(Integer, default=0)  # 0 = نامحدود
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
    traffic_gb: Mapped[int] = mapped_column(Integer, default=0)
    title: Mapped[str] = mapped_column(String(196), default="")
    points_used: Mapped[int] = mapped_column(Integer, default=0)

    receipt_file_id: Mapped[str | None] = mapped_column(String(256))
    receipt_is_document: Mapped[bool] = mapped_column(Boolean, default=False)
    admin_id: Mapped[int | None] = mapped_column(BigInteger)
    admin_note: Mapped[str | None] = mapped_column(Text)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    user: Mapped[User] = relationship(back_populates="orders")
    package: Mapped[Package | None] = relationship()


class Service(Base):
    """یک کانفیگ فعال متعلق به کاربر."""

    __tablename__ = "services"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    order_id: Mapped[int | None] = mapped_column(ForeignKey("orders.id"))

    title: Mapped[str] = mapped_column(String(196), default="")
    inbound_id: Mapped[int] = mapped_column(Integer, default=1)
    client_uuid: Mapped[str] = mapped_column(String(64), index=True)
    email: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    sub_id: Mapped[str] = mapped_column(String(64), default="")

    config_link: Mapped[str] = mapped_column(Text, default="")
    sub_link: Mapped[str] = mapped_column(Text, default="")

    traffic_gb: Mapped[int] = mapped_column(Integer, default=0)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    is_trial: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[ServiceStatus] = mapped_column(
        Enum(ServiceStatus), default=ServiceStatus.ACTIVE, index=True
    )

    # آخرین مصرف خوانده‌شده از پنل (بایت)
    used_bytes: Mapped[int] = mapped_column(BigInteger, default=0)
    expiry_notified: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    user: Mapped[User] = relationship(back_populates="services")


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
