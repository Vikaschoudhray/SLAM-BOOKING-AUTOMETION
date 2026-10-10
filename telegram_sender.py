import os
import requests
from pathlib import Path
from typing import Optional, Dict, Any, Tuple
from config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
from storage import log_audit

TELEGRAM_API_BASE = "https://api.telegram.org/bot"

def get_api_url(endpoint: str) -> str:
    if not TELEGRAM_BOT_TOKEN:
        raise ValueError("TELEGRAM_BOT_TOKEN is missing or empty.")
    return f"{TELEGRAM_API_BASE}{TELEGRAM_BOT_TOKEN}/{endpoint.lstrip('/')}"

def test_telegram_connection() -> Tuple[bool, str]:
    """Tests if the Telegram Bot Token and Chat ID are valid and responsive."""
    if not TELEGRAM_BOT_TOKEN:
        return False, "TELEGRAM_BOT_TOKEN is not configured."
    if not TELEGRAM_CHAT_ID:
        return False, "TELEGRAM_CHAT_ID is not configured."
    
    try:
        url = get_api_url("getMe")
        res = requests.get(url, timeout=15)
        data = res.json()
        if not data.get("ok"):
            err = data.get("description", "Unknown Telegram API error")
            return False, f"Bot verification failed: {err}"
        
        bot_name = data.get("result", {}).get("username", "UnknownBot")
        return True, f"Telegram Bot verified successfully: @{bot_name}"
    except Exception as e:
        return False, f"Telegram connection error: {str(e)}"

def send_telegram_message(text: str) -> Tuple[bool, Optional[str]]:
    """Sends a text message to the configured Telegram chat."""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        log_audit("WARNING", "TELEGRAM_SKIPPED", details="Bot token or chat ID not set.")
        return False, "Token or chat ID not configured."
    
    url = get_api_url("sendMessage")
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": "Markdown"
    }
    
    try:
        response = requests.post(url, json=payload, timeout=20)
        data = response.json()
        if data.get("ok"):
            msg_id = str(data.get("result", {}).get("message_id", ""))
            return True, msg_id
        else:
            err = data.get("description", "Unknown error")
            log_audit("ERROR", "TELEGRAM_SEND_FAILED", details=f"Error: {err}")
            return False, err
    except Exception as ex:
        log_audit("ERROR", "TELEGRAM_EXCEPTION", details=str(ex))
        return False, str(ex)

def send_jobcard_screenshot(
    screenshot_path: Path,
    loco_no: str,
    jobcard_no: str,
    schedule: str,
    status_result: str,
    date_time_str: str,
    extra_remarks: str = ""
) -> Tuple[bool, Optional[str]]:
    """
    Sends only the required jobcard information with the screenshot.

    Telegram output:
      🚂 Loco No: <loco>
      📋 Schedule: <schedule>
      📅 Date: <date>

    jobcard_no, status_result and extra_remarks are retained in the
    function signature for compatibility with portal.py, but are not
    displayed in the Telegram caption.
    """
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        log_audit(
            "WARNING",
            "TELEGRAM_SKIPPED",
            loco_no,
            jobcard_no,
            "Bot token or chat ID not set."
        )
        return False, "Token or chat ID not configured."

    if not screenshot_path.exists():
        err_msg = f"Screenshot file not found: {screenshot_path}"
        log_audit("ERROR", "TELEGRAM_FILE_NOT_FOUND", loco_no, jobcard_no, err_msg)
        return False, err_msg

    # Convert the existing date/time value to date-only display.
    date_only = str(date_time_str).split()[0]

    caption = (
        f"🚂 *Loco No:* `{loco_no}`\n"
        f"📋 *Schedule:* {schedule}\n"
        f"📅 *Date:* `{date_only}`"
    )

    url = get_api_url("sendPhoto")

    try:
        with open(screenshot_path, "rb") as photo_file:
            files = {"photo": photo_file}
            data = {
                "chat_id": TELEGRAM_CHAT_ID,
                "caption": caption,
                "parse_mode": "Markdown"
            }

            response = requests.post(
                url,
                data=data,
                files=files,
                timeout=30
            )

            res_json = response.json()

            if res_json.get("ok"):
                msg_id = str(
                    res_json.get("result", {}).get("message_id", "")
                )
                log_audit(
                    "INFO",
                    "TELEGRAM_DELIVERED",
                    loco_no,
                    jobcard_no,
                    f"Delivered photo message_id={msg_id}"
                )
                return True, msg_id

            err = res_json.get(
                "description",
                "Failed to send photo"
            )
            log_audit(
                "ERROR",
                "TELEGRAM_SEND_FAILED",
                loco_no,
                jobcard_no,
                err
            )
            return False, err

    except Exception as ex:
        log_audit(
            "ERROR",
            "TELEGRAM_EXCEPTION",
            loco_no,
            jobcard_no,
            str(ex)
        )
        return False, str(ex)


def send_dashboard_screenshot(
    screenshot_path: Path,
    date_time_str: str
) -> Tuple[bool, Optional[str]]:
    """
    Sends the Section Schedules Progress dashboard screenshot when
    no new eligible Pink jobcards are available.
    """
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        log_audit(
            "WARNING",
            "TELEGRAM_SKIPPED",
            details="Bot token or chat ID not set."
        )
        return False, "Token or chat ID not configured."

    if not screenshot_path.exists():
        err_msg = f"Screenshot file not found: {screenshot_path}"
        log_audit("ERROR", "TELEGRAM_FILE_NOT_FOUND", details=err_msg)
        return False, err_msg

    date_only = str(date_time_str).split()[0]

    caption = (
        f"📋 *Section Schedules Progress*\\n"
        f"📅 *Date:* `{date_only}`\\n"
        f"ℹ️ *No new unacknowledged jobcard found.*"
    )

    url = get_api_url("sendPhoto")

    try:
        with open(screenshot_path, "rb") as photo_file:
            files = {"photo": photo_file}
            data = {
                "chat_id": TELEGRAM_CHAT_ID,
                "caption": caption,
                "parse_mode": "Markdown"
            }

            response = requests.post(
                url,
                data=data,
                files=files,
                timeout=30
            )

            res_json = response.json()

            if res_json.get("ok"):
                msg_id = str(
                    res_json.get("result", {}).get("message_id", "")
                )
                log_audit(
                    "INFO",
                    "DASHBOARD_SCREENSHOT_DELIVERED",
                    details=f"Delivered photo message_id={msg_id}"
                )
                return True, msg_id

            err = res_json.get(
                "description",
                "Failed to send dashboard screenshot"
            )
            log_audit(
                "ERROR",
                "TELEGRAM_SEND_FAILED",
                details=err
            )
            return False, err

    except Exception as ex:
        log_audit(
            "ERROR",
            "TELEGRAM_EXCEPTION",
            details=str(ex)
        )
        return False, str(ex)
