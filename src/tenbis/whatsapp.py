"""WhatsApp Web Playwright flow: send barcode image, scan reactions, send text.

All selectors are imported from selectors.py — no CSS strings here.
"""

import dataclasses
import datetime as dt
from pathlib import Path

from playwright.sync_api import Page

from tenbis import selectors
from tenbis.logger import get_logger
from tenbis.settings import Settings


class GroupNotFoundError(Exception):
    """The configured WhatsApp group name was not found."""


class WAAuthExpiredError(Exception):
    """WhatsApp session expired. Run `mise run login:whatsapp` then sync profiles."""


# ── constants ─────────────────────────────────────────────────────────────────

# Reaction the bot adds to acknowledge a used voucher
BOT_REACTION = "🤖"

# Caption prefix written by this bot when sending a barcode image
CAPTION_PREFIX = "Shufersal voucher ₪"

# Emojis available in WA's default 6-emoji quick-tray (no picker needed)
_QUICK_TRAY_EMOJIS = {"👍", "❤️", "😂", "😮", "😢", "🙏"}


# ── data model ────────────────────────────────────────────────────────────────


@dataclasses.dataclass
class VoucherMessage:
    message_id: str
    caption: str
    user_reacted: bool  # any family-member reaction present
    bot_acked: bool  # BOT_REACTION (🤖) present — means bot already acknowledged


# ── auth ──────────────────────────────────────────────────────────────────────


def check_auth(page: Page) -> None:
    """Navigate to WhatsApp Web and raise WAAuthExpiredError if not logged in."""
    page.goto(selectors.WHATSAPP_URL, wait_until="domcontentloaded")
    try:
        page.wait_for_selector(selectors.WHATSAPP_LOGGED_IN, timeout=60_000)
    except Exception:
        raise WAAuthExpiredError(
            "WhatsApp session expired. Run 'mise run login:whatsapp' on your laptop "
            "then 'mise run sync:profiles'."
        )
    get_logger().info("whatsapp_auth_ok")


def do_login(page: Page) -> None:
    """Interactive WhatsApp login: display QR and wait for the user to scan it."""
    page.goto(selectors.WHATSAPP_URL, wait_until="domcontentloaded")
    try:
        page.wait_for_selector(selectors.WHATSAPP_LOGGED_IN, timeout=10_000)
        get_logger().info("whatsapp_already_logged_in")
        return
    except Exception:
        pass
    print("Scan the QR code in the browser window to log in to WhatsApp Web.")
    page.wait_for_selector(selectors.WHATSAPP_LOGGED_IN, timeout=120_000)
    get_logger().info("whatsapp_login_complete")


# ── group navigation ──────────────────────────────────────────────────────────


def open_group(page: Page, group_name: str) -> None:
    """Search for group_name and open it, validating it is a group chat."""
    page.click(selectors.WHATSAPP_SEARCH_BOX, timeout=10_000)
    page.wait_for_timeout(500)
    page.keyboard.press("Control+a")
    page.keyboard.press("Backspace")

    page.keyboard.type(group_name, delay=60)
    page.wait_for_timeout(1_500)

    results = page.locator(selectors.WHATSAPP_CHAT_RESULT_TITLE)
    count = results.count()
    if count == 0:
        raise GroupNotFoundError(
            f"No WhatsApp chat found for '{group_name}'. "
            "Check WHATSAPP_GROUP_NAME in .env matches the exact group title."
        )

    clicked = False
    for i in range(count):
        title = results.nth(i).get_attribute("title") or results.nth(i).inner_text()
        if title.strip() == group_name:
            results.nth(i).click()
            clicked = True
            break

    if not clicked:
        raise GroupNotFoundError(
            f"Search returned results but none matched '{group_name}' exactly."
        )

    page.wait_for_timeout(2_000)

    # Click the message input to confirm the chat is fully loaded and dismiss the
    # search overlay.  Pressing Escape would close the chat entirely; clicking the
    # input is the safe way to "commit" the group open without side-effects.
    try:
        page.locator(selectors.WHATSAPP_TEXT_INPUT).first.click(timeout=5_000)
    except Exception:
        pass  # non-fatal; chat may already be in focus

    try:
        subtitle = page.locator(selectors.WHATSAPP_ACTIVE_CHAT_SUBTITLE).first.inner_text(
            timeout=5_000
        )
        if "," not in subtitle and "participant" not in subtitle.lower():
            get_logger(subtitle=subtitle).warning("group_subtitle_unexpected")
    except Exception:
        get_logger().warning("group_subtitle_not_found")

    get_logger(group=group_name).info("group_opened")


