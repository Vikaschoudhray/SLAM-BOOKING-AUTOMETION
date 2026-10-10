"""
RailwayBot SLAM Authentication Module
Reusable Playwright login module for the Indian Railways CRIS SLAM portal.

Credentials:
    SLAM_USERNAME
    SLAM_PASSWORD
Configured in C:\\RailwayBot\\.env or config.py.
Passwords and OTPs are never logged or exposed.
OTP remains strictly user-entered.
Arithmetic CAPTCHA is detected, normalized, and solved automatically.
"""

import os
import re
import sys
import time
from pathlib import Path
from typing import Optional, Any

from playwright.sync_api import Page, TimeoutError as PlaywrightTimeoutError

# Ensure console supports UTF-8 / safe character printing on Windows
try:
    if sys.stdout and hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if sys.stderr and hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

try:
    import config
except ImportError:
    config = None


# Stable selectors for the CRIS SLAM portal
LOGIN_URL = getattr(config, "PORTAL_URL", "https://slam.indianrail.gov.in/SLAM/Login.aspx")
LOGS_DIR = getattr(config, "LOGS_DIR", Path(r"C:\RailwayBot\logs"))

USERNAME_SELECTORS = [
    "#ContentPlaceHolder1_txtUserName",
    "input[name*='txtUserName']",
    "input[id*='txtUserName']",
    "input[placeholder*='UserName']",
    "input[type='text']",
]

PASSWORD_SELECTORS = [
    "#ContentPlaceHolder1_txtPassword",
    "input[name*='txtPassword']",
    "input[id*='txtPassword']",
    "input[type='password']",
]

CAPTCHA_EQUATION_SELECTORS = [
    "#ContentPlaceHolder1_captchaEquation",
    "span[id*='captchaEquation']",
    "#ContentPlaceHolder1_captchaDiv",
    "div[id*='captchaDiv']",
    "[id*='captchaEquation']",
]

CAPTCHA_HIDDEN_ANSWER_SELECTORS = [
    "#ContentPlaceHolder1_captchaAnswer",
    "input[name*='captchaAnswer']",
    "input[id*='captchaAnswer']",
]

CAPTCHA_INPUT_SELECTORS = [
    "#ContentPlaceHolder1_txtCaptcha",
    "input[name*='txtCaptcha']",
    "input[id*='txtCaptcha']",
    "input[placeholder*='CAPTCHA']",
]

GET_OTP_SELECTORS = [
    "#ContentPlaceHolder1_BtnGetOtp",
    "input[name*='BtnGetOtp']",
    "input[id*='BtnGetOtp']",
    "input[value='Get OTP']",
    "button:has-text('Get OTP')",
]

OTP_INPUT_SELECTORS = [
    "#ContentPlaceHolder1_txtOTP",
    "input[name*='txtOTP']",
    "input[id*='txtOTP']",
    "input[id*='OTP']",
    "input[name*='OTP']",
    "input[placeholder*='OTP']",
]

SIGN_IN_SELECTORS = [
    "#ContentPlaceHolder1_btnSignIn",
    "input[name*='btnSignIn']",
    "input[id*='btnSignIn']",
    "input[value*='Sign In']",
    "input[value*='Login']",
    "button:has-text('Sign In')",
    "button:has-text('Login')",
]

ERROR_LABEL_SELECTORS = [
    "#ContentPlaceHolder1_lblError",
    "span[id*='lblError']",
    ".alert-danger",
]


