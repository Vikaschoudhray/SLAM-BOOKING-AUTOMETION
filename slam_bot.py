"""
RailwayBot SLAM Bot Main Launcher
Automates the Indian Railways CRIS SLAM portal workflow.
Integrates reusable SLAMAuth module for automated login and CAPTCHA solving,
prompts for manual OTP, and executes the complete RailwayBot automation cycle.
"""

import sys
from pathlib import Path
from playwright.sync_api import sync_playwright

# Ensure C:\RailwayBot is in sys.path
BASE_DIR = Path(__file__).resolve().parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

import config
from storage import init_db
from slam_auth import SLAMAuth
from portal import run_automation_cycle


def main():
    print("=" * 80)
    print("        INDIAN RAILWAYS — CRIS SLAM JOBCARD AUTOMATION (SLAM_BOT)")
    print(f"        Base Directory: {config.BASE_DIR}")
    print(f"        Chrome Profile: {config.CHROME_PROFILE_DIR}")
    print(f"        Portal URL:     {config.PORTAL_URL}")
    print("=" * 80, flush=True)

    # 1. Initialize SQLite Database
    init_db()

    # 2. Ensure Profile Directory Exists
    Path(config.CHROME_PROFILE_DIR).mkdir(parents=True, exist_ok=True)

    # 3. Launch Persistent Chrome Context
    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            user_data_dir=str(config.CHROME_PROFILE_DIR),
            channel="chrome",
            headless=config.HEADLESS,
            accept_downloads=True,
            viewport={"width": 1920, "height": 1080},
        )

        page = context.pages[0] if context.pages else context.new_page()
        page.set_default_timeout(getattr(config, "BROWSER_TIMEOUT_MS", 30000))

        # 4. Authenticate using SLAMAuth
        auth = SLAMAuth(page)
        if not auth.login():
            print("[SLAM BOT] SLAM login failed or cancelled. Stopping RailwayBot.")
            context.close()
            return

        print(f"[SLAM BOT] Session active. Current URL: {page.url}")
        print("[SLAM BOT] Continuing RailwayBot automation workflow...\n")

        # 5. Run RailwayBot Automation Cycle
        try:
            summary = run_automation_cycle(
                dry_run=config.DRY_RUN,
                enable_acknowledgement=config.ENABLE_ACKNOWLEDGEMENT,
                existing_context=context,
                existing_page=page,
            )

            print("\n" + "=" * 80)
            print("  SLAM BOT EXECUTION FINISHED")
            print(f"  Start Time:          {summary.get('start_time')}")
            print(f"  Dry-Run Mode:        {summary.get('dry_run')}")
            print(f"  Jobcards Detected:   {summary.get('jobcards_found', 0)}")
            print(f"  Jobcards Processed:  {summary.get('jobcards_processed', 0)}")
            print("=" * 80)
        finally:
            context.close()


if __name__ == "__main__":
    main()