# ── send ──────────────────────────────────────────────────────────────────────


def send_barcode(page: Page, image_path: Path, caption: str, settings: Settings) -> str:
    """Send an image to the configured WhatsApp group. Returns the message data-id."""
    open_group(page, settings.whatsapp_group_name)

    page.click(selectors.WHATSAPP_ATTACH_BUTTON, timeout=10_000)
    page.wait_for_timeout(500)
    with page.expect_file_chooser(timeout=10_000) as fc_info:
        page.locator(selectors.WHATSAPP_PHOTOS_BUTTON).click()
    fc_info.value.set_files(str(image_path))
    page.wait_for_timeout(2_000)

    try:
        caption_box = page.locator(selectors.WHATSAPP_CAPTION_INPUT).first
        caption_box.click(timeout=5_000)
        caption_box.type(caption, delay=30)
    except Exception:
        get_logger().warning("caption_input_not_found_skipping")

    page.locator(selectors.WHATSAPP_SEND_BUTTON).click(timeout=10_000, force=True)
    page.wait_for_timeout(3_000)

    message_id = _last_sent_message_id(page)
    get_logger(group=settings.whatsapp_group_name, message_id=message_id).info("barcode_sent")
    return message_id


def send_text(page: Page, text: str, settings: Settings) -> None:
    """Send a plain text message to the configured WhatsApp group (for alerts)."""
    open_group(page, settings.whatsapp_group_name)
    page.click(selectors.WHATSAPP_TEXT_INPUT, timeout=10_000)
    page.keyboard.type(text, delay=20)
    page.keyboard.press("Enter")
    page.wait_for_timeout(2_000)
    get_logger(group=settings.whatsapp_group_name).info("text_sent")


# ── scan ──────────────────────────────────────────────────────────────────────


def scan_voucher_messages(page: Page, s: Settings) -> list[VoucherMessage]:
    """Scan the currently open WA group for bot-sent barcode messages.

    Scrolls up several times to load older messages (WA uses virtual scrolling),
    then uses JS to find all [data-id] elements whose caption text contains
    CAPTION_PREFIX.  Caption text is in [data-testid="selectable-text"] or
    [data-testid="media-caption-rich-text"] inside the message bubble — NOT in
    span[dir] (which only holds timestamps).
    """
    page.wait_for_timeout(1_000)  # let initial messages render

    # Scroll up to load recent history (virtual list only keeps ~10 msgs in DOM)
    panel = page.locator('[data-testid="conversation-panel-messages"]')
    try:
        panel.first.wait_for(timeout=5_000)
        for _ in range(5):
            panel.first.evaluate("el => el.scrollTop -= el.clientHeight")
            page.wait_for_timeout(600)
        # Scroll back to bottom so the chat looks normal after scanning
        panel.first.evaluate("el => el.scrollTop = el.scrollHeight")
        page.wait_for_timeout(500)
    except Exception:
        get_logger().warning("scroll_panel_not_found")

    raw: list[dict] = page.evaluate(
        """([prefix, botReaction]) => {
            const results = [];
            document.querySelectorAll('[data-id]').forEach(el => {
                const dataId = el.getAttribute('data-id');
                if (!dataId || dataId.startsWith('album-')) return;

                // Caption text is in data-testid="image-caption selectable-text".
                // Use the ~= (word-match) selector to handle multi-value data-testid.
                let caption = '';
                const candidateSelectors = [
                    '[data-testid~="selectable-text"]',
                    '[data-testid~="media-caption-rich-text"]',
                ];
                for (const sel of candidateSelectors) {
                    for (const node of el.querySelectorAll(sel)) {
                        const txt = (node.textContent || '').trim();
                        if (txt.includes(prefix)) {
                            caption = txt;
                            break;
                        }
                    }
                    if (caption) break;
                }
                if (!caption) return;

                // Read reactions
                const reactionEl = el.querySelector('[data-testid="msg-reactions"]');
                const btns = reactionEl
                    ? Array.from(reactionEl.querySelectorAll('button,[role="button"]'))
                    : [];
                const allText = btns
                    .map(b => (b.getAttribute('aria-label') || '') + (b.textContent || ''))
                    .join('');

                results.push({
                    messageId: dataId,
                    caption,
                    userReacted: btns.length > 0,
                    botAcked: allText.includes(botReaction),
                });
            });
            return results;
        }""",
        [CAPTION_PREFIX, BOT_REACTION],
    )

    return [
        VoucherMessage(
            message_id=r["messageId"],
            caption=r["caption"],
            user_reacted=r["userReacted"],
            bot_acked=r["botAcked"],
        )
        for r in raw
    ]


