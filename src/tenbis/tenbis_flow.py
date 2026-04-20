"""10bis Playwright flow: budget check, purchase, barcode capture.

All selectors are imported from selectors.py — this module contains no CSS strings.
"""

import datetime as dt
import re
from zoneinfo import ZoneInfo

from playwright.sync_api import Page

from tenbis import selectors
from tenbis.imaging import create_voucher_image
from tenbis.logger import logger
from tenbis.vouchers import VoucherRecord


class AuthExpiredError(Exception):
    """Raised when the 10bis session is not authenticated. Run `mise run login:tenbis`."""


class BudgetInsufficientError(Exception):
    """Raised when there is not enough budget to purchase."""

    def __init__(self, monthly: float, daily_remaining: float, required: float) -> None:
        self.monthly = monthly
        self.daily_remaining = daily_remaining
        self.required = required
        super().__init__(
            f"Insufficient budget: monthly={monthly} daily_remaining={daily_remaining} required={required}"  # noqa: E501
        )


# ── helpers ───────────────────────────────────────────────────────────────────


def check_auth(page: Page) -> None:
    """Navigate to the 10bis home page and raise AuthExpiredError if not logged in."""
    page.goto(selectors.TENBIS_BASE_URL, wait_until="domcontentloaded")
    try:
        page.wait_for_selector(selectors.TENBIS_LOGGED_IN_BUTTON, timeout=8_000)
    except Exception:
        raise AuthExpiredError(
            "10bis session expired. Run 'mise run login:tenbis' on your laptop "
            "then 'mise run sync:profiles'."
        )
    logger.info("tenbis_auth_ok")


def parse_amount(text: str) -> float | None:
    match = re.search(r"₪\s*([0-9]+(?:\.[0-9]+)?)|([0-9]+(?:\.[0-9]+)?)\s*₪", text)
    if not match:
        return None
    return float(match.group(1) or match.group(2))


def get_budget_from_text(body_text: str, labels: list[str]) -> float | None:
    lines = [line.strip() for line in body_text.splitlines() if line.strip()]
    normalized = [line.casefold() for line in lines]
    for label in labels:
        label_cf = label.casefold()
        for idx, line in enumerate(normalized):
            if label_cf in line:
                for prev in range(idx - 1, max(idx - 5, -1), -1):
                    val = parse_amount(lines[prev])
                    if val is not None:
                        return val
                val = parse_amount(lines[idx])
                if val is not None:
                    return val
    return None


def today_spent(body_text: str) -> float:
    """Sum transaction amounts whose date matches today (DD.MM.YY format)."""
    today = dt.date.today().strftime("%d.%m.%y")
    lines = [line.strip() for line in body_text.splitlines() if line.strip()]
    total = 0.0
    for idx, line in enumerate(lines):
        if line.startswith(today):
            # row layout: date+time, business, order type, ₪amount
            for offset in range(1, 5):
                if idx + offset < len(lines):
                    val = parse_amount(lines[idx + offset])
                    if val is not None:
                        total += val
                        break
    return total


def get_budget(page: Page, daily_limit: float) -> tuple[float, float]:
    """Return (monthly_balance, daily_remaining).

    daily_remaining = daily_limit - sum of today's transactions.
    """
    page.goto(selectors.TENBIS_BILLING_URL, wait_until="domcontentloaded")
    page.wait_for_timeout(2_000)
    body = page.locator("body").inner_text()

    monthly = get_budget_from_text(body, selectors.TENBIS_BUDGET_LABELS_MONTHLY)
    if monthly is None:
        raise RuntimeError("Could not read monthly balance from billing page")

    spent = today_spent(body)
    daily_remaining = max(daily_limit - spent, 0.0)

    logger.info("budget", monthly=monthly, spent_today=spent, daily_remaining=daily_remaining)
    return monthly, daily_remaining


