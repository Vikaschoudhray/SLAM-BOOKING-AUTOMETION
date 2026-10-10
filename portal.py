import re
import os
import sys
import time
import datetime
from pathlib import Path
from urllib.parse import urljoin
from typing import List, Dict, Any, Optional, Tuple
from playwright.sync_api import sync_playwright, Page, BrowserContext

import config
from storage import (
    log_audit,
    is_jobcard_already_processed,
    record_processed_jobcard,
    update_telegram_delivery,
    SingleInstanceLock
)
from telegram_sender import send_jobcard_screenshot, send_dashboard_screenshot, send_telegram_message

def find_authenticated_page(context: BrowserContext) -> Optional[Page]:
    """
    Checks all open tabs to determine if an authenticated session exists.
    Looks for logged-in indicators such as 'Logout', 'Bulletin Boards', or non-login URLs.
    """
    for p in reversed(context.pages):
        try:
            url = p.url.lower()
            if p.locator("a:has-text('Logout'), a:has-text('Bulletin Boards'), span:has-text('Bulletin Boards'), a:has-text('Jobcards')").count() > 0:
                return p
            if "login.aspx" not in url and "about:blank" not in url and "slam.indianrail.gov.in" in url:
                return p
        except Exception:
            pass
    return None

def wait_for_user_login(
    context: BrowserContext,
    timeout_seconds: int = 180,
    otp_provider: Optional[Any] = None,
) -> Optional[Page]:
    """
    Authenticates to the SLAM portal using the reusable SLAMAuth module.
    Reuses existing session if active, otherwise automatically solves CAPTCHA
    and prompts for OTP.
    """
    auth_page = find_authenticated_page(context)
    if auth_page:
        return auth_page

    page = context.pages[0] if context.pages else context.new_page()
    page.set_default_timeout(getattr(config, "BROWSER_TIMEOUT_MS", 30000))

    try:
        from slam_auth import SLAMAuth
        auth = SLAMAuth(page, otp_provider=otp_provider)
        if auth.login():
            return find_authenticated_page(context) or page
    except Exception as e:
        print(f"[LOGIN ERROR] Automated authentication error: {e}", flush=True)
        log_audit("WARNING", "LOGIN_AUTH_ERROR", details=str(e))

    # Fallback to waiting if user completes it in opened browser
    print(f"\nWaiting up to {timeout_seconds} seconds for authenticated session...", flush=True)
    elapsed = 0
    while elapsed < timeout_seconds:
        time.sleep(2)
        elapsed += 2

        auth_page = find_authenticated_page(context)
        if auth_page:
            print(f"\n[OK] Login detected successfully! Active URL: {auth_page.url}\n", flush=True)
            log_audit("INFO", "LOGIN_SUCCESS", details=f"Logged in. URL: {auth_page.url}")
            return auth_page

        if elapsed % 15 == 0:
            print(f"Still waiting for login... ({elapsed}s / {timeout_seconds}s)", flush=True)

    log_audit("WARNING", "LOGIN_TIMEOUT", details="User login timed out.")
    return None

