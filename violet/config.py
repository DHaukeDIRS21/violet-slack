import os
from dataclasses import dataclass
from pathlib import Path


def load_dotenv(path: Path) -> None:
    """Liest KEY=VALUE-Zeilen aus .env; bereits gesetzte Variablen gewinnen."""
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        value = value.split(" #", 1)[0].strip().strip('"').strip("'")
        os.environ.setdefault(key.strip(), value)


def _env(name: str, default: str | None = None) -> str:
    value = os.environ.get(name, default)
    if value is None or value == "":
        raise RuntimeError(f"Umgebungsvariable {name} fehlt (siehe .env.example)")
    return value


@dataclass(frozen=True)
class Config:
    bot_token: str           # xoxb-…  Violet selbst (DM mit dir, Buttons)
    app_token: str           # xapp-…  Socket Mode
    user_token: str          # xoxp-…  postet als du, liest deine DMs
    owner_user_id: str       # nur diese Person darf Violet bedienen
    focus_channel: str       # #improver-squad
    allgemein_channel: str   # #allgemein
    sysadmin_channel: str    # #dirs21_sysadmin
    signature: str
    model: str
    data_dir: Path
    timezone: str

    @classmethod
    def from_env(cls) -> "Config":
        return cls(
            bot_token=_env("SLACK_BOT_TOKEN"),
            app_token=_env("SLACK_APP_TOKEN"),
            user_token=_env("SLACK_USER_TOKEN"),
            owner_user_id=_env("VIOLET_OWNER_USER_ID", "UMP9T403C"),
            focus_channel=_env("VIOLET_FOCUS_CHANNEL", "C07AW2F9ELT"),
            allgemein_channel=_env("VIOLET_ALLGEMEIN_CHANNEL", "C02PUPJ1CUX"),
            sysadmin_channel=_env("VIOLET_SYSADMIN_CHANNEL", "C0C465HRZB3"),
            signature=_env("VIOLET_SIGNATURE", "Daniel"),
            model=_env("VIOLET_MODEL", "claude-opus-5-5"),
            data_dir=Path(_env("VIOLET_DATA_DIR", "./data")),
            timezone=_env("VIOLET_TIMEZONE", "Europe/Berlin"),
        )