class SLAMAuth:
    """
    Reusable authentication handler for the Indian Railways SLAM Portal.
    """

    def __init__(
        self,
        page: Page,
        username: Optional[str] = None,
        password: Optional[str] = None,
        otp_provider: Optional[Any] = None,
    ):
        self.page = page
        self.otp_provider = otp_provider
        
        # Load username safely from args, config, or env
        resolved_user = username
        if not resolved_user and config:
            resolved_user = getattr(config, "SLAM_USERNAME", "")
        if not resolved_user:
            resolved_user = os.getenv("SLAM_USERNAME", "")
        self.username = (resolved_user or "").strip()

        # Load password safely from args, config, or env (never printed)
        resolved_pass = password
        if not resolved_pass and config:
            resolved_pass = getattr(config, "SLAM_PASSWORD", "")
        if not resolved_pass:
            resolved_pass = os.getenv("SLAM_PASSWORD", "")
        self.password = resolved_pass or ""

    @staticmethod
    def normalize_captcha_text(text: str) -> str:
        """
        Normalizes whitespace and Unicode operators before solving.
        Supports: +, -, −, –, —, x, X, ×, *, /, ÷
        """
        if not text:
            return ""
        # Clean whitespace and non-breaking spaces
        cleaned = text.replace("\xa0", " ").strip()
        # Normalize multiplication
        cleaned = cleaned.replace("×", "*").replace("x", "*").replace("X", "*")
        # Normalize subtraction and minus variants
        cleaned = cleaned.replace("−", "-").replace("–", "-").replace("—", "-")
        # Normalize division
        cleaned = cleaned.replace("÷", "/")
        return cleaned

    @classmethod
    def solve_captcha(cls, text: str) -> str:
        """
        Evaluates an arithmetic CAPTCHA expression (e.g. '12 + 7 = ?', '15 × 4 = ?').
        Returns the calculated answer as a string integer.
        """
        cleaned = cls.normalize_captcha_text(text)
        match = re.search(
            r"(-?\d+(?:\.\d+)?)\s*([\+\-\*\/])\s*(-?\d+(?:\.\d+)?)",
            cleaned,
        )
        if not match:
            raise ValueError(f"CAPTCHA format not recognized: {text!r}")

        a = float(match.group(1))
        op = match.group(2)
        b = float(match.group(3))

        if op == "+":
            result = a + b
        elif op == "-":
            result = a - b
        elif op == "*":
            result = a * b
        elif op == "/":
            if b == 0:
                raise ValueError("CAPTCHA division by zero")
            result = a / b
        else:
            raise ValueError(f"Unsupported CAPTCHA operator: {op}")

        return str(int(result)) if result.is_integer() else str(result)

    def _ensure_credentials(self) -> None:
        """Prompts for missing credentials if not provided in .env."""
        if not self.username:
            self.username = input("Enter SLAM Username: ").strip()

        if not self.password:
            from getpass import getpass
            self.password = getpass("Enter SLAM Password: ").strip()

        if not self.username or not self.password:
            raise RuntimeError("SLAM username and password are required for authentication.")

    def is_logged_in(self) -> bool:
        """
        Checks if the current session is actively authenticated in SLAM.
        Verifies URL and presence of logged-in portal elements.
        """
        try:
            url = self.page.url.lower()
            if "about:blank" in url:
                return False

            # If URL is inside SLAM portal and not on Login.aspx
            if "slam.indianrail.gov.in" in url and "login.aspx" not in url:
                return True

            # Check for known logged-in DOM elements (e.g. Logout, Bulletin Boards, Jobcards)
            logged_in_selectors = [
                "a:has-text('Logout')",
                "a:has-text('Bulletin Boards')",
                "span:has-text('Bulletin Boards')",
                "a:has-text('Jobcards')",
                "#ctl00_lblUserName",
                "#ctl00_btnLogout",
            ]
            for sel in logged_in_selectors:
                if self.page.locator(sel).count() > 0:
                    return True

        except Exception:
            pass

        return False

    def save_debug_diagnostics(self) -> None:
        """
        Saves diagnostic screenshot and sanitized DOM without exposing credentials.
        """
        try:
            LOGS_DIR.mkdir(parents=True, exist_ok=True)
            screenshot_path = LOGS_DIR / "captcha_debug.png"
            html_path = LOGS_DIR / "captcha_debug.html"

            self.page.screenshot(path=str(screenshot_path))

            # Sanitize passwords before saving HTML
            raw_html = self.page.content()
            sanitized_html = re.sub(
                r'(<input[^>]*type=["\']password["\'][^>]*value=["\'])[^"\']*(["\'])',
                r'\1***\2',
                raw_html,
                flags=re.IGNORECASE,
            )
            html_path.write_text(sanitized_html, encoding="utf-8")
            print(f"[SLAM AUTH] Diagnostic screenshot saved to {screenshot_path}")
            print(f"[SLAM AUTH] Diagnostic DOM saved to {html_path}")
        except Exception as e:
            print(f"[SLAM AUTH WARNING] Could not save diagnostic files: {e}")

    def _find_first_visible(self, selectors: list[str], timeout_ms: int = 5000):
        """Helper to find the first visible element among candidate selectors."""
        for sel in selectors:
            try:
                loc = self.page.locator(sel)
                if loc.count() > 0 and loc.first.is_visible():
                    return loc.first
            except Exception:
                pass
        return None

    def get_server_error_message(self) -> Optional[str]:
        """Checks if ASP.NET returned an error message."""
        for sel in ERROR_LABEL_SELECTORS:
            try:
                loc = self.page.locator(sel)
                if loc.count() > 0:
                    text = loc.first.inner_text().strip()
                    if text:
                        return text
            except Exception:
                pass
        return None

    def detect_and_solve_captcha(self) -> Optional[str]:
        """
        Detects the arithmetic CAPTCHA from DOM, calculates the answer,
        and returns it as a string. Returns None if detection fails.
        """
        raw_text = ""
        # 1. Try equation text selectors
        for sel in CAPTCHA_EQUATION_SELECTORS:
            try:
                loc = self.page.locator(sel)
                if loc.count() > 0:
                    text = loc.first.inner_text().strip()
                    if any(op in text for op in ["+", "-", "−", "–", "×", "x", "X", "*", "/", "÷"]):
                        raw_text = text
                        break
            except Exception:
                pass

        # 2. Try solving arithmetic challenge if text was found
        if raw_text:
            try:
                answer = self.solve_captcha(raw_text)
                print(f"[SLAM AUTH] CAPTCHA detected: {raw_text}")
                print(f"[SLAM AUTH] CAPTCHA answer calculated: {answer}")
                return answer
            except Exception as ex:
                print(f"[SLAM AUTH] CAPTCHA parse warning on '{raw_text}': {ex}")

        # 3. Check hidden answer element if equation text was unavailable
        for sel in CAPTCHA_HIDDEN_ANSWER_SELECTORS:
            try:
                loc = self.page.locator(sel)
                if loc.count() > 0:
                    val = (loc.first.get_attribute("value") or "").strip()
                    if val.isdigit():
                        print(f"[SLAM AUTH] CAPTCHA detected from form metadata.")
                        print(f"[SLAM AUTH] CAPTCHA answer calculated: {val}")
                        return val
            except Exception:
                pass

        return None

    def login(self, force: bool = False) -> bool:
        """
        Executes the full SLAM authentication flow:
        1. Checks whether already authenticated -> reuses existing session.
        2. If not, opens login page.
        3. Loads credentials from .env.
        4. Fills username and password.
        5. Detects and solves arithmetic CAPTCHA automatically.
        6. Clicks Get OTP.
        7. Awaits OTP input field.
        8. Prompts user for manual OTP entry.
        9. Submits login and verifies session.
        """
        self._ensure_credentials()
        print("[SLAM AUTH] Credentials loaded.")

        # Check existing session before navigating
        if not force and self.is_logged_in():
            print("[SLAM AUTH] Existing session is active. Reusing authenticated session.")
            return True

        print("[SLAM AUTH] Opening login page...")
        try:
            self.page.goto(LOGIN_URL, wait_until="domcontentloaded", timeout=60000)
            self.page.wait_for_timeout(2000)
        except Exception as e:
            print(f"[SLAM AUTH WARNING] Navigation note: {e}")

        # After navigating to Login.aspx, if session was already authenticated,
        # SLAM redirects to home/dashboard.
        if not force and self.is_logged_in():
            print("[SLAM AUTH] Existing session is active. Reusing authenticated session.")
            return True

        # 1. Fill Username
        user_loc = None
        for sel in USERNAME_SELECTORS:
            try:
                loc = self.page.locator(sel)
                if loc.count() > 0:
                    loc.first.wait_for(state="visible", timeout=15000)
                    user_loc = loc.first
                    break
            except Exception:
                pass

        if not user_loc:
            print("[SLAM AUTH ERROR] Username field not found on login page.")
            self.save_debug_diagnostics()
            return False

        user_loc.fill(self.username)

        # 2. Fill Password (never logged)
        pass_loc = None
        for sel in PASSWORD_SELECTORS:
            try:
                loc = self.page.locator(sel)
                if loc.count() > 0 and loc.first.is_visible():
                    pass_loc = loc.first
                    break
            except Exception:
                pass

        if not pass_loc:
            print("[SLAM AUTH ERROR] Password field not found on login page.")
            self.save_debug_diagnostics()
            return False

        pass_loc.fill(self.password)

        # 3. Detect and Solve CAPTCHA
        captcha_answer = self.detect_and_solve_captcha()

        # Locate CAPTCHA input field
        captcha_input_loc = None
        for sel in CAPTCHA_INPUT_SELECTORS:
            try:
                loc = self.page.locator(sel)
                if loc.count() > 0 and loc.first.is_visible():
                    captcha_input_loc = loc.first
                    break
            except Exception:
                pass

        if not captcha_input_loc:
            print("[SLAM AUTH ERROR] CAPTCHA input field not detected.")
            self.save_debug_diagnostics()
            return False

        if captcha_answer:
            captcha_input_loc.fill("")
            captcha_input_loc.fill(captcha_answer)
            print("[SLAM AUTH] CAPTCHA filled.")
        else:
            print("[SLAM AUTH WARNING] Could not automatically solve CAPTCHA.")
            self.save_debug_diagnostics()
            manual_ans = input("[ACTION REQUIRED] Enter CAPTCHA answer shown on screen: ").strip()
            if not manual_ans:
                return False
            captcha_input_loc.fill(manual_ans)
            print("[SLAM AUTH] CAPTCHA filled manually.")

        # 4. Click Get OTP
        get_otp_btn = None
        for sel in GET_OTP_SELECTORS:
            try:
                loc = self.page.locator(sel)
                if loc.count() > 0 and loc.first.is_visible():
                    get_otp_btn = loc.first
                    break
            except Exception:
                pass

        if not get_otp_btn:
            print("[SLAM AUTH ERROR] 'Get OTP' button not found.")
            self.save_debug_diagnostics()
            return False

        get_otp_btn.click()
        print("[SLAM AUTH] Get OTP clicked.")

        # Wait for postback / page response
        try:
            self.page.wait_for_load_state("domcontentloaded", timeout=15000)
        except Exception:
            pass
        self.page.wait_for_timeout(2000)

        # Check for immediate server error message
        server_error = self.get_server_error_message()
        if server_error:
            print(f"[SLAM AUTH ERROR] Portal returned: {server_error}")
            self.save_debug_diagnostics()
            # If invalid captcha, could retry or abort
            return False

        # 5. Wait for OTP field to appear
        otp_loc = None
        waited_seconds = 0
        max_otp_wait = 25
        print("[SLAM AUTH] Waiting for OTP field to appear...")

        while waited_seconds < max_otp_wait:
            for sel in OTP_INPUT_SELECTORS:
                try:
                    loc = self.page.locator(sel)
                    if loc.count() > 0 and loc.first.is_visible():
                        otp_loc = loc.first
                        break
                except Exception:
                    pass
            if otp_loc:
                break
            time.sleep(1)
            waited_seconds += 1

        if not otp_loc:
            print("[SLAM AUTH ERROR] OTP field did not appear after Get OTP.")
            err = self.get_server_error_message()
            if err:
                print(f"[SLAM AUTH ERROR] Portal error details: {err}")
            self.save_debug_diagnostics()
            return False

        # Re-fill password if ASP.NET cleared it upon postback
        try:
            for sel in PASSWORD_SELECTORS:
                loc = self.page.locator(sel)
                if loc.count() > 0 and loc.first.is_visible():
                    current_val = loc.first.input_value()
                    if not current_val:
                        loc.first.fill(self.password)
                    break
        except Exception:
            pass

        # 6. Manual OTP Entry (Supports: Telegram reply, Browser direct entry, or Terminal input)
        print("\n" + "=" * 70, flush=True)
        print("[ACTION REQUIRED] SLAM OTP has been sent to authorized mobile!", flush=True)
        print(">> Option A: Enter OTP directly in the opened Chrome window and click Sign In.", flush=True)
        print(">> Option B: Reply with OTP on Telegram if using Telegram Bot.", flush=True)
        print(">> Option C: Type OTP here in terminal and press Enter.", flush=True)
        print("=" * 70, flush=True)

        import threading
        user_otps = []

        # 1. Listen to external provider (e.g. Telegram) if configured
        if self.otp_provider:
            def _read_external():
                try:
                    val = self.otp_provider()
                    if val:
                        user_otps.append(str(val).strip())
                except Exception:
                    pass
            t_ext = threading.Thread(target=_read_external, daemon=True)
            t_ext.start()

        # 2. Listen to terminal
        def _read_terminal():
            try:
                val = input("[ACTION REQUIRED] Enter OTP: ").strip()
                if val:
                    user_otps.append(val)
            except Exception:
                pass

        t_term = threading.Thread(target=_read_terminal, daemon=True)
        t_term.start()

        otp_wait_seconds = 0
        max_user_otp_wait = 180  # Wait up to 3 minutes for OTP

        while otp_wait_seconds < max_user_otp_wait:
            time.sleep(1)
            otp_wait_seconds += 1

            # Check if OTP was received via Telegram or Terminal
            if user_otps:
                entered_otp = user_otps[0]
                otp_loc.fill(entered_otp)
                for sel in SIGN_IN_SELECTORS:
                    loc = self.page.locator(sel)
                    if loc.count() > 0 and loc.first.is_visible():
                        loc.first.click()
                        break
                break

            # Check if user completed login directly in Chrome
            if self.is_logged_in():
                print("[SLAM AUTH] Login detected from browser!", flush=True)
                return True

            # Check if user typed OTP in Chrome and hasn't clicked Sign In yet
            try:
                val_in_browser = otp_loc.input_value().strip()
                if len(val_in_browser) >= 4:
                    time.sleep(1)
                    for sel in SIGN_IN_SELECTORS:
                        loc = self.page.locator(sel)
                        if loc.count() > 0 and loc.first.is_visible():
                            loc.first.click()
                            break
                    break
            except Exception:
                pass

        # 8. Wait for authentication navigation
        print("[SLAM AUTH] Verifying authentication...")
        try:
            self.page.wait_for_url(
                re.compile(r"^(?!.*Login\.aspx).*$", re.IGNORECASE),
                timeout=20000,
            )
        except Exception:
            pass

        self.page.wait_for_timeout(2000)

        if self.is_logged_in():
            print("[SLAM AUTH] Login successful.")
            return True

        err = self.get_server_error_message()
        if err:
            print(f"[SLAM AUTH ERROR] Login failed: {err}")
        else:
            print(f"[SLAM AUTH ERROR] Login not confirmed. Current URL: {self.page.url}")

        self.save_debug_diagnostics()
        return False