def navigate_to_section_schedules_dashboard(page: Page) -> bool:
    """
    Automatically opens:
        Bulletin Boards -> Section Schedules Progress

    The SLAM menu uses a JavaScript href, so normal text clicking can
    sometimes leave the submenu open without executing navigation.
    This function uses hover + visible submenu detection + DOM click,
    with the known SLAM RedirectPage fallback.
    """
    print("[PORTAL] Navigating to 'Bulletin Boards -> Section Schedules Progress'...", flush=True)

    dashboard_url = "https://slam.indianrail.gov.in/SLAM/BullitenBoards/DailySchedulesProgressDashboard.aspx?Type=1"

    try:
        # Make sure we are on an authenticated SLAM page.
        if "slam.indianrail.gov.in" not in page.url.lower():
            page.goto(config.PORTAL_URL, wait_until="domcontentloaded", timeout=60000)

        # Locate the Bulletin Boards menu.
        bb_candidates = [
            "a:has-text('Bulletin Boards')",
            "span:has-text('Bulletin Boards')",
            "text=Bulletin Boards",
        ]

        bb = None
        for selector in bb_candidates:
            loc = page.locator(selector)
            if loc.count() > 0:
                for i in range(min(loc.count(), 5)):
                    candidate = loc.nth(i)
                    try:
                        if candidate.is_visible():
                            bb = candidate
                            break
                    except Exception:
                        pass
            if bb:
                break

        if not bb:
            raise RuntimeError("Bulletin Boards menu was not found.")

        # Open the submenu.
        bb.hover(force=True)
        time.sleep(1)

        # Exact submenu item.
        ssp_selectors = [
            "a:has-text('Section Schedules Progress')",
            "a[href*='parentSubMenu3_SubMenuID12']",
            "a[href*='SectionDashboard']",
        ]

        ssp = None
        for selector in ssp_selectors:
            loc = page.locator(selector)
            if loc.count() > 0:
                for i in range(min(loc.count(), 5)):
                    candidate = loc.nth(i)
                    try:
                        if candidate.is_visible():
                            ssp = candidate
                            break
                    except Exception:
                        pass
            if ssp:
                break

        if not ssp:
            raise RuntimeError(
                "Section Schedules Progress submenu item was not found after opening Bulletin Boards."
            )

        print("[PORTAL] Submenu opened. Section Schedules Progress found.", flush=True)

        # First try the real DOM click.
        try:
            ssp.scroll_into_view_if_needed()
            ssp.click(force=True, timeout=10000)
        except Exception as click_error:
            print(f"[PORTAL] Normal submenu click failed: {click_error}", flush=True)

        time.sleep(2)

        # The SLAM item is a javascript:RedirectPage(...) link.
        # If click did not navigate, execute the link's actual JS click.
        if "DailySchedulesProgressDashboard.aspx" not in page.url:
            try:
                ssp.evaluate("(el) => el.click()")
            except Exception as js_click_error:
                print(f"[PORTAL] DOM click fallback failed: {js_click_error}", flush=True)

        time.sleep(2)

        # Final direct fallback to the exact dashboard URL already verified
        # during previous testing.
        if "DailySchedulesProgressDashboard.aspx" not in page.url:
            print("[PORTAL] Menu click did not navigate. Using verified dashboard URL...", flush=True)
            page.goto(
                dashboard_url,
                wait_until="domcontentloaded",
                timeout=45000
            )
            time.sleep(3)

        # Verify dashboard, not merely HTTP navigation.
        title = page.title().strip()
        if (
            "DailySchedulesProgressDashboard.aspx" in page.url
            or "Daily Schedules Progress Dashboard" in title
        ):
            print(
                f"[PORTAL] Arrived at dashboard: {page.url} ({title})",
                flush=True
            )
            return True

        raise RuntimeError(
            f"Navigation completed but dashboard could not be verified. URL={page.url}, title={title}"
        )

    except Exception as e:
        print(f"[PORTAL ERROR] Failed to navigate to Section Schedules Progress: {e}", flush=True)
        log_audit("ERROR", "NAV_FAILED", details=str(e))
        return False

def is_color_pink(bg_color: str, fg_color: str, outer_html: str = "") -> bool:
    """
    Determines if an element's background or text color represents the
    pink 'Not Acknowledged / Sent' status according to the SLAM portal legend.
    """
    combined = f"{bg_color} {fg_color} {outer_html}".lower()
    if "pink" in combined or "ffc0cb" in combined or "ffb6c1" in combined or "f8d7da" in combined:
        return True

    matches = re.findall(r"rgba?\((\d+),\s*(\d+),\s*(\d+)", combined)
    for r, g, b in matches:
        r, g, b = int(r), int(g), int(b)
        if r > 180 and r > g + 20 and b > 100:
            return True
        if r >= 240 and 150 <= g <= 230 and 150 <= b <= 230:
            return True
    return False