def do_login(page: Page, email: str) -> None:
    """Interactive login flow: fill email, wait for OTP, fill OTP.

    This is only called from the `login-tenbis` CLI command (headed mode).
    """
    page.goto(selectors.TENBIS_BASE_URL, wait_until="domcontentloaded")

    # Already logged in?
    try:
        page.wait_for_selector(selectors.TENBIS_LOGGED_IN_BUTTON, timeout=5_000)
        logger.info("already_logged_in")
        return
    except Exception:
        pass

    # Click sign-in
    try:
        page.click(selectors.TENBIS_SIGN_IN_BUTTON, timeout=5_000)
    except Exception:
        pass

    # Fill email
    page.wait_for_selector(selectors.TENBIS_EMAIL_INPUT, timeout=10_000)
    page.fill(selectors.TENBIS_EMAIL_INPUT, email)
    try:
        page.click(selectors.TENBIS_LOGIN_SUBMIT, timeout=5_000)
    except Exception:
        page.keyboard.press("Enter")

    # Wait for OTP inputs
    page.wait_for_selector(selectors.TENBIS_OTP_INPUT, timeout=30_000)
    otp = input("Enter the 5-digit OTP code from your email/phone: ").strip()

    digits = [c for c in otp if c.isdigit()]
    if len(digits) != 5:
        raise ValueError(f"Expected 5 digits, got: {otp!r}")
    inputs = page.locator(selectors.TENBIS_OTP_INPUT)
    for i, digit in enumerate(digits):
        inputs.nth(i).fill(digit)

    try:
        page.click(selectors.TENBIS_OTP_SUBMIT, timeout=5_000)
    except Exception:
        page.keyboard.press("Enter")

    page.wait_for_selector(selectors.TENBIS_LOGGED_IN_BUTTON, timeout=30_000)
    logger.info("login_complete")


def purchase_voucher(
    page: Page,
    item_url: str,
    amount: float,
    tz: ZoneInfo,
    dry_run: bool = False,
) -> tuple[bytes, VoucherRecord]:
    """Navigate the 10bis site to purchase a Shufersal voucher.

    Returns (png_bytes, VoucherRecord). Raises on any failure.
    If dry_run is True, stops before the final Submit click and raises
    RuntimeError so the caller knows nothing was charged.
    """
    # Navigate to the dish page
    page.goto(item_url, wait_until="domcontentloaded")
    page.wait_for_timeout(2_000)

    # Add to cart
    page.wait_for_selector(selectors.TENBIS_ADD_TO_CART_BUTTON, timeout=15_000)
    page.click(selectors.TENBIS_ADD_TO_CART_BUTTON)
    logger.info("added_to_cart")
    page.wait_for_timeout(1_500)

    # Open cart / proceed to checkout
    try:
        page.click(selectors.TENBIS_CART_BUTTON, timeout=8_000)
        page.wait_for_timeout(1_500)
    except Exception:
        pass  # some flows go straight to checkout

    # Click Checkout button if present
    try:
        page.click(selectors.TENBIS_CHECKOUT_BUTTON, timeout=8_000)
        page.wait_for_timeout(2_000)
    except Exception:
        pass

    logger.info("at_checkout")

    if dry_run:
        logger.info("dry_run_stop")
        raise RuntimeError("DRY_RUN=true — stopped before submitting order (nothing was charged)")

    # Submit the order
    page.wait_for_selector(selectors.TENBIS_SUBMIT_ORDER_BUTTON, timeout=15_000)
    page.click(selectors.TENBIS_SUBMIT_ORDER_BUTTON)
    logger.info("order_submitted")

    # Wait for voucher/barcode page
    page.wait_for_selector(selectors.TENBIS_BARCODE_IMG, timeout=30_000)
    page.wait_for_timeout(1_000)

    # Extract barcode number text
    barcode_number = ""
    try:
        barcode_number = page.locator(selectors.TENBIS_BARCODE_NUMBER).first.inner_text().strip()
    except Exception:
        pass

    png_bytes = capture_barcode(page, barcode_number)

    now_iso = dt.datetime.now(tz).isoformat(timespec="seconds")
    record = VoucherRecord(
        barcode_number=barcode_number,
        amount=amount,
        purchased_at=now_iso,
    )
    logger.info("voucher_purchased", barcode_number=barcode_number)
    return png_bytes, record


def capture_barcode(page: Page, barcode_number: str) -> bytes:
    """Return PNG bytes for the barcode, composed with the number label."""
    barcode_el = page.locator(selectors.TENBIS_BARCODE_IMG).first
    style = barcode_el.get_attribute("style") or ""
    match = re.search(selectors.TENBIS_BARCODE_BG_URL_PATTERN, style)
    if match:
        img_url = match.group(1).replace("&quot;", "")
        response = page.request.get(img_url)
        if response.ok:
            raw_bytes = response.body()
            if barcode_number:
                return create_voucher_image(raw_bytes, barcode_number)
            return raw_bytes

    # Fallback: screenshot the barcode element directly
    raw_bytes = barcode_el.screenshot()
    if barcode_number:
        return create_voucher_image(raw_bytes, barcode_number)
    return raw_bytes
