import os
import sys
import time
import datetime
from pathlib import Path

# Ensure C:\RailwayBot is in sys.path
BASE_DIR = Path(__file__).resolve().parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

import config
from storage import init_db, log_audit
from portal import run_automation_cycle

def print_banner():
    now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print("=" * 80)
    print("        INDIAN RAILWAYS — CRIS SLAM JOBCARD AUTOMATION SYSTEM")
    print(f"        Execution Time: {now_str}")
    print(f"        Project Root:   {config.BASE_DIR}")
    print(f"        Database:       {config.DB_PATH}")
    mode_str = "DRY-RUN (Safe Mode - Portal changes disabled)" if (config.DRY_RUN or not config.ENABLE_ACKNOWLEDGEMENT) else "LIVE ACKNOWLEDGEMENT (Official updates active)"
    print(f"        Operating Mode: {mode_str}")
    print(f"        Telegram Alert: {'ENABLED' if config.TELEGRAM_BOT_TOKEN and config.TELEGRAM_CHAT_ID else 'DISABLED'}")
    print("=" * 80, flush=True)

def main():
    print_banner()
    
    # 1. Initialize SQLite Database
    init_db()
    
    # 2. Run Automation Cycle
    summary = run_automation_cycle(
        dry_run=config.DRY_RUN,
        enable_acknowledgement=config.ENABLE_ACKNOWLEDGEMENT
    )
    
    # 3. Print Final Report
    print("\n" + "=" * 80)
    print("  RUN SUMMARY REPORT")
    print("=" * 80)
    print(f"  Start Time:          {summary.get('start_time')}")
    print(f"  Dry-Run Mode:        {summary.get('dry_run')}")
    print(f"  Jobcards Detected:   {summary.get('jobcards_found')}")
    print(f"  Jobcards Processed:  {summary.get('jobcards_processed')}")
    
    for res in summary.get("results", []):
        loco = res.get("loco", "-")
        jc = res.get("jobcard_no", "-")
        act = res.get("action_taken", "-")
        tg = "Delivered" if res.get("telegram_delivered") else "Not Sent"
        print(f"    * Loco {loco} | JC {jc} | Action: {act} | Telegram: {tg}")
    
    print("=" * 80)
    log_audit("INFO", "MAIN_CYCLE_FINISHED", details=f"Processed {summary.get('jobcards_processed')}/{summary.get('jobcards_found')}")

if __name__ == "__main__":
    main()
