from __future__ import annotations

from types import SimpleNamespace

import pytest

from stock_news_bot.cogs.admin import _check_admin, is_admin
from stock_news_bot.utils.errors import AdminPermissionError


def _fake_bot(admin_ids: list[int]):
    return SimpleNamespace(settings=SimpleNamespace(discord_admin_user_ids=admin_ids))


def test_is_admin_true_for_listed_user():
    bot = _fake_bot([111, 222])
    assert is_admin(bot, 111) is True


def test_is_admin_false_for_unlisted_user():
    bot = _fake_bot([111, 222])
    assert is_admin(bot, 999) is False


def test_check_admin_raises_for_non_admin():
    bot = _fake_bot([111])
    fake_user = SimpleNamespace(id=999)
    interaction = SimpleNamespace(client=bot, user=fake_user)
    with pytest.raises(AdminPermissionError):
        _check_admin(interaction)


def test_check_admin_passes_for_admin():
    bot = _fake_bot([111])
    fake_user = SimpleNamespace(id=111)
    interaction = SimpleNamespace(client=bot, user=fake_user)
    _check_admin(interaction)  # 예외 없이 통과해야 함