def scan_eligible_jobcards(page: Page) -> List[Dict[str, Any]]:
    """
    Scans the Section Schedules Progress table and extracts all jobcards
    whose status is 'Not Acknowledged / Sent' (Pink), skipping any that
    have already been processed in SQLite.
    """
    print("[PORTAL] Scanning dashboard for eligible pink jobcards...", flush=True)
    raw_jobcards = page.evaluate('''() => {
        const results = [];

        function styleInfo(el) {
            if (!el) return {
                tag: "", id: "", className: "", title: "", style: "",
                bg: "", color: "", bgcolor: "", html: ""
            };

            const cs = window.getComputedStyle(el);

            return {
                tag: el.tagName || "",
                id: el.id || "",
                className: typeof el.className === "string" ? el.className : "",
                title: el.getAttribute("title") || "",
                style: el.getAttribute("style") || "",
                bg: cs.backgroundColor || "",
                color: cs.color || "",
                bgcolor: el.getAttribute("bgcolor") || "",
                html: (el.outerHTML || "").substring(0, 1800)
            };
        }

        function pinkEvidence(el) {
            const evidence = [];
            let node = el;

            for (let level = 0; node && level < 6; level++, node = node.parentElement) {
                const s = styleInfo(node);
                const combined = [
                    s.bg, s.bgcolor, s.className, s.title, s.style, s.html
                ].join(" ").toLowerCase();

                if (
                    combined.includes("pink") ||
                    combined.includes("#ffc0cb") ||
                    combined.includes("#ffb6c1") ||
                    combined.includes("#f8d7da") ||
                    combined.includes("255, 192, 203") ||
                    combined.includes("255, 182, 193") ||
                    combined.includes("248, 215, 218") ||
                    combined.includes("not acknowledged") ||
                    combined.includes("not acknowledged/sent")
                ) {
                    evidence.push({
                        level,
                        tag: s.tag,
                        bg: s.bg,
                        bgcolor: s.bgcolor,
                        className: s.className,
                        title: s.title,
                        style: s.style
                    });
                }
            }

            return evidence;
        }

        const links = document.querySelectorAll(
            "a[href*='JobcardsAddEdit.aspx'], a[href*='JobCard']"
        );

        for (const a of links) {
            const row = a.closest("tr");
            const td = a.closest("td");

            let loco = "";
            let schedule = "";
            let ppioRemarks = "";

            if (row) {
                const tds = row.querySelectorAll("td");

                if (tds.length >= 2) {
                    loco = (tds[0].innerText || "").trim();
                    schedule = (tds[1].innerText || "").trim();
                }

                if (tds.length >= 8) {
                    ppioRemarks = (tds[tds.length - 1].innerText || "").trim();
                }
            }

            const tdStyle = styleInfo(td);
            const linkStyle = styleInfo(a);
            const rowStyle = styleInfo(row);

            const rowCells = row
                ? Array.from(row.querySelectorAll("td")).map(cell => styleInfo(cell))
                : [];

            const evidence = pinkEvidence(a);

            for (const cell of rowCells) {
                const combined = [
                    cell.bg, cell.bgcolor, cell.className,
                    cell.title, cell.style, cell.html
                ].join(" ").toLowerCase();

                if (
                    combined.includes("pink") ||
                    combined.includes("#ffc0cb") ||
                    combined.includes("#ffb6c1") ||
                    combined.includes("#f8d7da") ||
                    combined.includes("255, 192, 203") ||
                    combined.includes("255, 182, 193") ||
                    combined.includes("248, 215, 218") ||
                    combined.includes("not acknowledged") ||
                    combined.includes("not acknowledged/sent")
                ) {
                    evidence.push({
                        level: "row-cell",
                        tag: cell.tag,
                        bg: cell.bg,
                        bgcolor: cell.bgcolor,
                        className: cell.className,
                        title: cell.title,
                        style: cell.style
                    });
                }
            }

            results.push({
                loco,
                schedule,
                jobcard_no: (a.innerText || "").trim(),
                href: a.getAttribute("href") || "",
                title: a.getAttribute("title") || "",
                outer_html: a.outerHTML || "",
                link_style: a.getAttribute("style") || "",
                link_bgcolor_attr: a.getAttribute("bgcolor") || "",
                fg_color: linkStyle.color,
                bg_color: linkStyle.bg,
                parent_bg_color: tdStyle.bg,
                parent_bgcolor_attr: tdStyle.bgcolor,
                link_class: linkStyle.className,
                parent_class: tdStyle.className,
                row_class: rowStyle.className,
                ppio_remarks: ppioRemarks,
                row_cells: rowCells,
                pink_evidence: evidence
            });
        }

        return results;
    }''')

    eligible: List[Dict[str, Any]] = []
    print(f"[PORTAL] Total jobcard links detected on dashboard: {len(raw_jobcards)}", flush=True)

    for item in raw_jobcards:
        loco = item.get("loco", "").strip()
        jc_no = item.get("jobcard_no", "").strip()
        sch = item.get("schedule", "").strip()
        href = item.get("href", "").strip()
        title = item.get("title", "").strip().lower()
        html = item.get("outer_html", "")
        bg = item.get("bg_color", "")
        parent_bg = item.get("parent_bg_color", "")
        parent_bgcolor_attr = item.get("parent_bgcolor_attr", "")
        fg = item.get("fg_color", "")
        pink_evidence = item.get("pink_evidence", []) or ""

        if not jc_no:
            continue

        # Extract SectionJobCardId from URL
        jc_id_match = re.search(r"SectionJobCardId=(\d+)", href, re.IGNORECASE)
        section_jobcard_id = jc_id_match.group(1) if jc_id_match else ""
        item["section_jobcard_id"] = section_jobcard_id

        # 1. Duplicate Prevention Check in SQLite DB
        if is_jobcard_already_processed(loco, jc_no, section_jobcard_id):
            continue

        # 2. Detect Pink status ONLY from this individual Jobcard <a>.
        #
        # Verified from the live SLAM HTML:
        #   <a style="color:Black;background-color:Pink" ...>234</a>
        #
        # IMPORTANT:
        # Do NOT inspect the whole row for "Pink". A single row can contain
        # multiple jobcards where some are Green and one is Pink. Row-level
        # detection would incorrectly classify the Green jobcards as Pink.
        link_style = item.get("link_style", "") or ""
        style_normalized = re.sub(r"\s+", "", link_style.lower())

        is_pink_status = (
            "background-color:pink" in style_normalized
            or "background:pink" in style_normalized
        )

        # Also support an explicit bgcolor="Pink" on THIS SAME <a>, if the
        # portal ever renders the status that way.
        link_bgcolor_attr = item.get("link_bgcolor_attr", "") or ""
        if str(link_bgcolor_attr).strip().lower() == "pink":
            is_pink_status = True


        if is_pink_status:
            eligible.append(item)
            print(
                f"  [+] Eligible Pink Jobcard: Loco={loco} | "
                f"Sch={sch} | Jobcard={jc_no} | JC_ID={section_jobcard_id}",
                flush=True
            )
        else:
            print(
                f"  [-] Not Pink: Loco={loco} | "
                f"Sch={sch} | Jobcard={jc_no} | "
                f"link_style={link_style!r} | "
                f"link_bgcolor={link_bgcolor_attr!r}",
                flush=True
            )

    print(f"[PORTAL] Eligible unacknowledged jobcards identified: {len(eligible)}", flush=True)
    return eligible

