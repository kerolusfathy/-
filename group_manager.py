import asyncio
import random
import os
import requests
import hashlib
import traceback
import ssl
import certifi
from typing import List, Optional, Tuple
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException
from selenium.webdriver.chrome.options import Options
from PyQt5.QtWidgets import QApplication, QMessageBox
from PyQt5.QtCore import pyqtSignal, QObject, Qt, QMetaObject, Q_ARG
from pathlib import Path
import logging
import logging.handlers
from threading import Lock
import orjson
from datetime import datetime
from utils import SessionManager, load_cookies, decrypt_data, predictive_ban_detection, spin_content

class GroupManager(QObject):
    """Class to manage Facebook group operations including extraction, invitations, and interactions.
    Integrates with Chrome in 'drivers' and supports Selenium and Graph API."""
    
    statusUpdated = pyqtSignal(str)  # Signal to update status
    progressUpdated = pyqtSignal(int, int)  # Signal for progress bar updates

    def __init__(self, app, db, session_manager, config, log_manager):
        """Initialize GroupManager with dependencies."""
        super().__init__()
        self.app = app
        self.db = db
        self.session_manager = session_manager
        self.config = config
        self.log_manager = log_manager
        self.lock = Lock()  # For thread-safe operations
        self.base_dir = Path(os.path.dirname(os.path.abspath(__file__)))
        self.rate_limit_delay = 5  # Seconds to delay between API calls

        if not self.log_manager:
            raise ValueError("LogManager is required")

        self.setup_logging()
        self._log("GroupManager initialized successfully", "INFO")

    def setup_logging(self):
        """Setup logging with rotation to manage log file size."""
        logging.basicConfig(
            filename=self.base_dir / "group_manager.log",
            level=logging.INFO,
            format="%(asctime)s - %(levelname)s - %(message)s",
            handlers=[logging.handlers.RotatingFileHandler(
                self.base_dir / "group_manager.log",
                maxBytes=10*1024*1024,  # 10 MB
                backupCount=5
            )]
        )
        self.logger = logging.getLogger(__name__)

    def _log(self, message: str, level: str, account_id: str = "System", action: str = "Groups") -> None:
        """Log messages with timestamp and traceback via log_manager."""
        try:
            timestamp = datetime.now().isoformat()
            full_message = f"{timestamp} | {message}"
            self.log_manager.add_log(account_id, None, action, level, full_message)
            self.logger.log(getattr(logging, level.upper()), full_message)
            self.statusUpdated.emit(f"{level}: {message}")
        except Exception as e:
            print(f"Error logging in GroupManager: {str(e)}\n{traceback.format_exc()}")

    def _sanitize_input(self, value: Any) -> str:
        """Sanitize input to prevent injection or malformed data."""
        if value is None:
            return ""
        return str(value).replace("'", "''").replace(";", "")

    def _get_chrome_options(self, index: int, mobile_size: bool = True, visible: bool = True) -> Options:
        """Configure Chrome options with specified window size but desktop behavior."""
        try:
            chrome_options = Options()
            chrome_options.add_argument("--disable-notifications")
            # Set window size to mobile-like dimensions but keep desktop behavior
            if mobile_size:
                chrome_options.add_argument(f"--window-size={self.config.get('mobile_size', '360x640').replace('x', ',')}")
            # Force desktop User-Agent to ensure desktop version of websites
            chrome_options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36")
            if not visible:
                chrome_options.add_argument("--headless")
            chrome_options.add_argument("--disable-gpu")
            chrome_options.add_argument("--no-sandbox")
            chrome_options.add_argument(f"--window-position={index * 400 % 1600},{index * 400 // 1600}")
            chrome_path = self.base_dir / self.config.get("chrome_path", "drivers/chrome.exe")
            if not chrome_path.exists():
                raise FileNotFoundError(f"Chrome not found at {chrome_path}")
            chrome_options.binary_location = str(chrome_path)
            if self.config.get("proxy_rotation_enabled", True) and self.config.get("proxies"):
                proxy = self.session_manager.rotate_proxy(f"Session-{index}")
                if proxy:
                    chrome_options.add_argument(f"--proxy-server={proxy}")
                    self._log(f"Using proxy {proxy} for session {index}", "INFO")
            return chrome_options
        except Exception as e:
            self._log(f"Error setting Chrome options: {str(e)}\n{traceback.format_exc()}", "ERROR")
            self.statusUpdated.emit(f"Error setting Chrome options: {str(e)}")
            return Options()

    def setup_driver(self, account_id: str, account_data: Tuple) -> Optional[webdriver.Chrome]:
        """Setup a browser instance with cookies and ban detection."""
        try:
            chrome_options = self._get_chrome_options(0, mobile_size=True, visible=True)
            driver = self.session_manager.get_driver(account_id, chrome_options=chrome_options)
            if account_data[5]:  # Cookies
                cookies = decrypt_data(account_data[5], self.config)
                load_cookies(driver, cookies, lambda msg: self.statusUpdated.emit(msg))
            driver.get("https://www.facebook.com")
            asyncio.run_coroutine_threadsafe(asyncio.sleep(random.uniform(2, 4)), asyncio.get_running_loop()).result()
            if predictive_ban_detection(driver, self.config, lambda msg: self.statusUpdated.emit(msg)):
                self.db.update_account(account_id, status="Banned")
                self._log("Potential ban detected", "WARNING", account_id)
                self.session_manager.close_driver(account_id)
                return None
            return driver
        except Exception as e:
            self._log(f"Error setting up driver for {account_id}: {str(e)}\n{traceback.format_exc()}", "ERROR", account_id)
            return None

    async def extract_all_groups(self, keywords: str = "", fast_mode: bool = False, interact: bool = False, 
                                 min_members: int = 0, max_members: Optional[int] = None) -> None:
        """Extract all groups with progress tracking and confirmation."""
        start_time = datetime.now()
        try:
            accounts = self.db.get_accounts()
            if not accounts:
                self._log("No accounts available for extraction", "WARNING")
                self.statusUpdated.emit("No accounts available")
                return

            total = len(accounts)
            tasks = []
            loop = asyncio.get_running_loop()
            for i, acc in enumerate(accounts):
                task = asyncio.create_task(self.extract_groups(
                    acc[0], acc[5], acc[4], keywords, fast_mode, interact, min_members, max_members
                ))
                tasks.append(task)
                self.progressUpdated.emit(i + 1, total)

            results = await asyncio.gather(*tasks, return_exceptions=True)
            extracted_count = 0
            for i, result in enumerate(results):
                if isinstance(result, Exception):
                    self._log(f"Error extracting groups for account {accounts[i][0]}: {str(result)}\n{traceback.format_exc()}", "ERROR", accounts[i][0])
                else:
                    extracted_count += result.get("count", 0)

            execution_time = (datetime.now() - start_time).total_seconds()
            self._log(f"Extracted {extracted_count} groups in {execution_time:.2f} seconds", "INFO")
            self.statusUpdated.emit("All groups extracted successfully")
            if QApplication.instance():
                QMetaObject.invokeMethod(
                    self.app.ui if hasattr(self.app, 'ui') else None,
                    "show_message", Qt.QueuedConnection,
                    Q_ARG(str, "Success"), Q_ARG(str, "All groups extracted"), Q_ARG(str, "Information")
                )
        except Exception as e:
            self._log(f"Error extracting all groups: {str(e)}\n{traceback.format_exc()}", "ERROR")
            self.statusUpdated.emit(f"Error: {str(e)}")

    async def extract_joined_groups(self, account_id: Optional[str] = None) -> None:
        """Extract joined groups automatically and close browsers."""
        start_time = datetime.now()
        try:
            accounts = self.db.get_accounts() if not account_id else [acc for acc in self.db.get_accounts() if acc[0] == account_id]
            if not accounts:
                self._log("No accounts available for joined group extraction", "WARNING")
                self.statusUpdated.emit("No accounts available")
                return

            total = len(accounts)
            tasks = []
            loop = asyncio.get_running_loop()
            for i, acc in enumerate(accounts):
                task = asyncio.create_task(self.extract_groups(
                    acc[0], acc[5], acc[4], "", fast_mode=True, interact=False
                ))
                tasks.append(task)
                self.progressUpdated.emit(i + 1, total)

            results = await asyncio.gather(*tasks, return_exceptions=True)
            extracted_count = 0
            for i, result in enumerate(results):
                if isinstance(result, Exception):
                    self._log(f"Error extracting joined groups for account {accounts[i][0]}: {str(result)}\n{traceback.format_exc()}", "ERROR", accounts[i][0])
                else:
                    extracted_count += result.get("count", 0)

            self.session_manager.close_all_drivers()
            execution_time = (datetime.now() - start_time).total_seconds()
            self._log(f"Extracted {extracted_count} joined groups in {execution_time:.2f} seconds", "INFO")
            self.statusUpdated.emit("Joined groups extracted and saved")
            if QApplication.instance():
                QMetaObject.invokeMethod(
                    self.app.ui if hasattr(self.app, 'ui') else None,
                    "show_message", Qt.QueuedConnection,
                    Q_ARG(str, "Success"), Q_ARG(str, "Joined groups extracted and saved"), Q_ARG(str, "Information")
                )
        except Exception as e:
            self._log(f"Error extracting joined groups: {str(e)}\n{traceback.format_exc()}", "ERROR")
            self.statusUpdated.emit(f"Error: {str(e)}")

    async def extract_groups(self, account_id: str, cookies: Optional[str], access_token: Optional[str], 
                             keywords: str = "", fast_mode: bool = False, interact: bool = False, 
                             min_members: int = 0, max_members: Optional[int] = None) -> Dict[str, int]:
        """Extract groups using Selenium or Graph API."""
        driver = None
        group_count = 0
        try:
            account = self.db.get_account(account_id)
            if not account:
                self._log(f"Account {account_id} not found", "WARNING", account_id)
                self.statusUpdated.emit(f"Account {account_id} not found")
                return {"count": 0}

            driver = self.setup_driver(account_id, account) if not fast_mode or not access_token else None
            if not driver and not fast_mode:
                return {"count": 0}

            if keywords:  # Search by keywords using Selenium
                driver.get(f"https://www.facebook.com/search/groups/?q={keywords}")
                try:
                    WebDriverWait(driver, 10).until(EC.presence_of_element_located((By.XPATH, "//a[contains(@href, '/groups/')]")))
                except TimeoutException:
                    self._log(f"Timeout loading groups for keywords {keywords}", "ERROR", account_id)
                    return {"count": 0}
                for _ in range(5):
                    driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
                    await asyncio.sleep(random.uniform(1, 3))
                groups = driver.find_elements(By.XPATH, "//a[contains(@href, '/groups/')]")
                for group in groups:
                    group_url = group.get_attribute("href")
                    group_id = self._sanitize_input(group_url.split("/groups/")[1].split("/")[0])
                    group_name = self._sanitize_input(group.text or "Unnamed")
                    if not group_id or not group_name:
                        continue
                    member_count = self._get_member_count(driver, group_id)
                    if min_members and member_count < min_members:
                        continue
                    if max_members and member_count > max_members:
                        continue
                    self.db.add_group(account_id, group_id, group_name, 0, member_count=member_count)
                    self._log(f"Extracted group: {group_name} ({group_id})", "INFO", account_id, group_id)
                    group_count += 1

            elif fast_mode and access_token:  # Graph API
                loop = asyncio.get_running_loop()
                url = f"https://graph.facebook.com/v20.0/me/groups?access_token={hashlib.sha256(self._sanitize_input(access_token).encode()).hexdigest()}&fields=id,name,privacy,created_time,description,administrator,member_count"
                for attempt in range(3):  # Auto-retry mechanism
                    try:
                        response = await loop.run_in_executor(None, lambda: requests.get(
                            url, timeout=10, verify=certifi.where()
                        ))
                        data = orjson.loads(response.text)
                        if "data" in data:
                            for group in data["data"]:
                                group_id = self._sanitize_input(group.get("id", ""))
                                group_name = self._sanitize_input(group.get("name", "Unnamed"))
                                if not group_id or not group_name:
                                    continue
                                member_count = group.get("member_count", 0)
                                if min_members and member_count < min_members:
                                    continue
                                if max_members and member_count > max_members:
                                    continue
                                self.db.add_group(
                                    account_id, group_id, group_name, 1 if group["privacy"] == "CLOSED" else 0,
                                    group.get("created_time", ""), group.get("description", ""),
                                    "true" if group.get("administrator", False) else "false", member_count=member_count
                                )
                                self._log(f"Extracted group: {group_name} ({group_id})", "INFO", account_id, group_id)
                                group_count += 1
                            break
                        elif "error" in data:
                            self._log(f"Graph API error: {data['error'].get('message', 'Unknown error')} (Status: {response.status_code})", "ERROR", account_id)
                            if data["error"].get("code") == 190:  # Token expired/invalid
                                self.db.update_account(account_id, status="Not Logged In")
                                break
                            await asyncio.sleep(self.rate_limit_delay)  # Rate limit handling
                    except requests.RequestException as e:
                        self._log(f"Request error on attempt {attempt + 1}: {str(e)}\n{traceback.format_exc()}", "ERROR", account_id)
                        if attempt == 2:
                            break
                        await asyncio.sleep(self.rate_limit_delay)
                    except KeyError as e:
                        self._log(f"KeyError parsing Graph API response: {str(e)}\n{traceback.format_exc()}", "ERROR", account_id)
                        break

            else:  # Joined groups using Selenium
                driver.get("https://www.facebook.com/groups/feed/")
                try:
                    WebDriverWait(driver, 10).until(EC.presence_of_element_located((By.XPATH, "//a[contains(@href, '/groups/')]")))
                except TimeoutException:
                    self._log("Timeout loading joined groups feed", "ERROR", account_id)
                    return {"count": 0}
                for _ in range(5):
                    driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
                    await asyncio.sleep(random.uniform(1, 3))
                groups = driver.find_elements(By.XPATH, "//a[contains(@href, '/groups/')]")
                for group in groups:
                    group_url = group.get_attribute("href")
                    group_id = self._sanitize_input(group_url.split("/groups/")[1].split("/")[0])
                    group_name = self._sanitize_input(group.text or "Unnamed")
                    if not group_id or not group_name:
                        continue
                    member_count = self._get_member_count(driver, group_id)
                    if min_members and member_count < min_members:
                        continue
                    if max_members and member_count > max_members:
                        continue
                    self.db.add_group(account_id, group_id, group_name, 0, member_count=member_count)
                    self._log(f"Extracted group: {group_name} ({group_id})", "INFO", account_id, group_id)
                    group_count += 1

            if interact and self.config.get("custom_scripts"):
                groups = self.db.get_groups(account_id)
                for group in groups[:5]:  # Limit to avoid bans
                    group_id = group[2]
                    driver.get(f"https://www.facebook.com/groups/{group_id}")
                    await asyncio.sleep(random.uniform(2, 4))
                    try:
                        like_buttons = WebDriverWait(driver, 5).until(
                            EC.presence_of_all_elements_located((By.XPATH, "//button[contains(@aria-label, 'Like')]"))
                        )
                        if like_buttons:
                            like_buttons[0].click()
                            self._log("Liked a post", "INFO", account_id, group_id)
                    except (TimeoutException, NoSuchElementException):
                        pass
                    try:
                        comment_boxes = WebDriverWait(driver, 5).until(
                            EC.presence_of_all_elements_located((By.XPATH, "//div[@role='textbox']"))
                        )
                        if comment_boxes and self.config.get("custom_scripts"):
                            comment = random.choice(self.config["custom_scripts"])
                            comment_boxes[0].send_keys(comment)
                            await asyncio.sleep(random.uniform(1, 2))
                            submit_button = driver.find_element(By.XPATH, "//button[@type='submit']")
                            submit_button.click()
                            self._log(f"Commented: {comment}", "INFO", account_id, group_id)
                    except (TimeoutException, NoSuchElementException):
                        pass

            self._log(f"Extracted {group_count} groups for {account_id}", "INFO", account_id)
            self.statusUpdated.emit(f"Extracted {group_count} groups for {account_id}")
            return {"count": group_count}

        except Exception as e:
            self._log(f"Error extracting groups for {account_id}: {str(e)}\n{traceback.format_exc()}", "ERROR", account_id)
            self.statusUpdated.emit(f"Error: {str(e)}")
            return {"count": 0}
        finally:
            if driver:
                self.session_manager.close_driver(account_id)

    def _get_member_count(self, driver: webdriver.Chrome, group_id: str) -> int:
        """Extract member count from a group page."""
        try:
            driver.get(f"https://www.facebook.com/groups/{group_id}")
            WebDriverWait(driver, 5).until(EC.presence_of_element_located((By.XPATH, "//span[contains(text(), 'members')]")))
            member_text = driver.find_element(By.XPATH, "//span[contains(text(), 'members')]").text
            return int(''.join(filter(str.isdigit, member_text)))
        except (TimeoutException, NoSuchElementException):
            return 0
        except Exception as e:
            self._log(f"Error getting member count for {group_id}: {str(e)}\n{traceback.format_exc()}", "ERROR")
            return 0

    async def add_members_to_group(self, group_id: str, member_ids: str) -> None:
        """Send invitations to members using Graph API or Selenium."""
        start_time = datetime.now()
        try:
            accounts = self.db.get_accounts()
            if not accounts:
                self._log("No accounts available for adding members", "WARNING")
                self.statusUpdated.emit("No accounts available")
                return

            total = len(accounts)
            tasks = []
            loop = asyncio.get_running_loop()
            for i, acc in enumerate(accounts):
                if acc[9]:  # is_developer
                    task = asyncio.create_task(self._add_members_graph_api(acc[0], acc[4], group_id, member_ids))
                else:
                    driver = self.setup_driver(acc[0], acc)
                    if driver:
                        task = asyncio.create_task(self._add_members_to_group_task(driver, acc[0], group_id, member_ids))
                    else:
                        continue
                tasks.append(task)
                self.progressUpdated.emit(i + 1, total)

            results = await asyncio.gather(*tasks, return_exceptions=True)
            for i, result in enumerate(results):
                if isinstance(result, Exception):
                    self._log(f"Error adding members for account {accounts[i][0]}: {str(result)}\n{traceback.format_exc()}", "ERROR", accounts[i][0])

            execution_time = (datetime.now() - start_time).total_seconds()
            self._log(f"Sent invites to members in {group_id} in {execution_time:.2f} seconds", "INFO")
            self.statusUpdated.emit(f"Sent invites to members in {group_id}")
            if QApplication.instance():
                QMetaObject.invokeMethod(
                    self.app.ui if hasattr(self.app, 'ui') else None,
                    "show_message", Qt.QueuedConnection,
                    Q_ARG(str, "Success"), Q_ARG(str, f"Invites sent to members in {group_id}"), Q_ARG(str, "Information")
                )
        except Exception as e:
            self._log(f"Error adding members to {group_id}: {str(e)}\n{traceback.format_exc()}", "ERROR")
            self.statusUpdated.emit(f"Error: {str(e)}")

    async def _add_members_graph_api(self, account_id: str, access_token: str, group_id: str, member_ids: str) -> None:
        """Send invitations via Graph API for developer accounts."""
        try:
            member_list = [self._sanitize_input(mid.strip()) for mid in member_ids.strip().splitlines() if mid.strip()]
            url = f"https://graph.facebook.com/v20.0/{self._sanitize_input(group_id)}/members"
            loop = asyncio.get_running_loop()
            encrypted_token = hashlib.sha256(self._sanitize_input(access_token).encode()).hexdigest()
            for member_id in member_list[:10]:  # Limit to avoid bans
                payload = {"user_id": member_id, "access_token": encrypted_token}
                for attempt in range(3):  # Auto-retry
                    try:
                        response = await loop.run_in_executor(None, lambda: requests.post(
                            url, data=payload, timeout=10, verify=certifi.where()
                        ))
                        data = orjson.loads(response.text)
                        if "error" in data:
                            self._log(f"Failed to invite {member_id}: {data['error'].get('message', 'Unknown')} (Status: {response.status_code})", "ERROR", account_id, group_id)
                            if data["error"].get("code") in (368, 10):  # Rate limit or ban
                                await asyncio.sleep(self.rate_limit_delay)
                        else:
                            self._log(f"Invited {member_id}", "INFO", account_id, group_id)
                        break
                    except requests.RequestException as e:
                        self._log(f"Request error on attempt {attempt + 1}: {str(e)}\n{traceback.format_exc()}", "ERROR", account_id, group_id)
                        if attempt == 2:
                            break
                        await asyncio.sleep(self.rate_limit_delay)
                await asyncio.sleep(random.uniform(2, 5))
        except Exception as e:
            self._log(f"Graph API error adding members: {str(e)}\n{traceback.format_exc()}", "ERROR", account_id, group_id)

    async def _add_members_to_group_task(self, driver: webdriver.Chrome, account_id: str, group_id: str, member_ids: str) -> None:
        """Task to send invitations using Selenium."""
        try:
            member_list = [self._sanitize_input(mid.strip()) for mid in member_ids.strip().splitlines() if mid.strip()]
            for member_id in member_list[:10]:  # Limit to avoid bans
                driver.get(f"https://www.facebook.com/groups/{self._sanitize_input(group_id)}")
                await asyncio.sleep(random.uniform(1, 3))
                try:
                    invite_field = WebDriverWait(driver, 10).until(
                        EC.presence_of_element_located((By.XPATH, "//input[@placeholder='Enter name or email address']"))
                    )
                    invite_field.send_keys(member_id)
                    await asyncio.sleep(random.uniform(1, 2))
                    invite_button = driver.find_element(By.XPATH, "//div[@aria-label='Invite']")
                    invite_button.click()
                    self._log(f"Invited {member_id}", "INFO", account_id, group_id)
                except (TimeoutException, NoSuchElementException) as e:
                    self._log(f"Failed to locate invite elements: {str(e)}\n{traceback.format_exc()}", "ERROR", account_id, group_id)
                await asyncio.sleep(random.uniform(2, 5))
                if "checkpoint" in driver.current_url.lower():  # Captcha detection
                    self._log(f"Captcha detected while inviting {member_id}", "WARNING", account_id, group_id)
                    self.db.update_account(account_id, status="Banned")
                    break
        except Exception as e:
            self._log(f"Failed to invite members: {str(e)}\n{traceback.format_exc()}", "ERROR", account_id, group_id)
        finally:
            self.session_manager.close_driver(account_id)

    async def extract_group_members(self, group_id: str) -> List[str]:
        """Extract member IDs from a specific group."""
        start_time = datetime.now()
        try:
            accounts = self.db.get_accounts()
            if not accounts:
                self._log("No accounts available for member extraction", "WARNING")
                self.statusUpdated.emit("No accounts available")
                return []

            total = len(accounts)
            all_member_ids = []
            tasks = []
            loop = asyncio.get_running_loop()
            for i, acc in enumerate(accounts):
                driver = self.setup_driver(acc[0], acc)
                if driver:
                    task = asyncio.create_task(self._extract_group_members_task(driver, acc[0], group_id, all_member_ids))
                    tasks.append(task)
                self.progressUpdated.emit(i + 1, total)

            results = await asyncio.gather(*tasks, return_exceptions=True)
            for i, result in enumerate(results):
                if isinstance(result, Exception):
                    self._log(f"Error extracting members for account {accounts[i][0]}: {str(result)}\n{traceback.format_exc()}", "ERROR", accounts[i][0])

            unique_members = list(set(all_member_ids))
            execution_time = (datetime.now() - start_time).total_seconds()
            self._log(f"Extracted {len(unique_members)} members from {group_id} in {execution_time:.2f} seconds", "INFO")
            self.statusUpdated.emit(f"Extracted {len(unique_members)} members from {group_id}")
            return unique_members
        except Exception as e:
            self._log(f"Error extracting members from {group_id}: {str(e)}\n{traceback.format_exc()}", "ERROR")
            self.statusUpdated.emit(f"Error: {str(e)}")
            return []

    async def _extract_group_members_task(self, driver: webdriver.Chrome, account_id: str, group_id: str, all_member_ids: List[str]) -> None:
        """Task to extract group members."""
        try:
            driver.get(f"https://www.facebook.com/groups/{self._sanitize_input(group_id)}/members")
            WebDriverWait(driver, 10).until(EC.presence_of_element_located((By.XPATH, "//a[contains(@href, '/profile.php')]")))
            for _ in range(5):
                driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
                await asyncio.sleep(random.uniform(1, 3))
            members = driver.find_elements(By.XPATH, "//a[contains(@href, '/profile.php')]")
            member_ids = [
                self._sanitize_input(m.get_attribute("href").split("id=")[1].split('&')[0])
                for m in members if "id=" in m.get_attribute("href")
            ]
            all_member_ids.extend(member_ids)
            for member_id in member_ids:
                self._log(f"Extracted member {member_id}", "INFO", account_id, group_id)
        except (TimeoutException, NoSuchElementException) as e:
            self._log(f"Error locating members: {str(e)}\n{traceback.format_exc()}", "ERROR", account_id, group_id)
        except Exception as e:
            self._log(f"Error extracting members: {str(e)}\n{traceback.format_exc()}", "ERROR", account_id, group_id)
        finally:
            self.session_manager.close_driver(account_id)

    async def auto_approve_requests(self, group_id: str) -> None:
        """Automatically approve membership requests."""
        start_time = datetime.now()
        try:
            accounts = self.db.get_accounts()
            if not accounts:
                self._log("No accounts available for approving requests", "WARNING")
                self.statusUpdated.emit("No accounts available")
                return

            total = len(accounts)
            tasks = []
            loop = asyncio.get_running_loop()
            for i, acc in enumerate(accounts):
                driver = self.setup_driver(acc[0], acc)
                if driver:
                    task = asyncio.create_task(self._auto_approve_requests_task(driver, acc[0], group_id))
                    tasks.append(task)
                self.progressUpdated.emit(i + 1, total)

            results = await asyncio.gather(*tasks, return_exceptions=True)
            for i, result in enumerate(results):
                if isinstance(result, Exception):
                    self._log(f"Error approving requests for account {accounts[i][0]}: {str(result)}\n{traceback.format_exc()}", "ERROR", accounts[i][0])

            execution_time = (datetime.now() - start_time).total_seconds()
            self._log(f"Approved membership requests in {group_id} in {execution_time:.2f} seconds", "INFO")
            self.statusUpdated.emit(f"Approved membership requests in {group_id}")
            if QApplication.instance():
                QMetaObject.invokeMethod(
                    self.app.ui if hasattr(self.app, 'ui') else None,
                    "show_message", Qt.QueuedConnection,
                    Q_ARG(str, "Success"), Q_ARG(str, f"Approved membership requests in {group_id}"), Q_ARG(str, "Information")
                )
        except Exception as e:
            self._log(f"Error approving requests in {group_id}: {str(e)}\n{traceback.format_exc()}", "ERROR")
            self.statusUpdated.emit(f"Error: {str(e)}")

    async def _auto_approve_requests_task(self, driver: webdriver.Chrome, account_id: str, group_id: str) -> None:
        """Task to auto-approve membership requests."""
        try:
            driver.get(f"https://www.facebook.com/groups/{self._sanitize_input(group_id)}/requests")
            await asyncio.sleep(random.uniform(1, 3))
            approve_buttons = WebDriverWait(driver, 10).until(
                EC.presence_of_all_elements_located((By.XPATH, "//div[@aria-label='Approve']"))
            )
            approved_count = 0
            for button in approve_buttons[:10]:  # Limit to avoid bans
                button.click()
                approved_count += 1
                await asyncio.sleep(random.uniform(1, 2))
            self._log(f"Approved {approved_count} requests", "INFO", account_id, group_id)
        except (TimeoutException, NoSuchElementException) as e:
            self._log(f"Failed to locate approve buttons: {str(e)}\n{traceback.format_exc()}", "ERROR", account_id, group_id)
        except Exception as e:
            self._log(f"Failed to approve requests: {str(e)}\n{traceback.format_exc()}", "ERROR", account_id, group_id)
        finally:
            self.session_manager.close_driver(account_id)

    async def delete_posts(self, group_id: str, criteria: str = "no_interaction") -> None:
        """Delete posts based on specific criteria."""
        start_time = datetime.now()
        try:
            accounts = self.db.get_accounts()
            if not accounts:
                self._log("No accounts available for deleting posts", "WARNING")
                self.statusUpdated.emit("No accounts available")
                return

            total = len(accounts)
            tasks = []
            loop = asyncio.get_running_loop()
            for i, acc in enumerate(accounts):
                driver = self.setup_driver(acc[0], acc)
                if driver:
                    task = asyncio.create_task(self._delete_posts_task(driver, acc[0], group_id, criteria))
                    tasks.append(task)
                self.progressUpdated.emit(i + 1, total)

            results = await asyncio.gather(*tasks, return_exceptions=True)
            for i, result in enumerate(results):
                if isinstance(result, Exception):
                    self._log(f"Error deleting posts for account {accounts[i][0]}: {str(result)}\n{traceback.format_exc()}", "ERROR", accounts[i][0])

            execution_time = (datetime.now() - start_time).total_seconds()
            self._log(f"Deleted posts in {group_id} in {execution_time:.2f} seconds", "INFO")
            self.statusUpdated.emit(f"Deleted posts in {group_id}")
            if QApplication.instance():
                QMetaObject.invokeMethod(
                    self.app.ui if hasattr(self.app, 'ui') else None,
                    "show_message", Qt.QueuedConnection,
                    Q_ARG(str, "Success"), Q_ARG(str, f"Deleted posts in {group_id}"), Q_ARG(str, "Information")
                )
        except Exception as e:
            self._log(f"Error deleting posts in {group_id}: {str(e)}\n{traceback.format_exc()}", "ERROR")
            self.statusUpdated.emit(f"Error: {str(e)}")

    async def _delete_posts_task(self, driver: webdriver.Chrome, account_id: str, group_id: str, criteria: str) -> None:
        """Task to delete posts based on criteria."""
        try:
            driver.get(f"https://www.facebook.com/groups/{self._sanitize_input(group_id)}")
            await asyncio.sleep(random.uniform(1, 3))
            posts = WebDriverWait(driver, 10).until(
                EC.presence_of_all_elements_located((By.XPATH, "//div[@aria-label='Actions for this post']"))
            )
            deleted_count = 0
            for post in posts[:5]:  # Limit to avoid bans
                post.click()
                await asyncio.sleep(random.uniform(0.5, 1))
                if criteria == "no_interaction":
                    try:
                        reactions = driver.find_elements(By.XPATH, ".//span[contains(@aria-label, 'reaction')]")
                        if not reactions:
                            delete_option = WebDriverWait(driver, 5).until(
                                EC.element_to_be_clickable((By.XPATH, "//span[contains(text(), 'Delete post')]"))
                            )
                            delete_option.click()
                            await asyncio.sleep(random.uniform(1, 2))
                            confirm_button = driver.find_element(By.XPATH, "//div[@aria-label='Delete']")
                            confirm_button.click()
                            deleted_count += 1
                    except (TimeoutException, NoSuchElementException):
                        continue
                await asyncio.sleep(random.uniform(1, 2))
            self._log(f"Deleted {deleted_count} posts", "INFO", account_id, group_id)
        except (TimeoutException, NoSuchElementException) as e:
            self._log(f"Failed to locate post elements: {str(e)}\n{traceback.format_exc()}", "ERROR", account_id, group_id)
        except Exception as e:
            self._log(f"Failed to delete posts: {str(e)}\n{traceback.format_exc()}", "ERROR", account_id, group_id)
        finally:
            self.session_manager.close_driver(account_id)

    async def share_post(self, group_id: str, post_url: str, attachments: Optional[List[str]] = None) -> None:
        """Share a post to a group with optional media."""
        start_time = datetime.now()
        try:
            accounts = self.db.get_accounts()
            if not accounts:
                self._log("No accounts available for sharing post", "WARNING")
                self.statusUpdated.emit("No accounts available")
                return

            total = len(accounts)
            tasks = []
            loop = asyncio.get_running_loop()
            for i, acc in enumerate(accounts):
                driver = self.setup_driver(acc[0], acc)
                if driver:
                    task = asyncio.create_task(self._share_post_task(driver, acc[0], group_id, post_url, attachments))
                    tasks.append(task)
                self.progressUpdated.emit(i + 1, total)

            results = await asyncio.gather(*tasks, return_exceptions=True)
            for i, result in enumerate(results):
                if isinstance(result, Exception):
                    self._log(f"Error sharing post for account {accounts[i][0]}: {str(result)}\n{traceback.format_exc()}", "ERROR", accounts[i][0])

            execution_time = (datetime.now() - start_time).total_seconds()
            self._log(f"Shared post {post_url} to {group_id} in {execution_time:.2f} seconds", "INFO")
            self.statusUpdated.emit(f"Shared post {post_url} to {group_id}")
            if QApplication.instance():
                QMetaObject.invokeMethod(
                    self.app.ui if hasattr(self.app, 'ui') else None,
                    "show_message", Qt.QueuedConnection,
                    Q_ARG(str, "Success"), Q_ARG(str, "Post shared successfully"), Q_ARG(str, "Information")
                )
        except Exception as e:
            self._log(f"Error sharing post to {group_id}: {str(e)}\n{traceback.format_exc()}", "ERROR")
            self.statusUpdated.emit(f"Error: {str(e)}")

    async def _share_post_task(self, driver: webdriver.Chrome, account_id: str, group_id: str, post_url: str, attachments: Optional[List[str]]) -> None:
        """Task to share a post."""
        try:
            driver.get(self._sanitize_input(post_url))
            await asyncio.sleep(random.uniform(1, 3))
            share_button = WebDriverWait(driver, 10).until(
                EC.element_to_be_clickable((By.XPATH, "//span[contains(text(), 'Share')]"))
            )
            share_button.click()
            await asyncio.sleep(random.uniform(1, 2))
            group_option = driver.find_element(By.XPATH, f"//a[contains(@href, '/groups/{self._sanitize_input(group_id)}')]")
            group_option.click()
            if attachments:
                for attachment in attachments:
                    if attachment.endswith(('.jpg', '.jpeg', '.png', '.mp4', '.avi')):
                        driver.find_element(By.XPATH, "//input[@type='file']").send_keys(self._sanitize_input(attachment))
                        await asyncio.sleep(1)
            await asyncio.sleep(random.uniform(1, 2))
            driver.find_element(By.XPATH, "//div[@aria-label='Post']").click()
            self._log(f"Shared post {post_url}", "INFO", account_id, group_id)
        except (TimeoutException, NoSuchElementException) as e:
            self._log(f"Failed to locate share elements: {str(e)}\n{traceback.format_exc()}", "ERROR", account_id, group_id)
        except Exception as e:
            self._log(f"Failed to share post: {str(e)}\n{traceback.format_exc()}", "ERROR", account_id, group_id)
        finally:
            self.session_manager.close_driver(account_id)

    async def send_message(self, user_id: str, message: str) -> None:
        """Send a private message to a user."""
        start_time = datetime.now()
        try:
            accounts = self.db.get_accounts()
            if not accounts:
                self._log("No accounts available for sending message", "WARNING")
                self.statusUpdated.emit("No accounts available")
                return

            total = len(accounts)
            tasks = []
            loop = asyncio.get_running_loop()
            for i, acc in enumerate(accounts):
                driver = self.setup_driver(acc[0], acc)
                if driver:
                    task = asyncio.create_task(self._send_message_task(driver, acc[0], user_id, message))
                    tasks.append(task)
                self.progressUpdated.emit(i + 1, total)

            results = await asyncio.gather(*tasks, return_exceptions=True)
            for i, result in enumerate(results):
                if isinstance(result, Exception):
                    self._log(f"Error sending message for account {accounts[i][0]}: {str(result)}\n{traceback.format_exc()}", "ERROR", accounts[i][0])

            execution_time = (datetime.now() - start_time).total_seconds()
            self._log(f"Sent message to {user_id} in {execution_time:.2f} seconds", "INFO")
            self.statusUpdated.emit(f"Sent message to {user_id}")
            if QApplication.instance():
                QMetaObject.invokeMethod(
                    self.app.ui if hasattr(self.app, 'ui') else None,
                    "show_message", Qt.QueuedConnection,
                    Q_ARG(str, "Success"), Q_ARG(str, "Message sent"), Q_ARG(str, "Information")
                )
        except Exception as e:
            self._log(f"Error sending message to {user_id}: {str(e)}\n{traceback.format_exc()}", "ERROR")
            self.statusUpdated.emit(f"Error: {str(e)}")

    async def _send_message_task(self, driver: webdriver.Chrome, account_id: str, user_id: str, message: str) -> None:
        """Task to send a message."""
        try:
            driver.get(f"https://www.facebook.com/messages/t/{self._sanitize_input(user_id)}")
            await asyncio.sleep(random.uniform(1, 3))
            textbox = WebDriverWait(driver, 10).until(
                EC.presence_of_element_located((By.XPATH, "//div[@role='textbox']"))
            )
            spun_message = spin_content(self._sanitize_input(message), self.config, lambda msg: self.statusUpdated.emit(msg))
            textbox.send_keys(spun_message)
            await asyncio.sleep(random.uniform(1, 2))
            driver.find_element(By.XPATH, "//div[@aria-label='Press Enter to send']").click()
            self._log(f"Sent message: {spun_message}", "INFO", account_id, user_id)
        except (TimeoutException, NoSuchElementException) as e:
            self._log(f"Failed to locate message elements: {str(e)}\n{traceback.format_exc()}", "ERROR", account_id, user_id)
        except Exception as e:
            self._log(f"Failed to send message: {str(e)}\n{traceback.format_exc()}", "ERROR", account_id, user_id)
        finally:
            self.session_manager.close_driver(account_id)

    async def interact_with_members(self, group_id: str) -> None:
        """Interact with group members."""
        start_time = datetime.now()
        try:
            accounts = self.db.get_accounts()
            if not accounts:
                self._log("No accounts available for member interaction", "WARNING")
                self.statusUpdated.emit("No accounts available")
                return

            total = len(accounts)
            tasks = []
            loop = asyncio.get_running_loop()
            for i, acc in enumerate(accounts):
                driver = self.setup_driver(acc[0], acc)
                if driver:
                    task = asyncio.create_task(self._interact_with_members_task(driver, acc[0], group_id))
                    tasks.append(task)
                self.progressUpdated.emit(i + 1, total)

            results = await asyncio.gather(*tasks, return_exceptions=True)
            for i, result in enumerate(results):
                if isinstance(result, Exception):
                    self._log(f"Error interacting with members for account {accounts[i][0]}: {str(result)}\n{traceback.format_exc()}", "ERROR", accounts[i][0])

            execution_time = (datetime.now() - start_time).total_seconds()
            self._log(f"Interacted with members in {group_id} in {execution_time:.2f} seconds", "INFO")
            self.statusUpdated.emit(f"Interacted with members in {group_id}")
            if QApplication.instance():
                QMetaObject.invokeMethod(
                    self.app.ui if hasattr(self.app, 'ui') else None,
                    "show_message", Qt.QueuedConnection,
                    Q_ARG(str, "Success"), Q_ARG(str, "Interacted with members"), Q_ARG(str, "Information")
                )
        except Exception as e:
            self._log(f"Error interacting with members in {group_id}: {str(e)}\n{traceback.format_exc()}", "ERROR")
            self.statusUpdated.emit(f"Error: {str(e)}")

    async def _interact_with_members_task(self, driver: webdriver.Chrome, account_id: str, group_id: str) -> None:
        """Task to interact with members."""
        try:
            driver.get(f"https://www.facebook.com/groups/{self._sanitize_input(group_id)}/members")
            await asyncio.sleep(random.uniform(1, 3))
            members = WebDriverWait(driver, 10).until(
                EC.presence_of_all_elements_located((By.XPATH, "//a[contains(@href, '/profile.php')]"))
            )
            for member in members[:5]:  # Limit to avoid bans
                member_id = (
                    self._sanitize_input(member.get_attribute("href").split("id=")[1].split('&')[0])
                    if "id=" in member.get_attribute("href")
                    else self._sanitize_input(member.get_attribute("href").split("/")[-2])
                )
                if self.config.get("custom_scripts") and random.choice([True, False]):
                    message = random.choice(self.config["custom_scripts"])
                    await self._send_message_task(driver, account_id, member_id, message)
                driver.get(f"https://www.facebook.com/groups/{self._sanitize_input(group_id)}")
                await asyncio.sleep(random.uniform(1, 2))
                if random.choice([True, False]):
                    try:
                        like_buttons = driver.find_elements(By.XPATH, "//button[contains(@aria-label, 'Like')]")
                        if like_buttons:
                            like_buttons[0].click()
                            self._log(f"Liked post of {member_id}", "INFO", account_id, group_id)
                    except NoSuchElementException:
                        pass
                if random.choice([True, False]) and self.config.get("custom_scripts"):
                    try:
                        comment_boxes = driver.find_elements(By.XPATH, "//div[@role='textbox']")
                        if comment_boxes:
                            comment = random.choice(self.config["custom_scripts"])
                            comment_boxes[0].send_keys(comment)
                            await asyncio.sleep(random.uniform(1, 2))
                            driver.find_element(By.XPATH, "//button[@type='submit']").click()
                            self._log(f"Commented on {member_id}'s post: {comment}", "INFO", account_id, group_id)
                    except NoSuchElementException:
                        pass
        except (TimeoutException, NoSuchElementException) as e:
            self._log(f"Failed to locate interaction elements: {str(e)}\n{traceback.format_exc()}", "ERROR", account_id, group_id)
        except Exception as e:
            self._log(f"Failed to interact with members: {str(e)}\n{traceback.format_exc()}", "ERROR", account_id, group_id)
        finally:
            self.session_manager.close_driver(account_id)

    async def transfer_members_between_groups(self, source_group_id: str, target_group_id: str) -> None:
        """Transfer members between two groups."""
        start_time = datetime.now()
        try:
            member_ids = await self.extract_group_members(source_group_id)
            if not member_ids:
                self._log(f"No members found in {source_group_id}", "WARNING")
                self.statusUpdated.emit(f"No members found in {source_group_id}")
                return

            await self.add_members_to_group(target_group_id, "\n".join(member_ids))
            execution_time = (datetime.now() - start_time).total_seconds()
            self._log(f"Transferred {len(member_ids)} members from {source_group_id} to {target_group_id} in {execution_time:.2f} seconds", "INFO")
            self.statusUpdated.emit(f"Transferred {len(member_ids)} members from {source_group_id} to {target_group_id}")
            if QApplication.instance():
                QMetaObject.invokeMethod(
                    self.app.ui if hasattr(self.app, 'ui') else None,
                    "show_message", Qt.QueuedConnection,
                    Q_ARG(str, "Success"), Q_ARG(str, f"Transferred members from {source_group_id} to {target_group_id}"), Q_ARG(str, "Information")
                )
        except Exception as e:
            self._log(f"Error transferring members: {str(e)}\n{traceback.format_exc()}", "ERROR")
            self.statusUpdated.emit(f"Error: {str(e)}")

    def cleanup_old_data(self, days: int = 30) -> None:
        """Clean up old group data (placeholder for DB integration)."""
        try:
            self.db.cleanup_old_logs(days)
            self._log(f"Cleaned up data older than {days} days", "INFO")
        except Exception as e:
            self._log(f"Error cleaning up old data: {str(e)}\n{traceback.format_exc()}", "ERROR")

