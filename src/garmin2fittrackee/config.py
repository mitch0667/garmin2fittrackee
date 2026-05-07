import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

DEFAULT_EXTRACT_FOLDER = Path(
    os.getenv("GARMIN_EXTRACT_FOLDER", "/tmp/garmin_exports")
)


def default_log_file() -> Path:
    env_val = os.getenv("LOG_FILE")
    if env_val:
        return Path(env_val)
    log_dir = Path(os.getenv("LOG_DIR", "logs"))
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    return log_dir / f"garmin2fittrackee_{timestamp}.log"


@dataclass(frozen=True)
class FitTrackeeConfig:
    url: str
    username: str
    password: str

    @staticmethod
    def from_env() -> "FitTrackeeConfig":
        url = os.getenv("FITTRACKEE_URL", "")
        username = os.getenv("FITTRACKEE_USERNAME", "")
        password = os.getenv("FITTRACKEE_PASSWORD", "")
        return FitTrackeeConfig(
            url=url,
            username=username,
            password=password,
        )

    def masked(self) -> dict[str, str]:
        return {
            "url": self.url,
            "username": self.username,
            "password": self._mask(self.password),
        }

    @staticmethod
    def _mask(value: str) -> str:
        if len(value) <= 4:
            return "****"
        return value[:2] + "*" * (len(value) - 4) + value[-2:]
