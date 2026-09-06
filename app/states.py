from __future__ import annotations

from aiogram.fsm.state import State, StatesGroup


class BuyFlow(StatesGroup):
    waiting_receipt = State()


class AdminFlow(StatesGroup):
    editing_setting = State()
    editing_image = State()
    duration_title = State()
    duration_days = State()
    package_field = State()
    reject_note = State()
    broadcast = State()
    user_lookup = State()
    gift_days = State()


class ActivitySearch(StatesGroup):
    waiting_user_id = State()