if __name__ == "__main__":
    from PyQt5.QtWidgets import QApplication
    import sys
    app = QApplication(sys.argv)
    class DummyApp:
        class DummyUI:
            def show_message(self, title, message, icon):
                print(f"[{title}] {message}")
        ui = DummyUI()
        def rotate_proxy(self, session_id):
            return "http://proxy1:port"
    class DummyConfig:
        def get(self, key, default=None):
            defaults = {
                "mobile_size": "360x640",
                "chrome_path": "drivers/chrome.exe",
                "chromedriver_path": "drivers/chromedriver.exe",
                "custom_scripts": ["Test comment"],
                "proxies": ["http://proxy1:port"],
                "proxy_rotation_enabled": True
            }
            return defaults.get(key, default)
    class DummyDatabase:
        def get_accounts(self):
            return [("fb1", "pass", "email@example.com", None, None, "encrypted_cookies", "Logged In", None, 0, 0)]
        def get_account(self, account_id):
            return ("fb1", "pass", "email@example.com", None, None, "encrypted_cookies", "Logged In", None, 0, 0)
        def add_group(self, account_id, group_id, group_name, privacy, created_time="", description="", administrator="false", member_count=0):
            print(f"Added group: {group_id}")
        def get_groups(self, account_id):
            return [(1, "fb1", "group1", "Test Group", 0, "", "", "false", 100, "Active", "")]
        def update_account(self, account_id, **kwargs):
            print(f"Updated account {account_id}: {kwargs}")
        def cleanup_old_logs(self, days):
            print(f"Cleaned logs older than {days} days")
    class DummyLogManager:
        def add_log(self, fb_id, target, action, level, message):
            print(f"[{level}] {action}: {message}")
    class DummySessionManager:
        def get_driver(self, account_id, chrome_options):
            class DummyDriver:
                def get(self, url): print(f"Navigated to {url}")
                def find_elements(self, by, value): return []
                def find_element(self, by, value): return self
                def click(self): pass
                def send_keys(self, text): pass
                def execute_script(self, script): pass
                current_url = "https://www.facebook.com"
            return DummyDriver()
        def close_driver(self, account_id): pass
        def close_all_drivers(self): pass
        def rotate_proxy(self, session_id):
            return "http://proxy1:port"
    dummy_app = DummyApp()
    group_manager = GroupManager(dummy_app, DummyDatabase(), DummySessionManager(), DummyConfig(), DummyLogManager())
    asyncio.run(group_manager.extract_all_groups(keywords="test"))
    sys.exit(app.exec_())