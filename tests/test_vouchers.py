"""Tests for voucher filesystem helpers."""

import datetime as dt
from pathlib import Path

import pytest

from tenbis.vouchers import (
    VoucherRecord,
    _stem,
    load_pending_records,
    move_to_used,
    save_pending,
    today_voucher_exists,
    update_message_id,
)


@pytest.fixture()
def settings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Return a Settings object pointing at a temp directory."""
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    from tenbis.settings import Settings

    s = Settings()
    s.ensure_dirs()
    return s


def _make_record() -> VoucherRecord:
    return VoucherRecord(
        barcode_number="913920508201984",
        amount=200.0,
        purchased_at="2026-04-19T09:00:00+03:00",
        whatsapp_group="Vouchers",
    )


def test_stem():
    assert _stem("123", "2026-04-19T09:00:00+03:00") == "2026-04-19_09-00_123"


def test_save_and_load_pending(settings):
    record = _make_record()
    png_path = save_pending(record, b"\x89PNG\r\n", settings)
    assert png_path.exists()
    assert png_path.with_suffix(".json").exists()


def test_today_voucher_exists_pending(settings):
    record = _make_record()
    # Patch purchased_at to today
    today = dt.date.today().isoformat()
    record = record.model_copy(update={"purchased_at": f"{today}T09:00:00+03:00"})
    save_pending(record, b"PNG", settings)
    assert today_voucher_exists(settings)


def test_today_voucher_exists_false(settings):
    assert not today_voucher_exists(settings)


def test_update_message_id(settings):
    record = _make_record()
    png_path = save_pending(record, b"PNG", settings)
    update_message_id(png_path, "true_abc123")
    records = load_pending_records(settings)
    assert len(records) == 1
    assert records[0][1].whatsapp_message_id == "true_abc123"


def test_move_to_used(settings):
    record = _make_record()
    png_path = save_pending(record, b"PNG", settings)
    new_path = move_to_used(png_path, settings)
    assert new_path.exists()
    assert not png_path.exists()
    assert new_path.parent == settings.used_dir


def test_load_pending_only_with_message_id(settings):
    record = _make_record()
    png_path = save_pending(record, b"PNG", settings)
    # No message_id yet — should not appear in results
    assert load_pending_records(settings) == []
    update_message_id(png_path, "msg1")
    results = load_pending_records(settings)
    assert len(results) == 1
