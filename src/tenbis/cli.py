"""CLI entrypoint — all commands in one place.

Use `mise run <task>` for the canonical interface; the commands below are what each task calls.
"""

import sys
import tempfile
from pathlib import Path

import typer
from playwright.sync_api import Page

from tenbis import tenbis_flow, whatsapp
from tenbis.browser import tenbis_context, whatsapp_context
from tenbis.logger import logger, setup_logger
from tenbis.settings import Settings
from tenbis.vouchers import VoucherRecord

app = typer.Typer(help="10bis → Shufersal voucher automation", add_completion=False)


def load_settings() -> Settings:
    s = Settings()
    s.ensure_dirs()
    setup_logger(s.debug, s.log_format)
    return s


def make_caption(record: VoucherRecord) -> str:
    date = record.purchased_at[:10]  # "2026-04-20"
    return f"Shufersal voucher ₪{record.amount:.0f} | {record.barcode_number} | {date}"


# ── auth commands ─────────────────────────────────────────────────────────────


@app.command("login-tenbis")
def login_tenbis() -> None:
    """Open a headed browser and log in to 10bis (run on your laptop)."""
    s = Settings()
    s.ensure_dirs()
    setup_logger(debug=True, log_format=s.log_format)
    with tenbis_context(s.tenbis_profile_dir, headless=False, debug_dir=s.debug_dir) as (_, page):
        tenbis_flow.do_login(page, s.tenbis_email)
    typer.echo("10bis session saved. Run 'mise run sync:profiles' to copy to the server.")


@app.command("login-whatsapp")
def login_whatsapp() -> None:
    """Open a headed browser and log in to WhatsApp Web via QR code (run on your laptop)."""
    s = Settings()
    s.ensure_dirs()
    setup_logger(debug=True, log_format=s.log_format)
    with whatsapp_context(s.whatsapp_profile_dir, headless=False, debug_dir=s.debug_dir) as (
        _,
        page,
    ):
        whatsapp.do_login(page)
    typer.echo("WhatsApp session saved. Run 'mise run sync:profiles' to copy to the server.")


# ── inspection commands ───────────────────────────────────────────────────────


@app.command()
def budget() -> None:
    """Print the current 10bis monthly balance and daily remaining."""
    s = load_settings()
    with tenbis_context(s.tenbis_profile_dir, s.headless, s.debug_dir) as (_, page):
        tenbis_flow.check_auth(page)
        monthly, daily_remaining = tenbis_flow.get_budget(page, s.tenbis_daily_limit, s.tz)
    typer.echo(f"Monthly balance: ₪{monthly:.0f}  |  Daily remaining: ₪{daily_remaining:.0f}")


@app.command("list-vouchers")
def list_vouchers() -> None:
    """Scan the WhatsApp group and show active / acknowledged vouchers."""
    s = load_settings()
    with whatsapp_context(s.whatsapp_profile_dir, s.headless, s.debug_dir) as (_, page):
        whatsapp.check_auth(page)
        whatsapp.open_group(page, s.whatsapp_group_name)
        msgs = whatsapp.scan_voucher_messages(page)

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
    s = load_settings()

    png_bytes, record = do_purchase(s)
    if png_bytes is None or record is None:
        raise typer.Exit(0)

    _, tmp_path = tempfile.mkstemp(suffix=".png")
    tmp = Path(tmp_path)
    tmp.write_bytes(png_bytes)
    try:
        caption = make_caption(record)
        with whatsapp_context(s.whatsapp_profile_dir, s.headless, s.debug_dir) as (_, page):
            whatsapp.check_auth(page)
            whatsapp.send_barcode(page, tmp, caption, s.whatsapp_group_name)
        logger.info("voucher_sent", caption=caption)
        typer.echo(f"Sent: {caption}")
    finally:
        tmp.unlink(missing_ok=True)


# ── scan reactions command ────────────────────────────────────────────────────


@app.command("scan-reactions")
def scan_reactions() -> None:
    """Scan WhatsApp for used vouchers (any user reaction) and acknowledge with 🤖."""
    s = load_settings()
    with whatsapp_context(s.whatsapp_profile_dir, s.headless, s.debug_dir) as (_, page):
        whatsapp.check_auth(page)
        whatsapp.open_group(page, s.whatsapp_group_name)
        acked = ack_used_vouchers(page)
        msgs = whatsapp.scan_voucher_messages(page)

    active = sum(1 for m in msgs if not m.user_reacted)
    typer.echo(f"Active: {active}  Just acknowledged: {acked}  Total scanned: {len(msgs)}")


# ── full daily pipeline ───────────────────────────────────────────────────────