def sent_today(page: Page, s: Settings) -> bool:
    """Return True if the bot already sent a voucher message today."""
    today = dt.date.today().isoformat()  # "2026-04-20"
    return any(today in m.caption for m in scan_voucher_messages(page, s))


# ── reactions ─────────────────────────────────────────────────────────────────


def react_to_message(page: Page, message_id: str, emoji: str) -> None:
    """Add an emoji reaction to a message.

    For emojis in the default quick-tray (_QUICK_TRAY_EMOJIS): hover → tray button.
    For others (e.g. 🤖): hover → tray → expand → search → click.
    Non-fatal: logs a warning on failure rather than raising.
    """
    selector = selectors.WHATSAPP_MESSAGE_BY_ID.format(message_id=message_id)
    try:
        msg_el = page.locator(selector).first
        msg_el.scroll_into_view_if_needed(timeout=5_000)
        page.wait_for_timeout(400)
        msg_el.hover()
        page.wait_for_timeout(700)  # toolbar appears after ~400 ms

        react_btn = page.locator(selectors.WHATSAPP_REACTION_HOVER_BUTTON).first
        react_btn.click(timeout=5_000)
        page.wait_for_timeout(400)

        if emoji in _QUICK_TRAY_EMOJIS:
            page.locator(f'button[aria-label="{emoji}"]').first.click(timeout=5_000)
        else:
            # Open the full emoji picker via the "+" / "More emojis" button
            page.locator(selectors.WHATSAPP_REACTION_EXPAND).first.click(timeout=5_000)
            page.wait_for_timeout(500)
            search = page.locator(selectors.WHATSAPP_EMOJI_PICKER_SEARCH).first
            search.fill("robot")
            page.wait_for_timeout(800)
            page.locator(selectors.WHATSAPP_EMOJI_PICKER_RESULT.format(emoji=emoji)).first.click(
                timeout=5_000
            )

        get_logger(message_id=message_id, emoji=emoji).info("reacted_to_message")
    except Exception as exc:
        get_logger(message_id=message_id).warning("react_failed", error=str(exc))


# ── internals ─────────────────────────────────────────────────────────────────


def _last_sent_message_id(page: Page) -> str:
    """Return the data-id of the most recently sent outgoing message, or empty string."""
    try:
        msgs = page.locator("[data-id]")
        count = msgs.count()
        for i in range(count - 1, -1, -1):
            did = msgs.nth(i).get_attribute("data-id") or ""
            if did and not did.startswith("album-"):
                return did
        return ""
    except Exception:
        return ""
