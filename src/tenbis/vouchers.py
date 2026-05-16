"""Voucher data model and pending-voucher disk storage."""

import re
from pathlib import Path

from pydantic import BaseModel


class VoucherRecord(BaseModel):
    barcode_number: str
    amount: float
    purchased_at: str  # ISO-8601 with timezone
    order_id: int = 0


class PendingVoucher(BaseModel):
    record: VoucherRecord
    json_path: Path
    image_path: Path


def pending_dir(data_dir: Path) -> Path:
    return data_dir / "vouchers" / "pending"


def voucher_stem(record: VoucherRecord) -> str:
    purchased = record.purchased_at[:16].replace("T", "_").replace(":", "-")
    barcode = re.sub(r"[^0-9A-Za-z-]", "", record.barcode_number) or "unknown"
    return f"{purchased}_{barcode}"


def save_pending_voucher(data_dir: Path, record: VoucherRecord, png_bytes: bytes) -> PendingVoucher:
    directory = pending_dir(data_dir)
    directory.mkdir(parents=True, exist_ok=True)
    stem = voucher_stem(record)
    image_path = directory / f"{stem}.png"
    json_path = directory / f"{stem}.json"
    image_path.write_bytes(png_bytes)
    json_path.write_text(record.model_dump_json(indent=2), encoding="utf-8")
    return PendingVoucher(record=record, json_path=json_path, image_path=image_path)


def list_pending_vouchers(data_dir: Path) -> list[PendingVoucher]:
    directory = pending_dir(data_dir)
    if not directory.exists():
        return []

    vouchers: list[PendingVoucher] = []
    for json_path in sorted(directory.glob("*.json")):
        image_path = json_path.with_suffix(".png")
        if not image_path.exists():
            continue
        record = VoucherRecord.model_validate_json(json_path.read_text(encoding="utf-8"))
        vouchers.append(PendingVoucher(record=record, json_path=json_path, image_path=image_path))
    return vouchers


def delete_pending_voucher(voucher: PendingVoucher) -> None:
    voucher.image_path.unlink(missing_ok=True)
    voucher.json_path.unlink(missing_ok=True)