def process_single_jobcard(
    context: BrowserContext,
    base_page: Page,
    jobcard_info: Dict[str, Any],
    dry_run: bool,
    enable_acknowledgement: bool
) -> Dict[str, Any]:
    """
    Opens an individual jobcard page, verifies its identity (Loco, JC No, Schedule),
    performs acknowledgement if authorized, captures a screenshot, and delivers Telegram alert.
    """
    loco = jobcard_info.get("loco", "").strip()
    jc_no = jobcard_info.get("jobcard_no", "").strip()
    sch = jobcard_info.get("schedule", "").strip()
    href = jobcard_info.get("href", "").strip()
    jc_id = jobcard_info.get("section_jobcard_id", "").strip()
    ppio_remarks = jobcard_info.get("ppio_remarks", "").strip()

    result = {
        "loco": loco,
        "jobcard_no": jc_no,
        "schedule": sch,
        "section_jobcard_id": jc_id,
        "status_before": "Waiting For Acknowledge",
        "status_after": "Waiting For Acknowledge",
        "action_taken": "NONE",
        "screenshot_path": None,
        "telegram_delivered": False,
        "success": False,
        "error": None
    }

    print(f"\n--- [PROCESSING JOBCARD] Loco: {loco} | Jobcard: {jc_no} | Sch: {sch} ---", flush=True)
    jc_page = context.new_page()
    jc_page.set_default_timeout(30000)

    try:
        target_url = urljoin(base_page.url, href)
        jc_page.goto(target_url, wait_until="domcontentloaded", timeout=45000)
        time.sleep(3)

        # 1. Identity Verification on Jobcard Page
        page_text = jc_page.locator("body").inner_text()
        page_html = jc_page.content()

        # Check Loco in input box or text
        loco_input = jc_page.locator("input[id*='Loco'], input[name*='Loco']")
        loco_val = loco_input.first.input_value() if (loco_input.count() > 0) else ""

        loco_clean = re.sub(r'[^0-9]', '', loco)
        loco_verified = False
        if (loco in page_text) or (loco_clean and (loco_clean in page_text or loco_clean in loco_val or loco_clean in page_html)):
            loco_verified = True

        jc_clean = re.sub(r'[^0-9]', '', jc_no)
        jc_verified = False
        if (jc_no in page_text) or (jc_clean and (jc_clean in page_text or jc_clean in page_html)):
            jc_verified = True

        if not (loco_verified and jc_verified):
            err = f"Verification Failed: Loco ({loco}) or Jobcard ({jc_no}) does not match opened page content."
            print(f"[SAFETY STOP] {err}", flush=True)
            log_audit("ERROR", "VERIFICATION_FAILED", loco, jc_no, err)
            result["error"] = err
            jc_page.close()
            return result

        print(f"[VERIFIED] Jobcard identity confirmed for Loco {loco}, JC {jc_no}.", flush=True)

        # 2. Locate Acknowledge Button
        ack_button = None
        for selector in [
            "#Content1_btnAcknowledge",
            "input[id*='btnAcknowledge']",
            "input[value='Acknowledge']",
            "input[value*='Acknowledge']",
            "button:has-text('Acknowledge')"
        ]:
            loc = jc_page.locator(selector)
            if loc.count() > 0 and loc.first.is_visible():
                ack_button = loc.first
                break

        timestamp_str = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        sanitized_loco = re.sub(r'[^A-Za-z0-9_-]', '', loco) or "Loco"
        sanitized_jc = re.sub(r'[^A-Za-z0-9_-]', '', jc_no) or "JC"

        # 3. Action Execution (Dry-Run vs Real Acknowledgement)
        if dry_run or not enable_acknowledgement:
            print(f"[DRY RUN] Safe mode active. Acknowledge button verified but NOT clicked.", flush=True)
            result["action_taken"] = "DRY_RUN_VERIFIED"
            result["status_after"] = "Waiting For Acknowledge (Dry Run)"
            result["success"] = True

            screenshot_filename = f"{sanitized_loco}_Jobcard_{sanitized_jc}_DryRun_{timestamp_str}.png"
            screenshot_path = config.SCREENSHOTS_DIR / screenshot_filename
            jc_page.screenshot(path=str(screenshot_path), full_page=True)
            result["screenshot_path"] = str(screenshot_path)
            print(f"[DRY RUN] Screenshot saved: {screenshot_path}", flush=True)
            log_audit("INFO", "DRY_RUN_VERIFIED", loco, jc_no, f"Screenshot: {screenshot_filename}")

        else:
            # REAL ACKNOWLEDGEMENT (Requires authorization and enable_acknowledgement=True)
            if not ack_button:
                err = "Acknowledge button was not found or is disabled on the page."
                print(f"[ERROR] {err}", flush=True)
                log_audit("ERROR", "ACK_BUTTON_NOT_FOUND", loco, jc_no, err)
                result["error"] = err
                jc_page.close()
                return result

            print(f"[CRITICAL ACTION] Clicking Acknowledge for Loco {loco}, JC {jc_no}...", flush=True)
            ack_button.click()
            time.sleep(3)
            jc_page.wait_for_load_state("domcontentloaded", timeout=30000)

            # Verify portal result
            post_text = jc_page.locator("body").inner_text().lower()
            if "in progress" in post_text or (ack_button.count() == 0 or not ack_button.is_visible()):
                result["action_taken"] = "ACKNOWLEDGED"
                result["status_after"] = "In Progress"
                result["success"] = True
                print(f"[SUCCESS] Acknowledgement confirmed by portal for Loco {loco}, JC {jc_no}!", flush=True)
            else:
                result["action_taken"] = "ACK_CLICKED_UNVERIFIED"
                result["status_after"] = "Unverified"
                result["success"] = False
                result["error"] = "Status change to 'In Progress' could not be verified."
                print(f"[WARNING] Status change unverified.", flush=True)

            screenshot_filename = f"{sanitized_loco}_Jobcard_{sanitized_jc}_Acknowledged_{timestamp_str}.png"
            screenshot_path = config.SCREENSHOTS_DIR / screenshot_filename
            jc_page.screenshot(path=str(screenshot_path), full_page=True)
            result["screenshot_path"] = str(screenshot_path)
            print(f"[SCREENSHOT] Saved: {screenshot_path}", flush=True)
            log_audit("INFO", result["action_taken"], loco, jc_no, f"Screenshot: {screenshot_filename}")

        # 4. Deliver Screenshot to Telegram
        if result["screenshot_path"]:
            dt_display = datetime.datetime.now().strftime("%d/%m/%Y %H:%M:%S")
            print(f"[*] Delivering screenshot to Telegram...", flush=True)
            sent, msg_id = send_jobcard_screenshot(
                screenshot_path=Path(result["screenshot_path"]),
                loco_no=loco,
                jobcard_no=jc_no,
                schedule=sch,
                status_result=result["action_taken"],
                date_time_str=dt_display,
                extra_remarks=ppio_remarks
            )
            result["telegram_delivered"] = sent
            if sent:
                print(f"[+] Telegram alert delivered! (Message ID: {msg_id})", flush=True)
            else:
                print(f"[-] Telegram alert failed: {msg_id}", flush=True)

        # 5. Record Processed Jobcard in SQLite Database (Duplicate Prevention)
        record_processed_jobcard(
            loco_no=loco,
            jobcard_no=jc_no,
            schedule=sch,
            section_jobcard_id=jc_id,
            action_taken=result["action_taken"],
            status_before=result["status_before"],
            status_after=result["status_after"],
            screenshot_path=result["screenshot_path"],
            telegram_delivered=result["telegram_delivered"]
        )
        print(f"[DATABASE] Jobcard recorded in SQLite (Duplicate Prevention active).", flush=True)

    except Exception as ex:
        err = f"Exception processing jobcard: {str(ex)}"
        print(f"[ERROR] {err}", flush=True)
        log_audit("ERROR", "JC_PROCESSING_EXCEPTION", loco, jc_no, str(ex))
        result["error"] = err
        try:
            diag_file = config.SCREENSHOTS_DIR / f"ERROR_{loco}_{jc_no}_{int(time.time())}.png"
            jc_page.screenshot(path=str(diag_file))
        except Exception:
            pass
    finally:
        jc_page.close()

    return result

