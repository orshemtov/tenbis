"""CLI entrypoint — all commands in one place.

Use `mise run <task>` for the canonical interface; the commands below are what each task calls.
"""

import sys
from pathlib import Path

import typer

from tenbis import tenbis_flow, whatsapp
from tenbis.browser import tenbis_context, whatsapp_context
from tenbis.logger import get_logger, setup_logger
from tenbis.settings import Settings
from tenbis.vouchers import (
    load_pending_records,
    move_to_used,
    save_pending,
    today_voucher_exists,
    update_message_id,
)

app = typer.Typer(help="10bis → Shufersal voucher automation", add_completion=False)


def _settings() -> Settings:
    s = Settings()
    s.ensure_dirs()
    setup_logger(s.debug)
    return s


# ── auth commands ─────────────────────────────────────────────────────────────


@app.command("login-tenbis")
def login_tenbis() -> None:
    """Open a headed browser and log in to 10bis (run on your laptop)."""
    s = Settings()
    s.ensure_dirs()
    s.headless = False  # always headed for interactive login
    setup_logger(debug=True)
    with tenbis_context(s) as (_, page):
        tenbis_flow.do_login(page, s.tenbis_email)
    typer.echo("10bis session saved. Run 'mise run sync:profiles' to copy to the server.")


@app.command("login-whatsapp")
def login_whatsapp() -> None:
    """Open a headed browser and log in to WhatsApp Web via QR code (run on your laptop)."""
    s = Settings()
    s.ensure_dirs()
    s.headless = False  # always headed for interactive login
    setup_logger(debug=True)
    with whatsapp_context(s) as (_, page):
        whatsapp.do_login(page)
    typer.echo("WhatsApp session saved. Run 'mise run sync:profiles' to copy to the server.")


# ── inspection commands ───────────────────────────────────────────────────────


@app.command()
def budget() -> None:
    """Print the current 10bis monthly balance."""
    s = _settings()
    with tenbis_context(s) as (_, page):
        tenbis_flow.check_auth(page)
        monthly = tenbis_flow.get_budget(page)
    typer.echo(f"Monthly balance: ₪{monthly:.0f}")


# ── purchase command ──────────────────────────────────────────────────────────


@app.command()
def purchase() -> None:
    """Purchase a Shufersal voucher and save it to data/vouchers/pending/.

    Set DRY_RUN=true to do a full rehearsal without placing the order.
    """
    s = _settings()
    log = get_logger(dry_run=s.dry_run)

    with tenbis_context(s) as (_, page):
        tenbis_flow.check_auth(page)
        monthly = tenbis_flow.get_budget(page)

        if monthly < s.tenbis_min_monthly_balance:
            log.warning(
                "budget_too_low",
                monthly=monthly,
                required=s.tenbis_item_price,
            )
            typer.echo(
                f"Budget too low (monthly=₪{monthly:.0f}). "
                f"Required: ₪{s.tenbis_item_price:.0f}. Nothing purchased.",
                err=True,
            )
            raise typer.Exit(0)

        try:
            png_bytes, record = tenbis_flow.purchase_voucher(page, s)
        except RuntimeError as exc:
            if s.dry_run:
                typer.echo(f"Dry run complete: {exc}")
                raise typer.Exit(0)
            raise

    png_path = save_pending(record, png_bytes, s)
    log.info("voucher_saved", path=str(png_path))
    typer.echo(f"Voucher saved: {png_path}")


# ── send command ──────────────────────────────────────────────────────────────


@app.command("send-pending")
def send_pending() -> None:
    """Send any vouchers in pending/ that haven't been sent to WhatsApp yet."""
    s = _settings()
    log = get_logger()

    # Find pending vouchers without a message_id yet
    if not s.pending_dir.exists():
        typer.echo("No pending vouchers.")
        return

    sent = 0
    with whatsapp_context(s) as (_, page):
        whatsapp.check_auth(page)

        for json_path in sorted(s.pending_dir.glob("*.json")):
            from tenbis.vouchers import VoucherRecord

            record = VoucherRecord.model_validate_json(json_path.read_text(encoding="utf-8"))
            if record.whatsapp_message_id:
                continue  # already sent

            png_path = json_path.with_suffix(".png")
            if not png_path.exists():
                log.warning("png_missing", json=str(json_path))
                continue

            caption = f"Shufersal voucher ₪{record.amount:.0f} | {record.barcode_number}"
            msg_id = whatsapp.send_barcode(page, png_path, caption, s)
            update_message_id(png_path, msg_id)
            sent += 1
            log.info("voucher_sent", png=str(png_path), message_id=msg_id)

    typer.echo(f"Sent {sent} voucher(s) to {s.whatsapp_group_name}.")


# ── scan reactions command ────────────────────────────────────────────────────


