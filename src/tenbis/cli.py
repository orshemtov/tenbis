"""CLI entrypoint — all commands in one place.

Use `mise run <task>` for the canonical interface; the commands below are what each task calls.
"""

import sys
import tempfile
from pathlib import Path

import typer

from tenbis import tenbis_flow, whatsapp
from tenbis.browser import tenbis_context, whatsapp_context
from tenbis.logger import get_logger, setup_logger
from tenbis.settings import Settings
from tenbis.vouchers import VoucherRecord

app = typer.Typer(help="10bis → Shufersal voucher automation", add_completion=False)


def _settings() -> Settings:
    s = Settings()
    s.ensure_dirs()
    setup_logger(s.debug, s.log_format)
    return s


def _make_caption(record: VoucherRecord) -> str:
    date = record.purchased_at[:10]  # "2026-04-20"
    return f"Shufersal voucher ₪{record.amount:.0f} | {record.barcode_number} | {date}"


# ── auth commands ─────────────────────────────────────────────────────────────


@app.command("login-tenbis")
def login_tenbis() -> None:
    """Open a headed browser and log in to 10bis (run on your laptop)."""
    s = Settings()
    s.ensure_dirs()
    s.headless = False
    setup_logger(debug=True, log_format=s.log_format)
    with tenbis_context(s) as (_, page):
        tenbis_flow.do_login(page, s.tenbis_email)
    typer.echo("10bis session saved. Run 'mise run sync:profiles' to copy to the server.")


@app.command("login-whatsapp")
def login_whatsapp() -> None:
    """Open a headed browser and log in to WhatsApp Web via QR code (run on your laptop)."""
    s = Settings()
    s.ensure_dirs()
    s.headless = False
    setup_logger(debug=True, log_format=s.log_format)
    with whatsapp_context(s) as (_, page):
        whatsapp.do_login(page)
    typer.echo("WhatsApp session saved. Run 'mise run sync:profiles' to copy to the server.")


# ── inspection commands ───────────────────────────────────────────────────────


@app.command()
def budget() -> None:
    """Print the current 10bis monthly balance and daily remaining."""
    s = _settings()
    with tenbis_context(s) as (_, page):
        tenbis_flow.check_auth(page)
        monthly, daily_remaining = tenbis_flow.get_budget(page, s.tenbis_daily_limit)
    typer.echo(f"Monthly balance: ₪{monthly:.0f}  |  Daily remaining: ₪{daily_remaining:.0f}")


@app.command("list-vouchers")
def list_vouchers() -> None:
    """Scan the WhatsApp group and show active / acknowledged vouchers."""
    s = _settings()
    with whatsapp_context(s) as (_, page):
        whatsapp.check_auth(page)
        whatsapp.open_group(page, s.whatsapp_group_name)
        msgs = whatsapp.scan_voucher_messages(page, s)

    if not msgs:
        typer.echo("No voucher messages found in the group.")
        return

    active = [m for m in msgs if not m.user_reacted]
    used_pending = [m for m in msgs if m.user_reacted and not m.bot_acked]
    acked = [m for m in msgs if m.bot_acked]

    if active:
        typer.echo(f"Active ({len(active)}):")
        for m in active:
            typer.echo(f"  {m.caption}")
    if used_pending:
        typer.echo(f"Used — pending bot ack ({len(used_pending)}):")
        for m in used_pending:
            typer.echo(f"  {m.caption}")
    if acked:
        typer.echo(f"Acknowledged ({len(acked)}):")
        for m in acked:
            typer.echo(f"  {m.caption}")


# ── purchase command ──────────────────────────────────────────────────────────


@app.command()
def purchase() -> None:
    """Purchase a Shufersal voucher and send it to the WhatsApp group immediately.

    Set DRY_RUN=true to rehearse without placing the order.
    """
    s = _settings()
    log = get_logger(dry_run=s.dry_run)

    png_bytes, record = _do_purchase(s)
    if png_bytes is None or record is None:
        raise typer.Exit(0)

    tmp = Path(tempfile.mktemp(suffix=".png"))
    tmp.write_bytes(png_bytes)
    try:
        caption = _make_caption(record)
        with whatsapp_context(s) as (_, page):
            whatsapp.check_auth(page)
            whatsapp.send_barcode(page, tmp, caption, s)
        log.info("voucher_sent", caption=caption)
        typer.echo(f"Sent: {caption}")
    finally:
        tmp.unlink(missing_ok=True)


# ── scan reactions command ────────────────────────────────────────────────────


