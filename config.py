import os
from pathlib import Path
from dotenv import load_dotenv

# ============================================================
# Base directory
# ============================================================
BASE_DIR = Path(__file__).resolve().parent

# ============================================================
# Load .env file
# ============================================================
ENV_PATH = BASE_DIR / ".env"

if ENV_PATH.exists():
    load_dotenv(dotenv_path=ENV_PATH, override=True)
else:
    load_dotenv(override=True)

# ============================================================
# Directories
# ============================================================
SCREENSHOTS_DIR = BASE_DIR / "screenshots"
LOGS_DIR = BASE_DIR / "logs"
STATE_DIR = BASE_DIR / "state"

for directory in (SCREENSHOTS_DIR, LOGS_DIR, STATE_DIR):
    directory.mkdir(parents=True, exist_ok=True)

# ============================================================
# Portal & Chrome settings
# ============================================================
PORTAL_URL = os.getenv(
    "PORTAL_URL",
    "https://slam.indianrail.gov.in/SLAM/Login.aspx"
)

DASHBOARD_URL = os.getenv(
    "DASHBOARD_URL",
    "https://slam.indianrail.gov.in/SLAM/JobSchedules/SectionJobCardsDashboard.aspx"
)

# Credentials are maintained only in .env (do not hard-code them here).
# SLAM credentials are read from .env
SLAM_USERNAME = os.getenv("SLAM_USERNAME", "").strip()
SLAM_PASSWORD = os.getenv("SLAM_PASSWORD", "")

CHROME_PROFILE_DIR = Path(
    os.getenv(
        "CHROME_PROFILE_DIR",
        str(BASE_DIR / "slam_chrome_profile")
    )
)

HEADLESS = os.getenv(
    "HEADLESS",
    "false"
).strip().lower() in ("true", "1", "yes")

BROWSER_TIMEOUT_MS = int(
    os.getenv("BROWSER_TIMEOUT_MS", "60000")
)

LOGIN_WAIT_TIMEOUT_SECONDS = int(
    os.getenv("LOGIN_WAIT_TIMEOUT_SECONDS", "180")
)

# ============================================================
# Automation Safety Controls
# ============================================================
DRY_RUN = os.getenv(
    "DRY_RUN",
    "true"
).strip().lower() in ("true", "1", "yes")

ENABLE_ACKNOWLEDGEMENT = os.getenv(
    "ENABLE_ACKNOWLEDGEMENT",
    "false"
).strip().lower() in ("true", "1", "yes")

# ============================================================
# Telegram Bot API settings
# ============================================================
TELEGRAM_BOT_TOKEN = os.getenv(
    "TELEGRAM_BOT_TOKEN",
    ""
).strip()

TELEGRAM_CHAT_ID = os.getenv(
    "TELEGRAM_CHAT_ID",
    ""
).strip()

# ============================================================
# Database & Lock file paths
# ============================================================
DB_PATH = STATE_DIR / "slam_automation.sqlite"

LOCK_FILE_PATH = STATE_DIR / "slam_automation.lock"


# ============================================================
# Configuration validation
# ============================================================
def validate_config(require_telegram: bool = False) -> None:
    """Validate configuration parameters."""

    if not CHROME_PROFILE_DIR.exists():
        CHROME_PROFILE_DIR.mkdir(
            parents=True,
            exist_ok=True
        )

    if require_telegram:

        if not TELEGRAM_BOT_TOKEN:
            raise ValueError(
                "TELEGRAM_BOT_TOKEN is required in .env "
                "for Telegram delivery."
            )

        if not TELEGRAM_CHAT_ID:
            raise ValueError(
                "TELEGRAM_CHAT_ID is required in .env "
                "for Telegram delivery."
            )


# ============================================================
# Acknowledgement safety check
# ============================================================
def is_acknowledgement_allowed() -> bool:
    """
    Acknowledgement is allowed ONLY when:

    DRY_RUN = False
    AND
    ENABLE_ACKNOWLEDGEMENT = True
    """

    return (
        not DRY_RUN
        and ENABLE_ACKNOWLEDGEMENT
    )