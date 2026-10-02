"""مدیریت پنل‌ها و اینباندها از داخل ربات.

پنل‌ها در دیتابیس نگهداری می‌شوند و اینباندها جداگانه روی هر پنل ثبت
یا ساخته می‌شوند.
"""

from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Panel, PanelInbound
from app.filters import IsAdmin
from app.keyboards import admin as kb
from app.services import panel_service as ps
from app.services.vpn import VpnError
from app.states import AdminFlow
from app.utils.formatting import fa_digits

logger = logging.getLogger(__name__)
router = Router(name="admin_panels")
router.callback_query.filter(IsAdmin())
router.message.filter(IsAdmin())

HOME = "🛰 <b>پنل‌ها و اینباندها</b>\nپنل مورد نظر را انتخاب کنید:"


# ---------- فهرست پنل ----------


@router.callback_query(kb.AdminCB.filter(F.action == "panels"))
async def panels_home(call: CallbackQuery, session: AsyncSession) -> None:
    panels = await ps.list_panels(session)
    text = HOME
    if not panels:
        text += "\n\n⚠️ هنوز پنلی ثبت نشده است."
    await call.message.edit_text(text, reply_markup=kb.panels_list(panels))
    await call.answer()


@router.callback_query(kb.AdminCB.filter(F.action == "panel_seed"))
async def panel_seed(call: CallbackQuery, session: AsyncSession) -> None:
    """درج پنل تنظیم‌شده در .env به عنوان اولین پنل."""
    panel = await ps.ensure_default_from_env(session)
    if panel is None:
        await call.answer("پنلی در .env نبود یا از قبل ثبت شده.", show_alert=True)
        return
    await call.answer("✅ پنل .env ثبت شد.")
    await panels_home(call, session)


@router.callback_query(kb.AdminCB.filter(F.action == "panel_view"))
async def panel_view(
    call: CallbackQuery, callback_data: kb.AdminCB, session: AsyncSession
) -> None:
    panel = await ps.get_panel(session, callback_data.arg)
    if panel is None:
        await call.answer("پنل یافت نشد.", show_alert=True)
        return
    rows = await ps.list_inbounds_of(session, panel.id)
    client = ps.get_provider_for_panel(panel)
    can_manage = hasattr(client, "create_inbound") and hasattr(
        client, "delete_inbound"
    )
    from app.services.panel_service import VARIANTS

    text = (
        f"🛰 <b>{panel.title}</b>\n"
        f"نوع: {VARIANTS.get(panel.variant, panel.variant)}\n"
        f"وضعیت: {'🟢' if panel.is_active else '⚪️'}\n"
        f"آدرس: <code>{panel.base_url}</code>\n"
        f"مسیر پایه: <code>{panel.web_base_path or '—'}</code>\n"
        f"هاست لینک: <code>{panel.node_host or '—'}</code>\n"
        f"اینباند ثبت‌شده: {fa_digits(len(rows))}\n"
        f"توکن: {'✅' if panel.api_token else '—'}"
    )
    if not can_manage:
        text += "\n\n⚠️ در این نوع پنل، ساخت/حذف اینباند از ربات پشتیبانی نمی‌شود."
    await call.message.edit_text(
        text, reply_markup=kb.panel_view(panel.id, can_manage=can_manage)
    )
    await call.answer()


@router.callback_query(kb.AdminCB.filter(F.action == "panel_test"))
async def panel_test(
    call: CallbackQuery, callback_data: kb.AdminCB, session: AsyncSession
) -> None:
    panel = await ps.get_panel(session, callback_data.arg)
    if panel is None:
        await call.answer("پنل یافت نشد.", show_alert=True)
        return
    await call.answer("در حال تست...")
    try:
        await ps.test_panel(session, panel)
        await call.answer("🟢 اتصال موفق بود", show_alert=True)
    except VpnError as exc:
        await call.answer(f"🔴 {exc}"[:180], show_alert=True)
    except Exception as exc:  # noqa: BLE001
        await call.answer(f"🔴 {type(exc).__name__}: {exc}"[:180], show_alert=True)


