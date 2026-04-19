"""Playwright browser helpers.

All sessions use launch_persistent_context so that cookies, localStorage,
and IndexedDB survive across runs — critical for WhatsApp Web and 10bis.
"""

import datetime as dt
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from playwright.sync_api import BrowserContext, Page, Playwright, sync_playwright

from tenbis.logger import get_logger
from tenbis.settings import Settings


def _save_debug_dump(page: Page, debug_dir: Path) -> None:
    """Save a full-page screenshot + HTML to data/debug/<timestamp>/ on any failure."""
    ts = dt.datetime.now().strftime("%Y%m%dT%H%M%S")
    dump_dir = debug_dir / ts
    dump_dir.mkdir(parents=True, exist_ok=True)
    try:
        page.screenshot(path=str(dump_dir / "screenshot.png"), full_page=True)
    except Exception:
        pass
    try:
        (dump_dir / "page.html").write_text(page.content(), encoding="utf-8")
    except Exception:
        pass
    get_logger(dump_dir=str(dump_dir)).info("debug_dump_saved")


@contextmanager
def tenbis_context(settings: Settings) -> Iterator[tuple[BrowserContext, Page]]:
    """Yield a (context, page) pair for 10bis using a persistent Chromium profile."""
    with sync_playwright() as p:
        ctx = _launch(p, settings.tenbis_profile_dir, settings.headless)
        page = ctx.new_page()
        try:
            yield ctx, page
        except Exception:
            _save_debug_dump(page, settings.debug_dir)
            raise
        finally:
            ctx.close()


@contextmanager
def whatsapp_context(settings: Settings) -> Iterator[tuple[BrowserContext, Page]]:
    """Yield a (context, page) pair for WhatsApp Web using a persistent Chromium profile."""
    with sync_playwright() as p:
        ctx = _launch(p, settings.whatsapp_profile_dir, settings.headless)
        page = ctx.new_page()
        try:
            yield ctx, page
        except Exception:
            _save_debug_dump(page, settings.debug_dir)
            raise
        finally:
            ctx.close()


def _launch(p: Playwright, user_data_dir: Path, headless: bool) -> BrowserContext:
    user_data_dir.mkdir(parents=True, exist_ok=True)
    return p.chromium.launch_persistent_context(
        user_data_dir=str(user_data_dir),
        headless=headless,
        viewport={"width": 1280, "height": 900},
        locale="en-US",
        timezone_id="Asia/Jerusalem",
        args=["--no-sandbox", "--disable-dev-shm-usage"],
    )
