"""Voucher lifecycle: Pydantic models + pending/used filesystem management."""

import datetime as dt
import json
import shutil
from pathlib import Path

from pydantic import BaseModel

from tenbis.settings import Settings


class VoucherRecord(BaseModel):
    barcode_number: str
    amount: float
    purchased_at: str  # ISO-8601 with timezone
    whatsapp_group: str
    whatsapp_message_id: str = ""  # filled after send
    order_id: int = 0


def _stem(barcode_number: str, purchased_at: str) -> str:
    """Build the filename stem shared by .png and .json."""
    ts = purchased_at[:16].replace(":", "-").replace("T", "_")  # 2026-04-19_14-59
    return f"{ts}_{barcode_number}"


def save_pending(record: VoucherRecord, png_bytes: bytes, settings: Settings) -> Path:
    """Write <stem>.png and <stem>.json to pending/. Returns the PNG path."""
    settings.pending_dir.mkdir(parents=True, exist_ok=True)
    stem = _stem(record.barcode_number, record.purchased_at)
    png_path = settings.pending_dir / f"{stem}.png"
    json_path = settings.pending_dir / f"{stem}.json"
    png_path.write_bytes(png_bytes)
    json_path.write_text(record.model_dump_json(indent=2), encoding="utf-8")
    return png_path


def update_message_id(png_path: Path, message_id: str) -> None:
    """Patch the sidecar JSON with the WhatsApp message id after sending."""
    json_path = png_path.with_suffix(".json")
    if not json_path.exists():
        return
    data = json.loads(json_path.read_text(encoding="utf-8"))
    data["whatsapp_message_id"] = message_id
    json_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def move_to_used(png_path: Path, settings: Settings) -> Path:
    """Move the .png + .json pair from pending/ to used/. Returns new PNG path."""
    settings.used_dir.mkdir(parents=True, exist_ok=True)
    new_png = settings.used_dir / png_path.name
    shutil.move(str(png_path), new_png)
    json_path = png_path.with_suffix(".json")
    if json_path.exists():
        shutil.move(str(json_path), settings.used_dir / json_path.name)
    return new_png


def today_voucher_exists(settings: Settings) -> bool:
    """Return True if a voucher (pending or used) was already purchased today."""
    today = dt.date.today().isoformat()  # e.g. "2026-04-19"
    for directory in (settings.pending_dir, settings.used_dir):
        if directory.exists() and any(p.name.startswith(today) for p in directory.glob("*.png")):
            return True
    return False


def tracked_message_ids(settings: Settings) -> set[str]:
    """Return all whatsapp_message_ids already in pending/ or used/."""
    ids: set[str] = set()
    for directory in (settings.pending_dir, settings.used_dir):
        if not directory.exists():
            continue
        for json_path in directory.glob("*.json"):
            try:
                record = VoucherRecord.model_validate_json(json_path.read_text(encoding="utf-8"))
                if record.whatsapp_message_id:
                    ids.add(record.whatsapp_message_id)
            except Exception:
                pass
    return ids


def save_imported(record: VoucherRecord, settings: Settings) -> Path:
    """Write a stub .png + .json to pending/ for an imported voucher. Returns the PNG path."""
    settings.pending_dir.mkdir(parents=True, exist_ok=True)
    stem = _stem(record.barcode_number, record.purchased_at)
    png_path = settings.pending_dir / f"{stem}.png"
    json_path = settings.pending_dir / f"{stem}.json"
    # 1×1 transparent PNG as placeholder — the real image lives in WhatsApp
    png_path.write_bytes(
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
        b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01"
        b"\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
    )
    json_path.write_text(record.model_dump_json(indent=2), encoding="utf-8")
    return png_path


def load_pending_records(settings: Settings) -> list[tuple[Path, VoucherRecord]]:
    """Return all (png_path, VoucherRecord) pairs from pending/ that have a message_id."""
    results = []
    if not settings.pending_dir.exists():
        return results
    for json_path in sorted(settings.pending_dir.glob("*.json")):
        record = VoucherRecord.model_validate_json(json_path.read_text(encoding="utf-8"))
        if record.whatsapp_message_id:
            png_path = json_path.with_suffix(".png")
            results.append((png_path, record))
    return results