@router.callback_query(kb.AdminCB.filter(F.action == "panel_toggle"))
async def panel_toggle(
    call: CallbackQuery, callback_data: kb.AdminCB, session: AsyncSession
) -> None:
    panel = await ps.get_panel(session, callback_data.arg)
    if panel is None:
        await call.answer("پنل یافت نشد.", show_alert=True)
        return
    await ps.update_panel(session, panel, is_active=not panel.is_active)
    await call.answer("تغییر کرد.")
    await panel_view(
        call, kb.AdminCB(action="panel_view", arg=panel.id), session
    )


@router.callback_query(kb.AdminCB.filter(F.action == "panel_refresh"))
async def panel_refresh(
    call: CallbackQuery, callback_data: kb.AdminCB, session: AsyncSession
) -> None:
    ps.invalidate_cache(callback_data.arg)
    await call.answer("کش پاک شد؛ اتصال تازه برقرار می‌شود.")


@router.callback_query(kb.AdminCB.filter(F.action == "panel_del_confirm"))
async def panel_del_confirm(
    call: CallbackQuery, callback_data: kb.AdminCB, session: AsyncSession
) -> None:
    panel = await ps.get_panel(session, callback_data.arg)
    if panel is None:
        await call.answer("پنل یافت نشد.", show_alert=True)
        return
    text = (
        f"⚠️ پنل <b>{panel.title}</b> و همه اینباندهای ثبت‌شده‌اش حذف شود؟\n"
        "روی خود پنل و کلاینت‌هایش اثری ندارد."
    )
    await call.message.edit_text(
        text,
        reply_markup=kb.confirm(
            action="panel_del_yes", arg=panel.id, back_action="panel_view"
        ),
    )
    await call.answer()


@router.callback_query(kb.AdminCB.filter(F.action == "panel_del_yes"))
async def panel_del_yes(
    call: CallbackQuery, callback_data: kb.AdminCB, session: AsyncSession
) -> None:
    panel = await ps.get_panel(session, callback_data.arg)
    if panel is None:
        await call.answer("پنل یافت نشد.", show_alert=True)
        return
    await ps.delete_panel(session, panel)
    await call.answer("حذف شد.")
    await panels_home(call, session)


# ---------- ویرایش فیلد پنل ----------


@router.callback_query(kb.AdminCB.filter(F.action == "panel_edit_menu"))
async def panel_edit_menu(
    call: CallbackQuery, callback_data: kb.AdminCB, session: AsyncSession
) -> None:
    panel = await ps.get_panel(session, callback_data.arg)
    if panel is None:
        await call.answer("پنل یافت نشد.", show_alert=True)
        return
    await call.message.edit_text(
        f"✏️ ویرایش <b>{panel.title}</b>\nفیلد مورد نظر را انتخاب کنید:",
        reply_markup=kb.panel_edit_fields(panel.id),
    )
    await call.answer()


@router.callback_query(kb.AdminCB.filter(F.action == "panel_edit_field"))
async def panel_edit_field(
    call: CallbackQuery,
    callback_data: kb.AdminCB,
    session: AsyncSession,
    state: FSMContext,
) -> None:
    panel = await ps.get_panel(session, callback_data.arg)
    if panel is None:
        await call.answer("پنل یافت نشد.", show_alert=True)
        return
    field = callback_data.field or ""
    await state.set_state(AdminFlow.panel_field)
    await state.update_data(panel_id=panel.id, field=field)
    current = str(getattr(panel, field, "") or "")
    if field in {"api_token", "password"}:
        current = "••••••" if current else "—"
    await call.message.answer(
        f"مقدار فعلی <code>{current or '—'}</code>\n\n"
        "مقدار جدید را بفرستید (/cancel برای انصراف)."
    )
    await call.answer()


@router.message(AdminFlow.panel_field)
async def panel_field_save(
    message: Message, session: AsyncSession, state: FSMContext
) -> None:
    data = await state.get_data()
    panel = await ps.get_panel(session, int(data.get("panel_id") or 0))
    if panel is None:
        await message.answer("پنل یافت نشد.")
        await state.clear()
        return
    field = data.get("field", "")
    value = (message.text or "").strip()
    if field == "base_url" and not value.startswith(("http://", "https://")):
        await message.answer("آدرس باید با http:// یا https:// شروع شود.")
        return
    if field == "variant" and value not in ps.VARIANTS:
        await message.answer("نوع نامعتبر. یکی از: " + ", ".join(ps.VARIANTS))
        return
    try:
        await ps.update_panel(session, panel, **{field: value})
    except Exception as exc:  # noqa: BLE001
        await message.answer(f"🔴 خطا: {exc}")
        return
    await state.clear()
    client = ps.get_provider_for_panel(panel)
    manage = hasattr(client, "create_inbound") and hasattr(client, "delete_inbound")
    await message.answer(
        "✅ ذخیره شد.",
        reply_markup=kb.panel_view(panel.id, panel.variant, manage),
    )


