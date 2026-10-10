import re
import time
import requests
import config
from storage import init_db
from portal import run_automation_cycle

def print_waiting_banner():
    print("=" * 70)
    print("       RAILWAYBOT TELEGRAM CONTROLLER - ACTIVE")
    print("=" * 70)
    print(f"[+] Bot: {config.TELEGRAM_BOT_TOKEN[:6]}...")
    print(f"[+] DRY_RUN: {config.DRY_RUN}")
    print("[+] Waiting for commands (/scan)...")
    print("-" * 70)

def get_updates(offset=None):
    url = f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/getUpdates"
    params = {"timeout": 20}
    if offset is not None:
        params["offset"] = offset
    try:
        response = requests.get(url, params=params, timeout=30)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        print(f"[ERROR] Telegram getUpdates: {e}")
        return None

def send_reply(chat_id, text):
    url = f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {"chat_id": chat_id, "text": text, "parse_mode": "Markdown"}
    try:
        response = requests.post(url, json=payload, timeout=30)
        response.raise_for_status()
        return True
    except Exception as e:
        print(f"[ERROR] Telegram sendMessage: {e}")
        return False

def make_telegram_otp_provider(target_chat_id):
    """
    Prompts the user directly on Telegram for the SLAM OTP
    and listens for their reply.
    """
    def _fetch_otp():
        send_reply(
            target_chat_id,
            "📱 *SLAM OTP requested!*\n\n"
            "OTP aapke registered mobile par bhej diya gaya hai.\n\n"
            "👉 *Kripya apna OTP yahan Telegram par reply karein* (ya Chrome window me enter karein):"
        )
        print(f"[TELEGRAM CONTROLLER] Sent OTP request message to chat {target_chat_id}. Awaiting reply...")

        poll_offset = None
        try:
            curr = get_updates(None)
            if curr and curr.get("result"):
                poll_offset = curr["result"][-1]["update_id"] + 1
        except Exception:
            pass

        start_time = time.time()
        timeout = 180  # 3 minutes

        while time.time() - start_time < timeout:
            time.sleep(2)
            data = get_updates(poll_offset)
            if data and data.get("ok"):
                for upd in data.get("result", []):
                    poll_offset = upd["update_id"] + 1
                    msg = upd.get("message", {})
                    msg_chat = str(msg.get("chat", {}).get("id", ""))
                    if msg_chat == str(target_chat_id):
                        text = (msg.get("text") or "").strip()
                        digits = re.sub(r"\D", "", text)
                        if len(digits) >= 4:
                            print(f"[TELEGRAM CONTROLLER] Received OTP from Telegram: {digits}")
                            send_reply(target_chat_id, f"🔐 OTP received! Logging in to SLAM...")
                            return digits

        print("[TELEGRAM CONTROLLER] Timed out waiting for OTP reply on Telegram.")
        return None

    return _fetch_otp

def main():
    init_db()
    print_waiting_banner()
    offset = None
    while True:
        data = get_updates(offset)
        if not data or not data.get("ok"):
            time.sleep(2)
            continue
        for update in data.get("result", []):
            offset = update["update_id"] + 1
            message = update.get("message", {})
            text = message.get("text", '').strip().lower()
            chat_id = str(message.get("chat", {}).get("id", ''))
            
            if text in ('/scan', '/run'):
                send_reply(chat_id, '🚀 Starting SLAM automation...\n_Checking login session & dashboard..._')
                try:
                    otp_provider = make_telegram_otp_provider(chat_id)
                    summary = run_automation_cycle(
                        dry_run=config.DRY_RUN,
                        enable_acknowledgement=config.ENABLE_ACKNOWLEDGEMENT,
                        otp_provider=otp_provider
                    )
                    processed = summary.get("jobcards_processed", 0)
                    found = summary.get("jobcards_found", 0)
                    
                    print("=" * 80)
                    print(f"  CYCLE COMPLETED: {processed}/{found} jobcard(s) processed successfully.")
                    print("=" * 80)
                    
                    send_reply(chat_id, f'✅ Done! Processed: {processed}/{found} jobcard(s).')
                except Exception as ex:
                    send_reply(chat_id, f'❌ Error: {str(ex)}')

                # Drain any duplicate queued /scan commands that accumulated during the cycle
                try:
                    drain = get_updates(None)
                    if drain and drain.get("result"):
                        offset = drain["result"][-1]["update_id"] + 1
                except Exception:
                    pass

                print_waiting_banner()
                break  # Don't process stale queued /scan commands from the same batch
            elif text == '/status':
                send_reply(chat_id, f'📊 Status: ONLINE\nDRY_RUN: {config.DRY_RUN}')

if __name__ == '__main__':
    main()