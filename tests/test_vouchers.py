"""Tests for VoucherRecord model."""

from tenbis.vouchers import VoucherRecord


def test_voucher_record_fields() -> None:
    r = VoucherRecord(
        barcode_number="913920508201984",
        amount=200.0,
        purchased_at="2026-04-19T09:00:00+03:00",
    )
    assert r.barcode_number == "913920508201984"
    assert r.amount == 200.0
    assert r.purchased_at.startswith("2026-04-19")


def test_voucher_record_order_id_default() -> None:
    r = VoucherRecord(
        barcode_number="000",
        amount=100.0,
        purchased_at="2026-04-20T09:00:00+03:00",
    )
    assert r.order_id == 0


def test_voucher_record_copy() -> None:
    r = VoucherRecord(
        barcode_number="123",
        amount=200.0,
        purchased_at="2026-04-20T09:00:00+03:00",
    )
    r2 = r.model_copy(update={"barcode_number": "456"})
    assert r2.barcode_number == "456"
    assert r2.amount == 200.0