@app.command("scan-reactions")
def scan_reactions() -> None:
    """Scan WhatsApp for used vouchers (any user reaction) and acknowledge with 🤖."""
    s = _settings()
    with whatsapp_context(s) as (_, page):
        whatsapp.check_auth(page)
        whatsapp.open_group(page, s.whatsapp_group_name)
        acked = _ack_used_vouchers(page, s)
        msgs = whatsapp.scan_voucher_messages(page, s)

    active = sum(1 for m in msgs if not m.user_reacted)
    typer.echo(f"Active: {active}  Just acknowledged: {acked}  Total scanned: {len(msgs)}")


# ── full daily pipeline ───────────────────────────────────────────────────────


@app.command()
def run() -> None:
    """Full daily pipeline: scan reactions → purchase → send to WhatsApp.

    Idempotent: if a voucher was already sent today it exits early.
    """
    s = _settings()
    log = get_logger()

    with whatsapp_context(s) as (_, wa_page):
        try:
            whatsapp.check_auth(wa_page)
            whatsapp.open_group(wa_page, s.whatsapp_group_name)
        except whatsapp.WAAuthExpiredError as exc:
            log.error("whatsapp_auth_expired")
            typer.echo(f"⚠️ WhatsApp session expired: {exc}", err=True)
            sys.exit(1)

        # Step 1: acknowledge any newly-used vouchers
        try:
            _ack_used_vouchers(wa_page, s)
        except Exception as exc:
            log.exception("ack_failed")
            # Non-fatal — continue

        # Step 2: idempotency check
        if whatsapp.sent_today(wa_page, s):
            log.info("already_sent_today")
            typer.echo("Already sent a voucher today. Nothing to do.")
            raise typer.Exit(0)

        # Step 3: purchase (separate 10bis browser context)
        try:
            png_bytes, record = _do_purchase(s)
        except tenbis_flow.AuthExpiredError as exc:
            log.error("tenbis_auth_expired")
            whatsapp.send_text(
                wa_page,
                f"⚠️ 10bis session expired — run `mise run login:tenbis` on your laptop "
                f"then `mise run sync:profiles`\n\nDetails: {exc}",
                s,
            )
            sys.exit(1)
        except Exception as exc:
            log.exception("purchase_failed")
            whatsapp.send_text(wa_page, f"⚠️ Purchase failed: {exc}", s)
            sys.exit(1)

        if png_bytes is None or record is None:
            # Budget too low — already logged inside _do_purchase
            raise typer.Exit(0)

        # Step 4: send via the already-open WA context
        tmp = Path(tempfile.mktemp(suffix=".png"))
        tmp.write_bytes(png_bytes)
        try:
            caption = _make_caption(record)
            whatsapp.send_barcode(wa_page, tmp, caption, s)
            log.info("daily_run_complete", caption=caption)
        except Exception as exc:
            log.exception("send_failed")
            typer.echo(f"⚠️ WA send failed: {exc}", err=True)
            sys.exit(1)
        finally:
            tmp.unlink(missing_ok=True)

    typer.echo("Daily run complete.")


# ── internal helpers ──────────────────────────────────────────────────────────


def _ack_used_vouchers(wa_page, s: Settings) -> int:
    """React with BOT_REACTION to any voucher that has user reactions but no bot ack.

    Returns the count of newly acknowledged messages.
    """
    msgs = whatsapp.scan_voucher_messages(wa_page, s)
    count = 0
    for msg in msgs:
        if msg.user_reacted and not msg.bot_acked:
            whatsapp.react_to_message(wa_page, msg.message_id, whatsapp.BOT_REACTION)
            get_logger().info("voucher_acked", caption=msg.caption)
            count += 1
    return count


def _do_purchase(s: Settings) -> tuple[bytes | None, VoucherRecord | None]:
    """Run the 10bis purchase flow. Returns (png_bytes, record) or (None, None) if skipped."""
    log = get_logger(dry_run=s.dry_run)

    with tenbis_context(s) as (_, page):
        tenbis_flow.check_auth(page)
        monthly, daily_remaining = tenbis_flow.get_budget(page, s.tenbis_daily_limit)

        if monthly < s.tenbis_min_monthly_balance or daily_remaining < s.item.amount:
            log.warning(
                "budget_too_low",
                monthly=monthly,
                daily_remaining=daily_remaining,
                required=s.item.amount,
            )
            typer.echo(
                f"Budget too low (monthly=₪{monthly:.0f} daily_remaining=₪{daily_remaining:.0f}). "
                f"Required: ₪{s.item.amount:.0f}. Skipping.",
                err=True,
            )
            return None, None

        try:
            png_bytes, record = tenbis_flow.purchase_voucher(page, s)
        except RuntimeError as exc:
            if s.dry_run:
                typer.echo(f"Dry run complete: {exc}")
                return None, None
            raise

    log.info("voucher_purchased", barcode=record.barcode_number, amount=record.amount)
    return png_bytes, record