@app.command()
def run() -> None:
    """Full daily pipeline: scan reactions → purchase → send to WhatsApp.

    Idempotent: if a voucher was already sent today it exits early.

    Each browser (WhatsApp, 10bis) is opened in its own sequential sync_playwright
    context — Playwright forbids nesting two sync contexts inside each other.
    """
    s = load_settings()

    # ── Step 1 & 2: WhatsApp — ack used vouchers + idempotency check ──────────
    error_text: str | None = None
    with whatsapp_context(s.whatsapp_profile_dir, s.headless, s.debug_dir) as (_, wa_page):
        try:
            whatsapp.check_auth(wa_page)
            whatsapp.open_group(wa_page, s.whatsapp_group_name)
        except whatsapp.WAAuthExpiredError as exc:
            logger.error("whatsapp_auth_expired")
            typer.echo(f"WhatsApp session expired: {exc}", err=True)
            sys.exit(1)

        try:
            ack_used_vouchers(wa_page)
        except Exception:
            logger.exception("ack_failed")  # non-fatal

        if whatsapp.sent_today(wa_page, s.tz):
            logger.info("already_sent_today")
            typer.echo("Already sent a voucher today. Nothing to do.")
            raise typer.Exit(0)

    # ── Step 3: 10bis — purchase (separate playwright context) ────────────────
    png_bytes: bytes | None = None
    record = None
    try:
        png_bytes, record = do_purchase(s)
    except tenbis_flow.AuthExpiredError as exc:
        logger.error("tenbis_auth_expired")
        error_text = (
            f"10bis session expired — run `mise run login:tenbis` on your laptop "
            f"then `mise run sync:profiles`\n\nDetails: {exc}"
        )
    except Exception as exc:
        logger.exception("purchase_failed")
        error_text = f"Purchase failed: {exc}"

    if error_text:
        with whatsapp_context(s.whatsapp_profile_dir, s.headless, s.debug_dir) as (_, wa_page):
            whatsapp.send_text(wa_page, f"⚠️ {error_text}", s.whatsapp_group_name)
        sys.exit(1)

    if png_bytes is None or record is None:
        raise typer.Exit(0)  # budget too low — already logged

    # ── Step 4: WhatsApp — send barcode ───────────────────────────────────────
    _, tmp_path = tempfile.mkstemp(suffix=".png")
    tmp = Path(tmp_path)
    tmp.write_bytes(png_bytes)
    try:
        caption = make_caption(record)
        with whatsapp_context(s.whatsapp_profile_dir, s.headless, s.debug_dir) as (_, wa_page):
            whatsapp.send_barcode(wa_page, tmp, caption, s.whatsapp_group_name)
        logger.info("daily_run_complete", caption=caption)
        typer.echo("Daily run complete.")
    except Exception as exc:
        logger.exception("send_failed")
        typer.echo(f"WA send failed: {exc}", err=True)
        sys.exit(1)
    finally:
        tmp.unlink(missing_ok=True)


# ── helpers ───────────────────────────────────────────────────────────────────


def ack_used_vouchers(wa_page: Page) -> int:
    """React with BOT_REACTION to any voucher that has user reactions but no bot ack.

    Returns the count of newly acknowledged messages.
    """
    msgs = whatsapp.scan_voucher_messages(wa_page)
    count = 0
    for msg in msgs:
        if msg.user_reacted and not msg.bot_acked:
            whatsapp.react_to_message(wa_page, msg.message_id, whatsapp.BOT_REACTION)
            logger.info("voucher_acked", caption=msg.caption)
            count += 1
    return count


def do_purchase(s: Settings) -> tuple[bytes | None, VoucherRecord | None]:
    """Run the 10bis purchase flow. Returns (png_bytes, record) or (None, None) if skipped."""
    with tenbis_context(s.tenbis_profile_dir, s.headless, s.debug_dir) as (_, page):
        tenbis_flow.check_auth(page)
        monthly, daily_remaining = tenbis_flow.get_budget(page, s.tenbis_daily_limit, s.tz)

        if monthly < s.tenbis_min_monthly_balance or daily_remaining < s.item.amount:
            logger.warning(
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
            png_bytes, record = tenbis_flow.purchase_voucher(
                page,
                item_url=s.item.url,
                amount=s.item.amount,
                tz=s.tz,
                dry_run=s.dry_run,
            )
        except RuntimeError as exc:
            if s.dry_run:
                typer.echo(f"Dry run complete: {exc}")
                return None, None
            raise

    logger.info("voucher_purchased", barcode=record.barcode_number, amount=record.amount)
    return png_bytes, record
