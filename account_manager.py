# account_manager.py
import asyncio
import random
import json
import os
import requests
import re
import bleach
import shutil
from datetime import datetime
from typing import Optional, List, Tuple
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options
from PyQt5.QtCore import pyqtSignal, QObject, Qt, QMetaObject, Q_ARG, QThreadPool, QCryptographicHash
from PyQt5.QtWidgets import QApplication, QMessageBox
import traceback
import orjson
import chromedriver_autoinstaller
from concurrent.futures import ThreadPoolExecutor
from tenacity import retry, wait_fixed, stop_after_attempt
from utils import SessionManager, load_cookies, encrypt_data, decrypt_data, solve_captcha, get_access_token, predictive_ban_detection, simulate_human_behavior

class AccountManager(QObject):
    errorOccurred = pyqtSignal(str)
    statusUpdated = pyqtSignal(str)
    progressUpdated = pyqtSignal(int, int)

    def __init__(self, app, config, db, log_manager):
        super().__init__()
        self.app = app
        self.config = config
        self.db = db
        self.log_manager = log_manager
        self.session_manager = SessionManager(self.app, self.config)
        self.max_retries = self.config.get("max_retries", 3)
        self.default_delay = self.config.get("default_delay", 5)
        self.thread_pool = QThreadPool.globalInstance()
        self.thread_pool.setMaxThreadCount(4)
        chromedriver_autoinstaller.install()
        if self.log_manager:
            self.log_manager.add_log("System", None, "Accounts", "Info", "AccountManager initialized successfully")
        self.statusUpdated.emit("Info: AccountManager initialized successfully")

    def _log(self, message: str, level: str, fb_id: str = "System", action: str = "Accounts") -> None:
        try:
            if self.log_manager:
                self.log_manager.add_log(fb_id, None, action, level, f"{message}\n{traceback.format_exc() if level == 'Error' else ''}")
            self.statusUpdated.emit(f"{level}: {message}")
        except Exception as e:
            print(f"Error logging: {str(e)}\n{traceback.format_exc()}")

    def add_accounts(self, accounts_text: str) -> None:
        try:
            lines = accounts_text.strip().splitlines()
            total = len(lines)
            added_count = 0
            with ThreadPoolExecutor(max_workers=4) as executor:
                for i, line in enumerate(lines):
                    if not line.strip():
                        continue
                    parts = line.split("|")
                    if len(parts) < 3:
                        self._log(f"Invalid account format: {line}", "Warning")
                        self.statusUpdated.emit(f"Invalid account format: {line}")
                        continue
                    fb_id, password, email = bleach.clean(parts[0].strip()), bleach.clean(parts[1].strip()), bleach.clean(parts[2].strip())
                    proxy = bleach.clean(parts[3].strip()) if len(parts) > 3 else None
                    access_token = bleach.clean(parts[4].strip()) if len(parts) > 4 else None
                    app_id = bleach.clean(parts[5].strip()) if len(parts) > 5 else None
                    if self.db.get_account(fb_id):
                        self._log(f"Account {fb_id} already exists", "Warning", fb_id)
                        self.statusUpdated.emit(f"Account {fb_id} already exists")
                        continue
                    if not re.match(r"[^@]+@[^@]+\.[^@]+", email):
                        self._log(f"Invalid email format for {fb_id}: {email}", "Warning", fb_id)
                        self.statusUpdated.emit(f"Invalid email format for {fb_id}: {email}")
                        continue
                    if len(password) < 6:
                        self._log(f"Password too short for {fb_id}", "Warning", fb_id)
                        self.statusUpdated.emit(f"Password too short for {fb_id}")
                        continue
                    if shutil.disk_usage("/").free < 1024 * 1024:
                        self._log("Insufficient disk space", "Error")
                        self.statusUpdated.emit("Insufficient disk space")
                        return
                    encrypted_password = QCryptographicHash.hash(password.encode(), QCryptographicHash.Sha256).hex()
                    is_developer = 1 if access_token or app_id else 0
                    executor.submit(self.db.add_account, fb_id, encrypted_password, email, proxy, access_token, is_developer)
                    self._log(f"Added account: {fb_id}{' (Developer)' if is_developer else ''}", "Info", fb_id)
                    self.statusUpdated.emit(f"Added account: {fb_id}{' (Developer)' if is_developer else ''}")
                    added_count += 1
                    self.progressUpdated.emit(i + 1, total)
            self.db.conn.executemany("CREATE INDEX IF NOT EXISTS idx_fb_id ON accounts(fb_id)", [])
            self.db.conn.executemany("CREATE INDEX IF NOT EXISTS idx_timestamp ON accounts(last_login)", [])
            self.statusUpdated.emit(f"Added {added_count} accounts successfully")
            self._log(f"Added {added_count} accounts successfully", "Info")
        except Exception as e:
            self._log(f"Failed to add accounts: {str(e)}", "Error")
            self.statusUpdated.emit(f"Error adding accounts: {str(e)}")
            self.errorOccurred.emit(str(e))
            QMessageBox.critical(None, "Error", f"Failed to add accounts: {str(e)}")

    def _get_chrome_options(self, index: int, mobile_view: bool = True, visible: bool = True) -> Options:
        try:
            chrome_options = Options()
            chrome_options.add_argument("--disable-notifications")
            if mobile_view:
                chrome_options.add_argument(f"--window-size={self.config.get('mobile_size', '360x640').replace('x', ',')}")
            if not visible:
                chrome_options.add_argument("--headless")
            chrome_options.add_argument("--disable-gpu")
            chrome_options.add_argument("--no-sandbox")
            chrome_options.add_argument(f"--window-position={index * 400 % 1600},{index * 400 // 1600}")
            chrome_options.binary_location = os.path.join(os.path.dirname(os.path.abspath(__file__)), self.config.get("chrome_path", "drivers/chrome.exe"))
            return chrome_options
        except Exception as e:
            self._log(f"Error setting Chrome options: {str(e)}", "Error")
            self.statusUpdated.emit(f"Error setting Chrome options: {str(e)}")
            return Options()

    async def login_all_accounts(self, login_mode: str = "Selenium", preliminary_interaction: bool = True, mobile_view: bool = True, visible: bool = True) -> List[Tuple]:
        try:
            accounts = []
            try:
                accounts = self.db.get_accounts()
            except Exception as e:
                self._log(f"DB Error fetching accounts: {str(e)}", "Error")
                return []
            if not accounts:
                self._log("No accounts available to login", "Info")
                self.statusUpdated.emit("No accounts available to login")
                return []
            tasks = []
            successful_accounts = []
            total = len(accounts)
            for i, account in enumerate(accounts):
                fb_id = account[0]
                if login_mode == "AccessToken" and account[4]:
                    tasks.append(asyncio.create_task(self.login_with_access_token(fb_id, account[4])))
                elif login_mode == "Developer" and account[5]:
                    tasks.append(asyncio.create_task(self.login_developer(fb_id, account[1], account[2], account[5])))
                elif login_mode == "ExtractViaBrowser":
                    tasks.append(asyncio.create_task(self.extract_access_token_via_browser(fb_id, account[1], account[2])))
                else:
                    chrome_options = self._get_chrome_options(i, mobile_view, visible)
                    tasks.append(asyncio.create_task(self.login_account(fb_id, account[1], account[2], login_mode, preliminary_interaction, chrome_options)))
            results = await asyncio.gather(*tasks, return_exceptions=True)
            for i, result in enumerate(results):
                fb_id = accounts[i][0]
                if isinstance(result, Exception):
                    self._log(f"Login failed for {fb_id}: {str(result)}", "Error", fb_id)
                    self.statusUpdated.emit(f"Login failed for {fb_id}: {str(result)}")
                elif result:
                    successful_accounts.append(accounts[i])
                    self._log(f"Login succeeded for {fb_id}", "Info", fb_id)
                    self.statusUpdated.emit(f"Login succeeded for {fb_id}")
                self.progressUpdated.emit(i + 1, total)
            self._log(f"Login process completed for {len(accounts)} accounts", "Info")
            self.statusUpdated.emit(f"Login process completed for {len(accounts)} accounts")
            return successful_accounts
        except Exception as e:
            self._log(f"Failed to login all accounts: {str(e)}", "Error")
            self.statusUpdated.emit(f"Failed to login all accounts: {str(e)}")
            self.errorOccurred.emit(str(e))
            return []

    @retry(wait=wait_fixed(2), stop=stop_after_attempt(3))
    async def login_account(self, fb_id: str, encrypted_password: str, email: str, login_mode: str, preliminary_interaction: bool, chrome_options: Options, reauth: bool = False) -> bool:
        driver = None
        try:
            driver = self.session_manager.get_driver(fb_id, chrome_options=chrome_options, mobile=True, visible=True)
            if not driver:
                self._log(f"Failed to get driver for {fb_id}", "Error", fb_id)
                return False
            account = self.db.get_account(fb_id)
            if not account:
                self._log(f"Account {fb_id} not found", "Error", fb_id)
                self.statusUpdated.emit(f"Account {fb_id} not found")
                return False
            if not reauth and account[5] and account[5] != "":
                cookies = decrypt_data(account[5], self.config)
                load_cookies(driver, cookies, lambda msg: self.statusUpdated.emit(msg), secure=True)
                driver.get("https://www.facebook.com")
                await asyncio.wait_for(asyncio.sleep(random.uniform(2, 4)), timeout=5)
                if "login" not in driver.current_url:
                    self.db.update_account(fb_id, status="Logged In (Cookies)", last_login=datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
                    self._log(f"Logged in {fb_id} using cookies", "Info", fb_id)
                    self.statusUpdated.emit(f"Logged in {fb_id} using cookies")
                    if preliminary_interaction:
                        await simulate_human_behavior(driver, self.config, lambda msg: self.statusUpdated.emit(msg))
                    return True
            driver.get("https://www.facebook.com")
            await asyncio.wait_for(asyncio.sleep(random.uniform(1, 3)), timeout=5)
            email_field = WebDriverWait(driver, 10).until(EC.presence_of_element_located((By.ID, "email")))
            email_field.send_keys(email)
            password_field = WebDriverWait(driver, 10).until(EC.presence_of_element_located((By.ID, "pass")))
            password_field.send_keys(decrypt_data(encrypted_password, self.config))
            login_button = WebDriverWait(driver, 10).until(EC.element_to_be_clickable((By.NAME, "login")))
            login_button.click()
            await asyncio.wait_for(asyncio.sleep(random.uniform(3, 5)), timeout=10)
            if "checkpoint" in driver.current_url:
                success = await solve_captcha(driver, self.config.get("2captcha_api_key"), email, lambda msg: self.statusUpdated.emit(msg))
                if not success:
                    self.db.update_account(fb_id, status="CAPTCHA Failed")
                    self._log(f"CAPTCHA solving failed for {fb_id}", "Error", fb_id)
                    self.statusUpdated.emit(f"CAPTCHA solving failed for {fb_id}")
                    return False
                if "m_login_2fa" in driver.current_url:
                    self._log(f"2FA required for {fb_id}, not supported yet", "Error", fb_id)
                    self.statusUpdated.emit(f"2FA required for {fb_id}, not supported yet")
                    return False
            if predictive_ban_detection(driver, self.config, lambda msg: self.statusUpdated.emit(msg)):
                self.db.update_account(fb_id, status="Banned")
                self._log(f"Potential ban detected for {fb_id}", "Warning", fb_id)
                self.statusUpdated.emit(f"Potential ban detected for {fb_id}")
                return False
            if preliminary_interaction:
                await simulate_human_behavior(driver, self.config, lambda msg: self.statusUpdated.emit(msg))
            cookies = encrypt_data(orjson.dumps(driver.get_cookies()).decode(), self.config)
            self.db.update_account(fb_id, cookies=cookies, status="Logged In", last_login=datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
            self._log(f"Logged in successfully for {fb_id}", "Info", fb_id)
            self.statusUpdated.emit(f"Logged in successfully for {fb_id}")
            return True
        except Exception as e:
            self.db.update_account(fb_id, status=f"Login Failed: {type(e).__name__}")
            self._log(f"Login failed for {fb_id}: {str(e)}", "Error", fb_id)
            self.statusUpdated.emit(f"Login failed for {fb_id}: {str(e)}")
            self.errorOccurred.emit(str(e))
            QMessageBox.critical(None, "Login Error", f"Login failed for {fb_id}: {str(e)}")
            return False
        finally:
            if driver:
                self.session_manager.close_driver(fb_id)

    async def login_with_access_token(self, fb_id: str, access_token: str) -> bool:
        try:
            url = f"https://graph.facebook.com/v20.0/me?access_token={access_token}&fields=id,name"
            response = requests.get(url, timeout=10).json()
            if "error" in response:
                self.db.update_account(fb_id, status="Invalid Token")
                self._log(f"Invalid Access Token for {fb_id}: {response['error']['message']}", "Warning", fb_id)
                self.statusUpdated.emit(f"Invalid Access Token for {fb_id}")
                return False
            self.db.update_account(fb_id, access_token=access_token, status="Logged In (Token)", is_developer=1, last_login=datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
            self._log(f"Logged in with Access Token for {fb_id} (Developer)", "Info", fb_id)
            self.statusUpdated.emit(f"Logged in with Access Token for {fb_id} (Developer)")
            return True
        except Exception as e:
            self._log(f"Error with Access Token for {fb_id}: {str(e)}", "Error", fb_id)
            self.statusUpdated.emit(f"Error with Access Token for {fb_id}")
            self.errorOccurred.emit(str(e))
            QMessageBox.critical(None, "Token Error", f"Error with Access Token for {fb_id}: {str(e)}")
            return False

    async def login_developer(self, fb_id: str, encrypted_password: str, email: str, app_id: str) -> bool:
        driver = None
        try:
            chrome_options = self._get_chrome_options(0, mobile_view=True, visible=True)
            driver = self.session_manager.get_driver(fb_id, chrome_options=chrome_options)
            if not driver:
                self._log(f"Failed to get driver for {fb_id}", "Error", fb_id)
                return False
            driver.get("https://www.facebook.com")
            await asyncio.wait_for(asyncio.sleep(random.uniform(1, 3)), timeout=5)
            email_field = WebDriverWait(driver, 10).until(EC.presence_of_element_located((By.ID, "email")))
            email_field.send_keys(email)
            password_field = WebDriverWait(driver, 10).until(EC.presence_of_element_located((By.ID, "pass")))
            password_field.send_keys(decrypt_data(encrypted_password, self.config))
            login_button = WebDriverWait(driver, 10).until(EC.element_to_be_clickable((By.NAME, "login")))
            login_button.click()
            await asyncio.wait_for(asyncio.sleep(random.uniform(3, 5)), timeout=10)
            driver.get(f"https://www.facebook.com/v20.0/dialog/oauth?client_id={app_id}&redirect_uri=https://www.facebook.com/connect/login_success.html&response_type=token")
            await asyncio.wait_for(asyncio.sleep(5), timeout=10)
            if "access_token=" in driver.current_url:
                access_token = driver.current_url.split("access_token=")[1].split("&")[0]
                self.db.update_account(fb_id, access_token=access_token, status="Logged In (Developer)", is_developer=1, last_login=datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
                self._log(f"Logged in as Developer for {fb_id}", "Info", fb_id)
                self.statusUpdated.emit(f"Logged in as Developer for {fb_id}")
                return True
            self._log(f"Failed to extract Access Token for {fb_id}", "Error", fb_id)
            self.statusUpdated.emit(f"Failed to extract Access Token for {fb_id}")
            return False
        except Exception as e:
            self._log(f"Developer login failed for {fb_id}: {str(e)}", "Error", fb_id)
            self.statusUpdated.emit(f"Developer login failed for {fb_id}")
            self.errorOccurred.emit(str(e))
            QMessageBox.critical(None, "Developer Login Error", f"Developer login failed for {fb_id}: {str(e)}")
            return False
        finally:
            if driver:
                self.session_manager.close_driver(fb_id)

    async def extract_access_token_via_browser(self, fb_id: str, encrypted_password: str, email: str) -> bool:
        driver = None
        try:
            chrome_options = self._get_chrome_options(0, mobile_view=True, visible=True)
            driver = self.session_manager.get_driver(fb_id, chrome_options=chrome_options)
            if not driver:
                self._log(f"Failed to get driver for {fb_id}", "Error", fb_id)
                return False
            driver.get("https://www.facebook.com")
            await asyncio.wait_for(asyncio.sleep(random.uniform(1, 3)), timeout=5)
            email_field = WebDriverWait(driver, 10).until(EC.presence_of_element_located((By.ID, "email")))
            email_field.send_keys(email)
            password_field = WebDriverWait(driver, 10).until(EC.presence_of_element_located((By.ID, "pass")))
            password_field.send_keys(decrypt_data(encrypted_password, self.config))
            login_button = WebDriverWait(driver, 10).until(EC.element_to_be_clickable((By.NAME, "login")))
            login_button.click()
            await asyncio.wait_for(asyncio.sleep(random.uniform(3, 5)), timeout=10)
            access_token = await get_access_token(driver, self.config, lambda msg: self.statusUpdated.emit(msg))
            if access_token:
                self.db.update_account(fb_id, access_token=access_token, status="Logged In (Extracted)", is_developer=1, last_login=datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
                self._log(f"Access Token extracted for {fb_id}", "Info", fb_id)
                self.statusUpdated.emit(f"Access Token extracted for {fb_id}")
                return True
            self._log(f"Failed to extract Access Token for {fb_id}", "Error", fb_id)
            self.statusUpdated.emit(f"Failed to extract Access Token for {fb_id}")
            return False
        except Exception as e:
            self._log(f"Token extraction failed for {fb_id}: {str(e)}", "Error", fb_id)
            self.statusUpdated.emit(f"Token extraction failed for {fb_id}")
            self.errorOccurred.emit(str(e))
            QMessageBox.critical(None, "Token Extraction Error", f"Token extraction failed for {fb_id}: {str(e)}")
            return False
        finally:
            if driver:
                self.session_manager.close_driver(fb_id)

    async def unlock_account(self, fb_id: str, encrypted_password: str, email: str) -> bool:
        driver = None
        try:
            chrome_options = self._get_chrome_options(0, mobile_view=True, visible=True)
            driver = self.session_manager.get_driver(fb_id, chrome_options=chrome_options)
            if not driver:
                self._log(f"Failed to get driver for {fb_id}", "Error", fb_id)
                return False
            driver.get("https://www.facebook.com")
            await asyncio.wait_for(asyncio.sleep(random.uniform(1, 3)), timeout=5)
            email_field = WebDriverWait(driver, 10).until(EC.presence_of_element_located((By.ID, "email")))
            email_field.send_keys(email)
            password_field = WebDriverWait(driver, 10).until(EC.presence_of_element_located((By.ID, "pass")))
            password_field.send_keys(decrypt_data(encrypted_password, self.config))
            login_button = WebDriverWait(driver, 10).until(EC.element_to_be_clickable((By.NAME, "login")))
            login_button.click()
            await asyncio.wait_for(asyncio.sleep(random.uniform(3, 5)), timeout=10)
            if "checkpoint" in driver.current_url:
                success = await solve_captcha(driver, self.config.get("2captcha_api_key"), email, lambda msg: self.statusUpdated.emit(msg))
                if not success:
                    self.db.update_account(fb_id, status="CAPTCHA Failed")
                    self._log(f"CAPTCHA solving failed for {fb_id}", "Error", fb_id)
                    self.statusUpdated.emit(f"CAPTCHA solving failed for {fb_id}")
                    return False
                await asyncio.wait_for(asyncio.sleep(random.uniform(2, 4)), timeout=5)
            if "locked" in driver.current_url or "suspended" in driver.current_url:
                send_code = WebDriverWait(driver, 10).until(EC.element_to_be_clickable((By.XPATH, "//a[contains(text(), 'Send code via email')]")))
                send_code.click()
                await asyncio.wait_for(asyncio.sleep(random.uniform(5, 10)), timeout=15)
                self.db.update_account(fb_id, status="Unlocked", last_login=datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
                self._log(f"Unlocked {fb_id} successfully", "Info", fb_id)
                self.statusUpdated.emit(f"Unlocked {fb_id} successfully")
                return True
            self.db.update_account(fb_id, status="Logged In", last_login=datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
            self._log(f"Account {fb_id} logged in (no unlock needed)", "Info", fb_id)
            self.statusUpdated.emit(f"Account {fb_id} logged in (no unlock needed)")
            return True
        except Exception as e:
            self.db.update_account(fb_id, status="Unlock Failed")
            self._log(f"Unlock failed for {fb_id}: {str(e)}", "Error", fb_id)
            self.statusUpdated.emit(f"Unlock failed for {fb_id}: {str(e)}")
            self.errorOccurred.emit(str(e))
            QMessageBox.critical(None, "Unlock Error", f"Unlock failed for {fb_id}: {str(e)}")
            return False
        finally:
            if driver:
                self.session_manager.close_driver(fb_id)

    async def verify_login_status(self, fb_id: str) -> bool:
        driver = None
        try:
            account = self.db.get_account(fb_id)
            if not account:
                self._log(f"Account {fb_id} not found", "Warning", fb_id)
                self.statusUpdated.emit(f"Account {fb_id} not found")
                return False
            chrome_options = self._get_chrome_options(0, mobile_view=True, visible=False)
            driver = self.session_manager.get_driver(fb_id, chrome_options=chrome_options)
            if not driver:
                self._log(f"Failed to get driver for {fb_id}", "Error", fb_id)
                return False
            cookies = decrypt_data(account[5], self.config) if account[5] else None
            if cookies:
                load_cookies(driver, cookies, lambda msg: self.statusUpdated.emit(msg), secure=True)
            driver.get("https://www.facebook.com")
            await asyncio.wait_for(asyncio.sleep(random.uniform(2, 4)), timeout=5)
            if predictive_ban_detection(driver, self.config, lambda msg: self.statusUpdated.emit(msg)):
                self.db.update_account(fb_id, status="Banned")
                self._log(f"Account {fb_id} is banned", "Warning", fb_id)
                self.statusUpdated.emit(f"Account {fb_id} is banned")
                return False
            elif "login" not in driver.current_url:
                self.db.update_account(fb_id, status="Logged In", last_login=datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
                self._log(f"Account {fb_id} is logged in", "Info", fb_id)
                self.statusUpdated.emit(f"Account {fb_id} is logged in")
                return True
            self.db.update_account(fb_id, status="Not Logged In")
            self._log(f"Account {fb_id} is not logged in", "Info", fb_id)
            self.statusUpdated.emit(f"Account {fb_id} is not logged in")
            return False
        except Exception as e:
            self._log(f"Error verifying login for {fb_id}: {str(e)}", "Error", fb_id)
            self.statusUpdated.emit(f"Error verifying login for {fb_id}")
            self.errorOccurred.emit(str(e))
            QMessageBox.critical(None, "Verification Error", f"Error verifying login for {fb_id}: {str(e)}")
            return False
        finally:
            if driver:
                self.session_manager.close_driver(fb_id)

    def close_all_browsers(self) -> None:
        try:
            self.session_manager.close_all_drivers()
            self._log("All browsers closed successfully", "Info")
            self.statusUpdated.emit("All browsers closed successfully")
        except Exception as e:
            self._log(f"Error closing browsers: {str(e)}", "Error")
            self.statusUpdated.emit(f"Error closing browsers: {str(e)}")
            self.errorOccurred.emit(str(e))
            QMessageBox.critical(None, "Close Error", f"Error closing browsers: {str(e)}")

    def cleanup_inactive_accounts(self) -> None:
        try:
            accounts = self.db.get_accounts()
            for account in accounts:
                fb_id, last_login = account[0], account[7]
                if last_login and (datetime.now() - datetime.strptime(last_login, "%Y-%m-%d %H:%M:%S")).days > 30:
                    self.db.delete_account(fb_id)
                    self._log(f"Deleted inactive account {fb_id}", "Info", fb_id)
                    self.statusUpdated.emit(f"Deleted inactive account {fb_id}")
        except Exception as e:
            self._log(f"Error cleaning inactive accounts: {str(e)}", "Error")
            self.statusUpdated.emit(f"Error cleaning inactive accounts: {str(e)}")
            self.errorOccurred.emit(str(e))

if __name__ == "__main__":
    from PyQt5.QtWidgets import QApplication
    import sys
    app = QApplication.instance() or QApplication(sys.argv)
    class DummyApp:
        class DummyUI:
            def show_message(self, title, message, icon):
                print(f"[{title}] {message}")
        ui = DummyUI()
        log_manager = None
        def rotate_proxy(self, session_id):
            return "http://proxy1:port"
    class DummyConfig:
        def get(self, key, default=None):
            defaults = {
                "max_retries": 3,
                "default_delay": 5,
                "mobile_size": "360x640",
                "chrome_path": "drivers/chrome.exe",
                "chromedriver_path": "drivers/chromedriver.exe",
                "2captcha_api_key": "test_key",
                "custom_scripts": ["Test script"],
                "proxies": ["http://proxy1:port"]
            }
            return defaults.get(key, default)
    class DummyDatabase:
        def __init__(self):
            self.accounts = []
            self.conn = self
        def get_accounts(self):
            return self.accounts
        def get_account(self, fb_id):
            return next((acc for acc in self.accounts if acc[0] == fb_id), None)
        def add_account(self, fb_id, password, email, proxy=None, access_token=None, is_developer=0):
            self.accounts.append((fb_id, password, email, proxy, access_token, None, "Not Logged In", None, is_developer, 0))
        def update_account(self, fb_id, **kwargs):
            for i, acc in enumerate(self.accounts):
                if acc[0] == fb_id:
                    self.accounts[i] = tuple(kwargs.get(k, v) for k, v in zip(["fb_id", "password", "email", "proxy", "access_token", "cookies", "status", "last_login", "is_developer", "is_active"], acc))
        def delete_account(self, fb_id):
            self.accounts = [acc for acc in self.accounts if acc[0] != fb_id]
        def executemany(self, query, params):
            pass
    class DummyLogManager:
    def add_log(self, fb_id, target, action, level, message):
        try:
            with open("log.txt", "a", encoding="utf-8") as log_file:
                log_file.write(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}][{level}][{fb_id}][{action}]: {message}\n")
            if os.path.getsize("log.txt") > 1024 * 1024:  # 1MB
                os.rename("log.txt", f"log_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt")
                open("log.txt", "w", encoding="utf-8").close()
        except Exception as e:
            print(f"Failed to write log: {str(e)}\n{traceback.format_exc()}")

dummy_app = DummyApp()
dummy_app.log_manager = DummyLogManager()
account_manager = AccountManager(dummy_app, DummyConfig(), DummyDatabase(), dummy_app.log_manager)
accounts_text = "fb1|password1|email1@example.com"
try:
    account_manager.add_accounts(accounts_text)
    asyncio.run(account_manager.login_all_accounts())
    account_manager.cleanup_inactive_accounts()
except Exception as e:
    print(f"Error in main execution: {str(e)}\n{traceback.format_exc()}")
sys.exit(app.exec_())