@app.command("scan-reactions")
def scan_reactions() -> None:
    """Check pending vouchers for WhatsApp reactions; move reacted ones to used/."""
    s = _settings()
    log = get_logger()

    records = load_pending_records(s)
    if not records:
        log.info("no_pending_vouchers")
        typer.echo("No pending vouchers to scan.")
        return

    moved = 0
    with whatsapp_context(s) as (_, page):
        whatsapp.check_auth(page)
        # Open the group first so messages are visible
        page.click(whatsapp.selectors.WHATSAPP_SEARCH_BOX, timeout=10_000)
        page.wait_for_timeout(500)
        page.locator(whatsapp.selectors.WHATSAPP_SEARCH_INPUT).fill(s.whatsapp_group_name)
        page.wait_for_timeout(1_500)
        titles = page.locator(whatsapp.selectors.WHATSAPP_CHAT_RESULT_TITLE)
        for i in range(titles.count()):
            if (titles.nth(i).get_attribute("title") or "").strip() == s.whatsapp_group_name:
                titles.nth(i).click()
                break
        page.wait_for_timeout(2_000)

        for png_path, record in records:
            if whatsapp.has_reaction(page, record.whatsapp_message_id):
                new_path = move_to_used(png_path, s)
                moved += 1
                log.info("voucher_used", old=str(png_path), new=str(new_path))

    typer.echo(f"Scanned {len(records)} voucher(s). Moved {moved} to used/.")


# ── full daily pipeline ───────────────────────────────────────────────────────


@app.command()
def run() -> None:
    """Full daily pipeline: scan reactions → purchase → send to WhatsApp.

    This is what the systemd timer calls at 09:00 every day. It is idempotent:
    running it twice in a day will skip the purchase on the second call.
    """
    s = _settings()
    log = get_logger()

    # Step 1: scan reactions (move used vouchers)
    try:
        _run_scan_reactions(s)
    except Exception as exc:
        log.exception("scan_reactions_failed")
        _alert(s, f"scan-reactions failed: {exc}")
        # Not fatal — continue with purchase

    # Step 2: idempotency check
    if today_voucher_exists(s):
        log.info("already_purchased_today")
        typer.echo("Already purchased a voucher today. Nothing to do.")
        raise typer.Exit(0)

    # Step 3: purchase
    try:
        png_path = _run_purchase(s)
    except tenbis_flow.AuthExpiredError as exc:
        log.error("tenbis_auth_expired")
        _alert(
            s,
            f"⚠️ 10bis session expired — run `mise run login:tenbis` on your laptop then `mise run sync:profiles`\n\nDetails: {exc}",  # noqa: E501
        )
        sys.exit(1)
    except Exception as exc:
        log.exception("purchase_failed")
        _alert(s, f"⚠️ Purchase failed: {exc}")
        sys.exit(1)

    if png_path is None:
        # Budget too low — already logged inside _run_purchase
        raise typer.Exit(0)

    # Step 4: send to WhatsApp
    try:
        _run_send(s, png_path)
    except whatsapp.WAAuthExpiredError as exc:
        log.error("whatsapp_auth_expired")
        # Can't alert via WA — just log
        typer.echo(f"⚠️ WhatsApp session expired: {exc}", err=True)
        sys.exit(1)
    except Exception as exc:
        log.exception("send_failed")
        _alert(s, f"⚠️ Send to WhatsApp failed: {exc}")
        sys.exit(1)

    typer.echo("Daily run complete.")


# ── internal pipeline helpers ─────────────────────────────────────────────────


def _run_scan_reactions(s: Settings) -> None:
    records = load_pending_records(s)
    if not records:
        return
    with whatsapp_context(s) as (_, page):
        whatsapp.check_auth(page)
        page.click(whatsapp.selectors.WHATSAPP_SEARCH_BOX, timeout=10_000)
        page.wait_for_timeout(500)
        page.locator(whatsapp.selectors.WHATSAPP_SEARCH_INPUT).fill(s.whatsapp_group_name)
        page.wait_for_timeout(1_500)
        titles = page.locator(whatsapp.selectors.WHATSAPP_CHAT_RESULT_TITLE)
        for i in range(titles.count()):
            if (titles.nth(i).get_attribute("title") or "").strip() == s.whatsapp_group_name:
                titles.nth(i).click()
                break
        page.wait_for_timeout(2_000)
        for png_path, record in records:
            if whatsapp.has_reaction(page, record.whatsapp_message_id):
                move_to_used(png_path, s)
                get_logger().info("voucher_used", png=str(png_path))


def _run_purchase(s: Settings) -> Path | None:
    """Return the PNG path on success, None if budget is too low."""
    with tenbis_context(s) as (_, page):
        tenbis_flow.check_auth(page)
        monthly = tenbis_flow.get_budget(page)

        if monthly < s.tenbis_min_monthly_balance:
            get_logger(monthly=monthly).warning("budget_too_low")
            typer.echo(
                f"Budget too low (monthly=₪{monthly:.0f}). Skipping.",
                err=True,
            )
            return None

        png_bytes, record = tenbis_flow.purchase_voucher(page, s)

    return save_pending(record, png_bytes, s)


def _run_send(s: Settings, png_path: Path) -> None:
    from tenbis.vouchers import VoucherRecord

    json_path = png_path.with_suffix(".json")
    record = VoucherRecord.model_validate_json(json_path.read_text(encoding="utf-8"))
    caption = f"Shufersal voucher ₪{record.amount:.0f} | {record.barcode_number}"

    with whatsapp_context(s) as (_, page):
        whatsapp.check_auth(page)
        msg_id = whatsapp.send_barcode(page, png_path, caption, s)
        update_message_id(png_path, msg_id)


def _alert(s: Settings, message: str) -> None:
    """Best-effort: send a warning text to the WhatsApp group."""
    try:
        with whatsapp_context(s) as (_, page):
            whatsapp.check_auth(page)
            whatsapp.send_text(page, message, s)
    except Exception:
        get_logger().exception("alert_failed")
