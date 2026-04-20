"""WhatsApp Web Playwright flow: send barcode image, scan reactions, send text.

All selectors are imported from selectors.py — no CSS strings here.
"""

import re
from pathlib import Path

from playwright.sync_api import Page

from tenbis import selectors
from tenbis.logger import get_logger
from tenbis.settings import Settings


class GroupNotFoundError(Exception):
    """The configured WhatsApp group name was not found."""


class NotAGroupError(Exception):
    """The search result matched but is not a group chat."""


class WAAuthExpiredError(Exception):
    """WhatsApp session expired. Run `mise run login:whatsapp` then sync profiles."""


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
    # Click the search box and clear it
    page.click(selectors.WHATSAPP_SEARCH_BOX, timeout=10_000)
    page.wait_for_timeout(500)
    page.keyboard.press("Control+a")
    page.keyboard.press("Backspace")

    # Type the group name
    page.keyboard.type(group_name, delay=60)
    page.wait_for_timeout(1_500)

    # Find the matching result — exact title match
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

    # Validate it's a group (subtitle lists participants)
    try:
        subtitle = page.locator(selectors.WHATSAPP_ACTIVE_CHAT_SUBTITLE).first.inner_text(
            timeout=5_000
        )
        # Groups have a subtitle like "You, Wife" or "3 participants"; DMs just show a phone number / status  # noqa: E501
        # The heuristic: if the subtitle contains a comma or "participant" it's a group
        if "," not in subtitle and "participant" not in subtitle.lower():
            get_logger(subtitle=subtitle).warning("group_subtitle_unexpected")
    except Exception:
        # Subtitle not found — not a blocking error, just log and continue
        get_logger().warning("group_subtitle_not_found")

    get_logger(group=group_name).info("group_opened")


# ── send ──────────────────────────────────────────────────────────────────────


def send_barcode(page: Page, image_path: Path, caption: str, settings: Settings) -> str:
    """Send an image to the configured WhatsApp group. Returns the message data-id."""
    open_group(page, settings.whatsapp_group_name)

    # Open the attach menu, click "Photos & videos", and set the file via the
    # native file chooser — this routes through the photo pipeline, not stickers.
    page.click(selectors.WHATSAPP_ATTACH_BUTTON, timeout=10_000)
    page.wait_for_timeout(500)
    with page.expect_file_chooser(timeout=10_000) as fc_info:
        page.locator(selectors.WHATSAPP_PHOTOS_BUTTON).click()
    fc_info.value.set_files(str(image_path))
    page.wait_for_timeout(2_000)

    # Add caption
    try:
        caption_box = page.locator(selectors.WHATSAPP_CAPTION_INPUT).first
        caption_box.click(timeout=5_000)
        caption_box.type(caption, delay=30)
    except Exception:
        get_logger().warning("caption_input_not_found_skipping")

    # Send — force=True bypasses any overlay (e.g. the attach dropdown) that may still be visible
    page.locator(selectors.WHATSAPP_SEND_BUTTON).click(timeout=10_000, force=True)
    page.wait_for_timeout(3_000)

    # Capture the data-id of the most recent outgoing message
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


# ── scan reactions ────────────────────────────────────────────────────────────

USED_REACTION = "✅"


def has_reaction(page: Page, message_id: str) -> bool:
    """Return True if the message with the given data-id has any emoji reaction."""
    selector = selectors.WHATSAPP_MESSAGE_BY_ID.format(message_id=message_id)
    try:
        msg_el = page.locator(selector).first
        # Scroll the message into view
        msg_el.scroll_into_view_if_needed(timeout=5_000)
        page.wait_for_timeout(500)
        reaction_el = msg_el.locator(selectors.WHATSAPP_REACTION_CONTAINER)
        return reaction_el.count() > 0
    except Exception:
        return False


def react_to_message(page: Page, message_id: str, emoji: str) -> None:
    """Add an emoji reaction to a message using the internal WA Web API.

    Non-fatal: logs a warning on failure rather than raising.
    """
    result = page.evaluate(
        """
        async ([messageId, reaction]) => {
            const collections = window.require('WAWebCollections');
            const msg = collections.Msg.get(messageId)
                ?? (await collections.Msg.getMessagesById([messageId]))?.messages?.[0];
            if (!msg) return 'msg_not_found';
            await window.require('WAWebSendReactionMsgAction')
                        .sendReactionToMsg(msg, reaction);
            return 'ok';
        }
        """,
        [message_id, emoji],
    )
    if result != "ok":
        get_logger(message_id=message_id).warning("react_failed", result=result)


# Caption format written by send_barcode: "Shufersal voucher ₪{amount} | {barcode}"
_CAPTION_RE = re.compile(r"Shufersal voucher\s+₪([\d.]+)\s*\|\s*(\S+)", re.IGNORECASE)


def scrape_sent_vouchers(page: Page, group_name: str, scroll_passes: int = 10) -> list[dict]:
    """Scan the group's message history and return untracked sent vouchers.

    Each result dict has: message_id, amount (float), barcode_number, caption.
    scroll_passes controls how far back into history to scroll (each pass scrolls
    the chat viewport to the top and waits for older messages to load).
    """
    open_group(page, group_name)

    # Scroll up to load history
    for _ in range(scroll_passes):
        page.keyboard.press("Home")
        page.wait_for_timeout(1_200)

    # Use the WA Web in-memory store to get all loaded messages in one shot.
    # This is more reliable than DOM scraping and handles virtualised lists.
    raw = page.evaluate(
        """
        () => {
            try {
                const store = window.require('WAWebCollections');
                const msgs = store.Msg.getModelsArray();
                return msgs
                    .filter(m => m.id && m.id.fromMe && (m.type === 'image' || m.caption))
                    .map(m => ({
                        id: m.id._serialized || m.id.id || '',
                        caption: m.caption || m.body || '',
                        timestamp: m.t || 0,
                    }));
            } catch (e) {
                return [];
            }
        }
        """
    )

    results = []
    for entry in raw or []:
        caption = entry.get("caption", "")
        m = _CAPTION_RE.search(caption)
        if not m:
            continue
        results.append(
            {
                "message_id": entry["id"],
                "amount": float(m.group(1)),
                "barcode_number": m.group(2),
                "caption": caption,
                "timestamp": entry.get("timestamp", 0),
            }
        )

    get_logger(group=group_name, found=len(results)).info("scrape_sent_vouchers_done")
    return results


def _last_sent_message_id(page: Page) -> str:
    """Return the data-id of the most recently sent outgoing message, or empty string."""
    try:
        # Message data-id format changed in newer WA Web — no longer uses true_ prefix.
        # Exclude album containers (their IDs start with "album-").
        msgs = page.locator("[data-id]")
        count = msgs.count()
        for i in range(count - 1, -1, -1):
            did = msgs.nth(i).get_attribute("data-id") or ""
            if did and not did.startswith("album-"):
                return did
        return ""
    except Exception:
        return ""