# ---------- ساخت پنل ----------


@router.callback_query(kb.AdminCB.filter(F.action == "panel_new"))
async def panel_new(call: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await state.set_state(AdminFlow.panel_title)
    await call.message.answer(
        "➕ ساخت پنل جدید\n\nعنوان پنل را بفرستید (مثلاً سرور آلمان)."
    )
    await call.answer()


@router.callback_query(kb.AdminCB.filter(F.action == "panel_new_variant"))
async def panel_new_variant(
    call: CallbackQuery, callback_data: kb.AdminCB, state: FSMContext
) -> None:
    await state.update_data(variant=callback_data.field or "xui3")
    await state.set_state(AdminFlow.panel_url)
    await call.message.answer(
        "آدرس کامل پنل را بفرستید، مثلاً:\n<code>https://1.2.3.4:2053</code>"
    )
    await call.answer()


@router.message(AdminFlow.panel_title)
async def panel_title(message: Message, state: FSMContext) -> None:
    title = (message.text or "").strip()
    if not title:
        await message.answer("عنوان نمی‌تواند خالی باشد.")
        return
    await state.update_data(title=title)
    await state.set_state(AdminFlow.panel_variant)
    await message.answer("نوع پنل را انتخاب کنید:", reply_markup=kb.variant_choose())


@router.message(AdminFlow.panel_url)
async def panel_url(message: Message, state: FSMContext) -> None:
    url = (message.text or "").strip()
    if not url.startswith(("http://", "https://")):
        await message.answer("آدرس باید با http:// یا https:// شروع شود.")
        return
    await state.update_data(base_url=url.rstrip("/"))
    await state.set_state(AdminFlow.panel_path)
    await message.answer(
        "مسیر پایه پنل را بفرستید؛ اگر ندارد <code>-</code> بفرستید.\n"
        "مثال: <code>039i881dMbhx5VurVZ</code>"
    )


@router.message(AdminFlow.panel_path)
async def panel_path(message: Message, state: FSMContext) -> None:
    path = (message.text or "").strip()
    await state.update_data(web_base_path="" if path in {"-", ""} else path.strip("/"))
    data = await state.get_data()
    if str(data.get("variant", "")) in {"legacy", "panel"}:
        await state.set_state(AdminFlow.panel_user)
        await message.answer("نام کاربری پنل را بفرستید:")
    else:
        await state.set_state(AdminFlow.panel_token)
        await message.answer(
            "🔑 توکن API را بفرستید (Settings → Security → API Token)."
        )


@router.message(AdminFlow.panel_token)
async def panel_token(message: Message, state: FSMContext) -> None:
    token = (message.text or "").strip()
    if not token:
        await message.answer("توکن نمی‌تواند خالی باشد.")
        return
    await state.update_data(api_token=token, username="", password="")
    await state.set_state(AdminFlow.panel_host)
    await _ask_node_host(message)


@router.message(AdminFlow.panel_user)
async def panel_user(message: Message, state: FSMContext) -> None:
    user = (message.text or "").strip()
    if not user:
        await message.answer("نام کاربری نمی‌تواند خالی باشد.")
        return
    await state.update_data(username=user, api_token="")
    await state.set_state(AdminFlow.panel_pass)
    await message.answer("گذرواژه پنل را بفرستید:")


@router.message(AdminFlow.panel_pass)
async def panel_pass(message: Message, state: FSMContext) -> None:
    password = (message.text or "").strip()
    if not password:
        await message.answer("گذرواژه نمی‌تواند خالی باشد.")
        return
    await state.update_data(password=password)
    await state.set_state(AdminFlow.panel_host)
    await _ask_node_host(message)


async def _ask_node_host(message: Message) -> None:
    await message.answer(
        "📍 دامنه یا IP که در لینک کانفیگ کاربران استفاده می‌شود\n"
        "مثال: <code>138.199.216.221</code>"
    )


@router.message(AdminFlow.panel_host)
async def panel_host(message: Message, session: AsyncSession, state: FSMContext) -> None:
    host = (message.text or "").strip()
    await state.update_data(node_host=host)
    data = await state.get_data()

    fields = {
        "title": data.get("title", "پنل"),
        "variant": data.get("variant", "xui3"),
        "base_url": data.get("base_url", ""),
        "web_base_path": data.get("web_base_path", ""),
        "api_token": data.get("api_token", ""),
        "username": data.get("username", ""),
        "password": data.get("password", ""),
        "node_host": host,
        "is_active": True,
        "sort_order": 0,
    }
    if not fields["base_url"]:
        await message.answer("آدرس پنل ثبت نشد؛ دوباره از منو شروع کنید.")
        await state.clear()
        return

    panel = await ps.add_panel(session, **fields)
    await state.clear()

    # ذخیره اول بدون تست؛ ادمین بعداً دکمه تست می‌گیرد
    client = ps.get_provider_for_panel(panel)
    manage = hasattr(client, "create_inbound") and hasattr(client, "delete_inbound")
    await message.answer(
        f"✅ پنل <b>{panel.title}</b> ثبت شد.",
        reply_markup=kb.panel_view(panel.id, panel.variant, manage),
    )


# ---------- اینباندها ----------


@router.callback_query(kb.AdminCB.filter(F.action == "inb_list"))
async def inb_list(
    call: CallbackQuery, callback_data: kb.AdminCB, session: AsyncSession
) -> None:
    panel = await ps.get_panel(session, callback_data.arg)
    if panel is None:
        await call.answer("پنل یافت نشد.", show_alert=True)
        return
    rows = await ps.list_inbounds_of(session, panel.id)
    client = ps.get_provider_for_panel(panel)
    text = f"🛰 اینباندهای <b>{panel.title}</b>\n"
    if not rows:
        if hasattr(client, "create_inbound"):
            text += "\n⚠️ اینباندی ثبت نشده. از «از پنل بخوان» یا «ساخت اینباند» استفاده کنید."
        else:
            text += "\n⚠️ اینباندی ثبت نشده. از «از پنل بخوان» استفاده کنید."
    await call.message.edit_text(
        text,
        reply_markup=kb.inbounds_list(panel.id, rows, panel.variant),
    )
    await call.answer()


@router.callback_query(kb.AdminCB.filter(F.action == "inb_fetch"))
async def inb_fetch(
    call: CallbackQuery, callback_data: kb.AdminCB, session: AsyncSession
) -> None:
    """همه اینباندهای موجود روی پنل را در ربات ثبت می‌کند."""
    panel = await ps.get_panel(session, callback_data.arg)
    if panel is None:
        await call.answer("پنل یافت نشد.", show_alert=True)
        return
    await call.answer("در حال خواندن پنل...")
    try:
        options = await ps.fetch_inbounds_from_panel(panel)
    except Exception as exc:  # noqa: BLE001
        await call.answer(f"🔴 {exc}"[:180], show_alert=True)
        return

    added = skipped = 0
    for item in options:
        row = await ps.register_inbound(
            session,
            panel,
            inbound_id=int(item.get("id") or 0),
            remark=str(item.get("remark") or ""),
            protocol=str(item.get("protocol") or ""),
            port=int(item.get("port") or 0),
            network=str(item.get("network") or ""),
            security=str(item.get("security") or ""),
        )
        if row is None:
            skipped += 1
        else:
            added += 1
    await call.answer(
        f"✅ {added} ثبت شد، {skipped} تکراری بود", show_alert=True
    )
    await inb_list(call, kb.AdminCB(action="inb_list", arg=panel.id), session)


@router.callback_query(kb.AdminCB.filter(F.action == "inb_view"))
async def inb_view(
    call: CallbackQuery, callback_data: kb.AdminCB, session: AsyncSession
) -> None:
    row = await session.get(PanelInbound, callback_data.arg)
    if row is None:
        await call.answer("اینباند یافت نشد.", show_alert=True)
        return
    panel = await session.get(Panel, row.panel_id)
    variant = panel.variant if panel else "xui3"
    state = "🟢" if row.is_active else "⚪️"
    text = (
        f"{state} <b>{row.remark or f'#{row.inbound_id}'}</b>\n"
        f"پنل: {panel.title if panel else '—'}\n"
        f"شناسه: <code>{row.inbound_id}</code>\n"
        f"پروتکل: <code>{row.protocol or '—'}</code>\n"
        f"پورت: <code>{row.port or '—'}</code>\n"
        f"شبکه: <code>{row.network or '—'}</code> | امنیت: "
        f"<code>{row.security or '—'}</code>"
    )
    if variant.strip().lower() not in {
        "xui3",
        "v3",
        "3.8",
        "3x",
        "mhsanaei3",
    }:
        text += "\n\n⚠️ در این نوع پنل، ساخت/حذف اینباند از ربات پشتیبانی نمی‌شود."
    await call.message.edit_text(
        text, reply_markup=kb.inbound_view(row.id, row.panel_id, variant)
    )
    await call.answer()

# ---------- ساخت اینباند ----------


@router.callback_query(kb.AdminCB.filter(F.action == "inb_add"))
async def inb_add(call: CallbackQuery, callback_data: kb.AdminCB, state: FSMContext) -> None:
    panel_id = callback_data.arg
    await state.set_state(AdminFlow.inbound_protocol)
    await state.update_data(panel_id=panel_id, step="proto")
    await call.message.answer(
        "🧪 ساخت اینباند جدید\n\nپروتکل را انتخاب کنید:",
        reply_markup=kb.inbound_protocol_choose(panel_id),
    )
    await call.answer()


@router.callback_query(kb.AdminCB.filter(F.action == "inb_proto"))
async def inb_proto(
    call: CallbackQuery, callback_data: kb.AdminCB, state: FSMContext
) -> None:
    panel_id = callback_data.arg
    await state.update_data(protocol=callback_data.field or "vless")
    await state.set_state(AdminFlow.inbound_network)
    await call.message.answer(
        "🌍 نوع انتقال (شبکه) را انتخاب کنید:", reply_markup=kb.inbound_network_choose(panel_id)
    )
    await call.answer()


@router.callback_query(kb.AdminCB.filter(F.action == "inb_net"))
async def inb_net(
    call: CallbackQuery, callback_data: kb.AdminCB, state: FSMContext
) -> None:
    panel_id = callback_data.arg
    await state.update_data(network=callback_data.field or "tcp")
    await state.set_state(AdminFlow.inbound_security)
    await call.message.answer(
        "🔐 امنیت اتصال را انتخاب کنید:", reply_markup=kb.inbound_security_choose(panel_id)
    )
    await call.answer()


@router.callback_query(kb.AdminCB.filter(F.action == "inb_sec"))
async def inb_sec(
    call: CallbackQuery, callback_data: kb.AdminCB, state: FSMContext
) -> None:
    await state.update_data(security=callback_data.field or "none")
    await state.set_state(AdminFlow.inbound_port)
    await call.message.answer(
        "🔢 شماره پورت را بفرستید (مثلاً 443):"
    )
    await call.answer()


@router.message(AdminFlow.inbound_port)
async def inbound_port(message: Message, state: FSMContext) -> None:
    raw = (message.text or "").strip()
    if not raw.isdigit() or not (1 <= int(raw) <= 65535):
        await message.answer("⚠️ پورت باید عدد بین ۱ تا ۶۵۵۳۵ باشد.")
        return
    await state.update_data(port=int(raw))
    await state.set_state(AdminFlow.inbound_remark)
    await message.answer(
        "عنوان اینباند را بفرستید (مثلاً «سرور آلمان — vless»):"
    )


@router.message(AdminFlow.inbound_remark)
async def inbound_remark(
    message: Message, session: AsyncSession, state: FSMContext
) -> None:
    await state.update_data(remark=(message.text or "").strip())
    data = await state.get_data()
    security = str(data.get("security", "none"))

    if security == "reality":
        await state.set_state(AdminFlow.inbound_extra)
        await message.answer(
            "🔗 Reality به دو مقدار نیاز دارد:\n\n"
            "۱) <code>dest</code> مثل <code>www.microsoft.com:443</code>\n"
            "۲) <code>serverNames</code> مثل <code>www.microsoft.com</code>\n\n"
            "هر دو را در دو خط جدا بفرستید."
        )
        return
    await _finish_inbound(message, session, state, data)


@router.message(AdminFlow.inbound_extra)
async def inbound_extra(
    message: Message, session: AsyncSession, state: FSMContext
) -> None:
    """دریافت dest و serverNames برای Reality."""
    text = (message.text or "").strip()
    lines = [x.strip() for x in text.replace("\r", "\n").split("\n") if x.strip()]
    if len(lines) < 2:
        await message.answer(
            "⚠️ لطفاً هر دو مقدار را در دو خط بفرستید:\n"
            "<code>www.microsoft.com:443</code>\n<code>www.microsoft.com</code>"
        )
        return
    data = await state.get_data()
    data["dest"] = lines[0]
    data["server_names"] = lines[1]
    await _finish_inbound(message, session, state, data)


async def _finish_inbound(
    message: Message,
    session: AsyncSession,
    state: FSMContext,
    data: dict,
) -> None:
    """ساخت اینباند روی پنل و ثبت آن در ربات."""
    panel = await ps.get_panel(session, int(data.get("panel_id") or 0))
    if panel is None:
        await message.answer("پنل یافت نشد.")
        await state.clear()
        return

    spec = {
        "protocol": data.get("protocol", "vless"),
        "network": data.get("network", "tcp"),
        "security": data.get("security", "none"),
        "port": data.get("port", 0),
        "remark": data.get("remark", ""),
        "dest": data.get("dest", ""),
        "server_names": data.get("server_names", ""),
        "path": data.get("path", "/"),
        "sni": data.get("sni", ""),
    }

    await message.answer("⏳ در حال ساخت اینباند روی پنل...")
    try:
        inbound_id = await ps.create_inbound_on_panel(panel, spec)
    except VpnError as exc:
        await message.answer(f"🔴 خطا: {exc}", reply_markup=kb.back_home())
        await state.clear()
        return
    except Exception as exc:  # noqa: BLE001
        logger.exception("create_inbound failed")
        await message.answer(
            f"🔴 {type(exc).__name__}: {exc}", reply_markup=kb.back_home()
        )
        await state.clear()
        return

    row = await ps.register_inbound(
        session,
        panel,
        inbound_id=inbound_id,
        remark=str(spec["remark"]),
        protocol=str(spec["protocol"]),
        port=int(spec["port"]),
        network=str(spec["network"]),
        security=str(spec["security"]),
    )
    await state.clear()

    if row is None:
        # تکراری؛ فقط از پنل بخوان
        await message.answer(
            f"✅ اینباند <code>{inbound_id}</code> ساخته شد "
            "(قبلاً ثبت شده بود).",
            reply_markup=kb.back_home(),
        )
        return

    await message.answer(
        f"✅ اینباند ساخته و ثبت شد.\n"
        f"شناسه: <code>{inbound_id}</code>\n"
        f"عنوان: {spec['remark']}\n"
        f"پروتکل: {spec['protocol']} | شبکه: {spec['network']} | "
        f"امنیت: {spec['security']}\n"
        f"پورت: {spec['port']}",
        reply_markup=kb.inbound_view(row.id, panel.id, panel.variant),
    )


@router.message(AdminFlow.inbound_network)
async def inbound_network_fallback(message: Message) -> None:
    await message.answer("لطفاً از دکمه‌های زیر انتخاب کنید.")

# ---------- مدیریت اینباند ثبت‌شده ----------


@router.callback_query(kb.AdminCB.filter(F.action == "inb_sync"))
async def inb_sync(
    call: CallbackQuery, callback_data: kb.AdminCB, session: AsyncSession
) -> None:
    row = await session.get(PanelInbound, callback_data.arg)
    if row is None:
        await call.answer("اینباند یافت نشد.", show_alert=True)
        return
    await ps.sync_inbound_meta(session, row)
    await call.answer("تازه شد.")
    await inb_view(call, kb.AdminCB(action="inb_view", arg=row.id), session)


@router.callback_query(kb.AdminCB.filter(F.action == "inb_toggle"))
async def inb_toggle(
    call: CallbackQuery, callback_data: kb.AdminCB, session: AsyncSession
) -> None:
    row = await session.get(PanelInbound, callback_data.arg)
    if row is None:
        await call.answer("اینباند یافت نشد.", show_alert=True)
        return
    row.is_active = not row.is_active
    await session.commit()
    await call.answer("تغییر کرد.")
    await inb_view(call, kb.AdminCB(action="inb_view", arg=row.id), session)


@router.callback_query(kb.AdminCB.filter(F.action == "inb_unreg_confirm"))
async def inb_unreg_confirm(
    call: CallbackQuery, callback_data: kb.AdminCB, session: AsyncSession
) -> None:
    row = await session.get(PanelInbound, callback_data.arg)
    if row is None:
        await call.answer("اینباند یافت نشد.", show_alert=True)
        return
    text = (
        f"اینباند <b>{row.remark or f'#{row.inbound_id}'}</b> فقط از ربات "
        "حذف شود؟\nروی پنل باقی می‌ماند."
    )
    await call.message.edit_text(
        text,
        reply_markup=kb.confirm(
            action="inb_unreg_yes", arg=row.id, back_action="inb_view"
        ),
    )
    await call.answer()


@router.callback_query(kb.AdminCB.filter(F.action == "inb_unreg_yes"))
async def inb_unreg_yes(
    call: CallbackQuery, callback_data: kb.AdminCB, session: AsyncSession
) -> None:
    row = await session.get(PanelInbound, callback_data.arg)
    if row is None:
        await call.answer("اینباند یافت نشد.", show_alert=True)
        return
    panel_id = row.panel_id
    await ps.unregister_inbound(session, row)
    await call.answer("حذف شد.")
    rows = await ps.list_inbounds_of(session, panel_id)
    panel = await session.get(Panel, panel_id)
    variant = panel.variant if panel else "xui3"
    await call.message.edit_text(
        f"🛰 اینباندهای پنل",
        reply_markup=kb.inbounds_list(panel_id, rows, variant),
    )


@router.callback_query(kb.AdminCB.filter(F.action == "inb_del_confirm"))
async def inb_del_confirm(
    call: CallbackQuery, callback_data: kb.AdminCB, session: AsyncSession
) -> None:
    row = await session.get(PanelInbound, callback_data.arg)
    if row is None:
        await call.answer("اینباند یافت نشد.", show_alert=True)
        return
    text = (
        f"⚠️ اینباند <b>{row.remark or f'#{row.inbound_id}'}</b> از روی "
        "<b>پنل</b> حذف شود؟\n"
        "همه کلاینت‌های آن هم حذف خواهند شد. این عملیات برگشت‌پذیر نیست."
    )
    await call.message.edit_text(
        text,
        reply_markup=kb.confirm(
            action="inb_del_yes", arg=row.id, back_action="inb_view"
        ),
    )
    await call.answer()


@router.callback_query(kb.AdminCB.filter(F.action == "inb_del_yes"))
async def inb_del_yes(
    call: CallbackQuery, callback_data: kb.AdminCB, session: AsyncSession
) -> None:
    row = await session.get(PanelInbound, callback_data.arg)
    if row is None:
        await call.answer("اینباند یافت نشد.", show_alert=True)
        return
    panel = await session.get(Panel, row.panel_id)
    inbound_id = row.inbound_id
    panel_id = row.panel_id
    if panel is None:
        await call.answer("پنل یافت نشد.", show_alert=True)
        return

    await call.answer("در حال حذف از پنل...")
    try:
        await ps.delete_inbound_from_panel(panel, inbound_id)
    except Exception as exc:  # noqa: BLE001
        logger.warning("delete_inbound %s failed: %s", inbound_id, exc)
        await call.answer(f"🔴 خطا: {exc}"[:180], show_alert=True)
        return

    await ps.unregister_inbound(session, row)
    rows = await ps.list_inbounds_of(session, panel_id)
    await call.message.edit_text(
        "🛰 اینباندهای پنل",
        reply_markup=kb.inbounds_list(panel_id, rows, panel.variant),
    )