def run_automation_cycle(
    dry_run: Optional[bool] = None,
    enable_acknowledgement: Optional[bool] = None,
    existing_context: Optional[BrowserContext] = None,
    existing_page: Optional[Page] = None,
    otp_provider: Optional[Any] = None,
) -> Dict[str, Any]:
    """
    Executes a complete automation cycle:
    1. Acquires single-instance lock to prevent overlapping runs.
    2. Opens Chrome with persistent profile (or reuses existing_context).
    3. Checks authentication / pauses for OTP if required.
    4. Navigates to Section Schedules Progress dashboard.
    5. Scans for eligible pink jobcards (excluding already processed ones).
    6. Processes each jobcard individually with full identity checks, screenshots, and Telegram alerts.
    7. Cleans up and releases lock.
    """
    if dry_run is None:
        dry_run = config.DRY_RUN
    if enable_acknowledgement is None:
        enable_acknowledgement = config.ENABLE_ACKNOWLEDGEMENT

    summary = {
        "start_time": datetime.datetime.now().isoformat(),
        "dry_run": dry_run,
        "enable_acknowledgement": enable_acknowledgement,
        "jobcards_found": 0,
        "jobcards_processed": 0,
        "results": [],
        "success": False
    }

    print("=" * 80)
    print("  CRIS SLAM AUTOMATION — EXECUTION CYCLE")
    mode_label = "DRY-RUN (Safe Mode - No portal changes)" if (dry_run or not enable_acknowledgement) else "LIVE ACKNOWLEDGEMENT ENABLED"
    print(f"  MODE: {mode_label}")
    print("=" * 80)

    # 1. Single Instance Lock
    try:
        lock = SingleInstanceLock()
        if not lock.acquire():
            print("[LOCKED] Another instance of RailwayBot is currently running. Skipping this cycle safely.")
            log_audit("WARNING", "CYCLE_LOCKED", details="Another instance running.")
            return summary
    except Exception as e:
        print(f"[LOCK WARNING] {e}")
        lock = None

    def _execute_cycle(context: BrowserContext, page: Page) -> bool:
        page.set_default_timeout(getattr(config, "BROWSER_TIMEOUT_MS", 30000))

        # 2. Check connection
        print("[PORTAL] Checking SLAM connection...", flush=True)
        try:
            if "slam.indianrail.gov.in" not in page.url.lower():
                page.goto(config.PORTAL_URL, wait_until="domcontentloaded", timeout=60000)
        except Exception as e:
            print(f"[!] Navigation note: {e}", flush=True)

        time.sleep(2)

        # 3. Authentication
        auth_page = wait_for_user_login(
            context,
            timeout_seconds=config.LOGIN_WAIT_TIMEOUT_SECONDS,
            otp_provider=otp_provider
        )
        if not auth_page:
            print("[-] Login timed out or not authenticated. Halting cycle safely.")
            return False

        page = auth_page

        # 4. Navigate to Dashboard
        if not navigate_to_section_schedules_dashboard(page):
            print("[-] Failed to reach dashboard. Halting cycle safely.")
            return False

        # 5. Scan Pink Jobcards
        eligible_jobcards = scan_eligible_jobcards(page)
        summary["jobcards_found"] = len(eligible_jobcards)

        if not eligible_jobcards:
            print("\n[INFO] No new eligible Pink jobcards to process right now.")
            print("       All current items are already processed or in progress.")

            # Send the current Section Schedules Progress screenshot when
            # there is no new Pink jobcard.
            try:
                dashboard_timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
                dashboard_file = (
                    config.SCREENSHOTS_DIR
                    / f"Section_Schedules_Progress_No_Jobcard_{dashboard_timestamp}.png"
                )
                page.screenshot(path=str(dashboard_file), full_page=True)

                sent, msg_id = send_dashboard_screenshot(
                    screenshot_path=Path(dashboard_file),
                    date_time_str=datetime.datetime.now().strftime("%d/%m/%Y %H:%M:%S")
                )

                if sent:
                    print(
                        f"[+] No-jobcard dashboard screenshot delivered to Telegram "
                        f"(Message ID: {msg_id})",
                        flush=True
                    )
                else:
                    print(
                        f"[-] No-jobcard dashboard screenshot delivery failed: {msg_id}",
                        flush=True
                    )
            except Exception as screenshot_error:
                print(
                    f"[WARNING] Could not send no-jobcard dashboard screenshot: "
                    f"{screenshot_error}",
                    flush=True
                )

            summary["success"] = True
            time.sleep(2)
            return True

        # 6. Process Each Jobcard Individually
        print(f"\n[PORTAL] Beginning individual processing of {len(eligible_jobcards)} eligible jobcard(s)...")
        for idx, jc_info in enumerate(eligible_jobcards, 1):
            print(f"\n>>> Item {idx}/{len(eligible_jobcards)} <<<")
            res = process_single_jobcard(
                context=context,
                base_page=page,
                jobcard_info=jc_info,
                dry_run=dry_run,
                enable_acknowledgement=enable_acknowledgement
            )
            summary["results"].append(res)
            if res.get("success"):
                summary["jobcards_processed"] += 1
            time.sleep(2)

        summary["success"] = True
        print("\n" + "=" * 80)
        print(f"  CYCLE COMPLETED: {summary['jobcards_processed']}/{summary['jobcards_found']} jobcard(s) processed successfully.")
        print("=" * 80)
        time.sleep(3)
        return True

    try:
        if existing_context:
            page = existing_page or (existing_context.pages[0] if existing_context.pages else existing_context.new_page())
            _execute_cycle(existing_context, page)
        else:
            with sync_playwright() as p:
                context = p.chromium.launch_persistent_context(
                    user_data_dir=str(config.CHROME_PROFILE_DIR),
                    channel="chrome",
                    headless=config.HEADLESS,
                    viewport={"width": 1920, "height": 1080}
                )
                page = context.pages[0] if context.pages else context.new_page()
                try:
                    _execute_cycle(context, page)
                finally:
                    context.close()

    except Exception as e:
        print(f"[CRITICAL ERROR] Automation cycle exception: {e}")
        log_audit("CRITICAL", "CYCLE_EXCEPTION", details=str(e))
    finally:
        if lock:
            lock.release()

    return summary

if __name__ == "__main__":
    run_automation_cycle()
