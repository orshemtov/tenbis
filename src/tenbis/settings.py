from pathlib import Path
from zoneinfo import ZoneInfo

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=Path(__file__).parents[2] / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # 10bis
    tenbis_email: str = ""
    tenbis_item_url: str = (
        "https://www.10bis.co.il/next/en/restaurants/menu/delivery/26698/shufersal/?dishId=6552647"
    )
    tenbis_item_price: float = 200.0
    tenbis_min_monthly_balance: float = 200.0
    tenbis_min_daily_balance: float = 200.0

    # WhatsApp
    whatsapp_group_name: str = "Vouchers"

    # Paths
    data_dir: Path = Path(__file__).parents[2] / "data"

    # Runtime
    headless: bool = True
    dry_run: bool = False
    debug: bool = False
    timezone: str = "Asia/Jerusalem"

    # Deploy
    server: str = ""

    @property
    def tz(self) -> ZoneInfo:
        return ZoneInfo(self.timezone)

    @property
    def tenbis_profile_dir(self) -> Path:
        return self.data_dir / "10bis-profile"

    @property
    def whatsapp_profile_dir(self) -> Path:
        return self.data_dir / "whatsapp-profile"

    @property
    def vouchers_dir(self) -> Path:
        return self.data_dir / "vouchers"

    @property
    def pending_dir(self) -> Path:
        return self.vouchers_dir / "pending"

    @property
    def used_dir(self) -> Path:
        return self.vouchers_dir / "used"

    @property
    def debug_dir(self) -> Path:
        return self.data_dir / "debug"

    def ensure_dirs(self) -> None:
        for d in (
            self.tenbis_profile_dir,
            self.whatsapp_profile_dir,
            self.pending_dir,
            self.used_dir,
            self.debug_dir,
        ):
            d.mkdir(parents=True, exist_ok=True)
