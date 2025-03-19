import asyncio
import random
import requests
import os
import json
import base64
import subprocess
import traceback
import shutil
from typing import Dict, Optional, List, Callable, Any
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.service import Service
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from PIL import Image, ImageDraw, ImageFont
from PyQt5.QtWidgets import QApplication, QMessageBox
from PyQt5.QtCore import QObject, pyqtSignal, Qt, QMetaObject, Q_ARG
from datetime import datetime
import chromedriver_autoinstaller

class SessionManager(QObject):
    driverCreated = pyqtSignal(str)
    driverClosed = pyqtSignal(str)
    statusUpdated = pyqtSignal(str)

    def __init__(self, app, config_manager):
        super().__init__()
        try:
            self.app = app
            self.config_manager = config_manager
            self.drivers: Dict[str, webdriver.Chrome] = {}
            self.active_sessions: Dict[str, bool] = {}
            self.base_dir = os.path.dirname(os.path.abspath(__file__))
            self._log("SessionManager initialized successfully", "Info")
        except Exception as e:
            error_message = f"Error initializing SessionManager: {str(e)}\n{traceback.format_exc()}"
            self._log(error_message, "Error")
            raise

    def _log(self, message: str, level: str, fb_id: str = "System", action: str = "SessionManager") -> None:
        try:
            sanitized_message = self._sanitize_input(message)
            sanitized_fb_id = self._sanitize_input(fb_id)
            sanitized_action = self._sanitize_input(action)
            self.app.log_manager.add_log(sanitized_fb_id, None, sanitized_action, level, sanitized_message)
            self.statusUpdated.emit(f"{level}: {sanitized_message}")
        except Exception as e:
            error_message = f"Error logging in SessionManager: {str(e)}\n{traceback.format_exc()}"
            with open(os.path.join(self.base_dir, "fallback.log"), "a", encoding="utf-8") as f:
                f.write(f"[{datetime.now()}] {error_message}\n")

    def _sanitize_input(self, value: Any) -> str:
        if value is None:
            return ""
        return str(value).replace("'", "''").replace(";", "").strip()

    def get_driver(self, account_id: str, chrome_options: Optional[Options] = None, proxy: Optional[str] = None, 
                   mobile: bool = True, visible: bool = True) -> webdriver.Chrome:
        try:
            chromedriver_autoinstaller.install()
            if account_id in self.drivers and self.drivers[account_id].service.process.poll() is None:
                return self.drivers[account_id]

            if chrome_options is None:
                chrome_options = Options()
                chrome_options.add_argument("--disable-notifications")
                chrome_options.add_argument("--disable-infobars")
                chrome_options.add_argument("--no-sandbox")
                chrome_options.add_argument("--disable-dev-shm-usage")
                if mobile:
                    chrome_options.add_argument(f"--window-size={self.config_manager.get('mobile_size', '360x640').replace('x', ',')}")
                chrome_options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36")
                if not visible:
                    chrome_options.add_argument("--headless")

            chrome_path = os.path.join(self.base_dir, self.config_manager.get("chrome_path", "drivers/chrome.exe"))
            if not os.path.exists(chrome_path):
                raise FileNotFoundError(f"Chrome not found at {chrome_path}")

            chrome_version = self.config_manager.get("chrome_version", "133")
            current_version = self._get_chrome_version(chrome_path)
            if current_version and not current_version.startswith(chrome_version):
                raise Exception(f"Chrome version mismatch. Expected: {chrome_version}, Found: {current_version}")

            if not proxy and self.config_manager.get("proxy_rotation_enabled", True):
                proxy = self.rotate_proxy(account_id)

            if proxy:
                chrome_options.add_argument(f"--proxy-server={proxy}")
                self._log(f"Using proxy {proxy} for {account_id}", "Info", account_id)

            chrome_options.binary_location = chrome_path
            service = Service()
            driver = webdriver.Chrome(service=service, options=chrome_options)
            self.drivers[account_id] = driver
            self.active_sessions[account_id] = True
            self.driverCreated.emit(account_id)
            self._log(f"Driver created for {account_id}", "Info", account_id)
            return driver
        except Exception as e:
            error_message = f"Error creating driver for {account_id}: {str(e)}\n{traceback.format_exc()}"
            self._log(error_message, "Error", account_id)
            raise

    def _get_chrome_version(self, chrome_path: str) -> Optional[str]:
        try:
            cmd = f'"{chrome_path}" --version'
            output = subprocess.check_output(cmd, shell=True, stderr=subprocess.STDOUT).decode().strip()
            version = output.split()[-1]
            self._log(f"Detected Chrome version: {version}", "Info")
            return version
        except subprocess.CalledProcessError as e:
            self._log(f"Error detecting Chrome version: {str(e)}\n{traceback.format_exc()}", "Error")
            return None

    def close_driver(self, account_id: str) -> None:
        if account_id in self.drivers:
            try:
                self.drivers[account_id].quit()
            except Exception as e:
                self._log(f"Error quitting driver for {account_id}: {str(e)}\n{traceback.format_exc()}", "Warning", account_id)
            finally:
                del self.drivers[account_id]
                del self.active_sessions[account_id]
                self.driverClosed.emit(account_id)
                self._log(f"Closed driver for {account_id}", "Info", account_id)

    def close_all_drivers(self) -> None:
        for account_id in list(self.drivers.keys()):
            self.close_driver(account_id)
        self._log("Closed all drivers successfully", "Info")

    async def auto_reply_to_comments(self, account_id: str, post_url: str, cookies: str, 
                                    max_checks: int = 10, check_interval: int = 60) -> None:
        driver = None
        try:
            driver = self.get_driver(account_id, mobile=True, visible=False)
            if not await asyncio.wait_for(self._verify_cookies(driver, cookies, account_id), timeout=30):
                self._log("Cookies verification failed or timed out, stopping auto-reply", "Error", account_id)
                return

            custom_scripts = self.config_manager.get("custom_scripts", [
                "للتواصل والاستفسار، يرجى الاتصال على 01225398839",
                "شكرًا على تفاعلك! لمزيد من التفاصيل، اتصل على 01225398839"
            ])
            default_response = random.choice(custom_scripts)
            keywords_responses = {
                "رقم": custom_scripts[0], "تليفون": custom_scripts[0], "هاتف": custom_scripts[0],
                "اتصال": custom_scripts[0], "تواصل": custom_scripts[0],
                "مواعيد": "نعم، يرجى الاتصال على 01225398839 لمعرفة المواعيد",
                "السلام عليكم": "وعليكم السلام، للتواصل يرجى الاتصال على 01225398839"
            }
            responded_comments = set()
            responded_likes = set()

            for check in range(max_checks):
                if predictive_ban_detection(driver, self.config_manager, lambda msg: self.statusUpdated.emit(msg)):
                    self.statusUpdated.emit(f"Ban detected for {account_id}, stopping auto-reply")
                    break

                driver.get(self._sanitize_input(post_url))
                await asyncio.sleep(random.uniform(2, 4))

                like_elements = driver.find_elements(By.XPATH, "//span[contains(text(), 'Like')]//ancestor::a[@role='button']")
                for like_elem in like_elements[:5]:
                    user_id = self._sanitize_input(like_elem.get_attribute("href").split("id=")[-1] if "id=" in like_elem.get_attribute("href") else like_elem.get_attribute("href").split("/")[-2])
                    if user_id not in responded_likes:
                        WebDriverWait(driver, 10).until(EC.element_to_be_clickable(like_elem)).click()
                        await asyncio.sleep(random.uniform(1, 2))
                        WebDriverWait(driver, 10).until(EC.element_to_be_clickable((By.XPATH, "//div[contains(text(), 'Comment')]"))).click()
                        comment_box = WebDriverWait(driver, 10).until(EC.presence_of_element_located((By.XPATH, "//div[@aria-label='Write a comment...']")))
                        comment_box.send_keys(default_response)
                        driver.find_element(By.XPATH, "//div[@aria-label='Press Enter to post']").click()
                        self._log(f"Auto-liked and replied to like by {user_id} on {post_url}", "Info", account_id)
                        responded_likes.add(user_id)
                        await asyncio.sleep(random.uniform(1, 2))

                comment_elements = driver.find_elements(By.XPATH, "//div[@data-visualcompletion='ignore-dynamic']//div[@role='article']")
                for comment in comment_elements[:5]:
                    comment_text = self._sanitize_input(comment.text.lower())
                    user_elements = comment.find_elements(By.XPATH, ".//a[@role='link']")
                    if not user_elements:
                        continue
                    user_id = self._sanitize_input(user_elements[0].get_attribute("href").split("id=")[-1] if "id=" in user_elements[0].get_attribute("href") else user_elements[0].get_attribute("href").split("/")[-2])
                    comment_id = f"{user_id}_{comment_text[:20]}"
                    if comment_id not in responded_comments:
                        like_button = WebDriverWait(driver, 10).until(EC.element_to_be_clickable((By.XPATH, ".//span[contains(text(), 'Like')]")))
                        like_button.click()
                        response = default_response
                        for keyword, reply in keywords_responses.items():
                            if keyword in comment_text:
                                response = reply
                                break
                        reply_box = WebDriverWait(driver, 10).until(EC.presence_of_element_located((By.XPATH, ".//div[@aria-label='Write a reply...']")))
                        reply_box.send_keys(response)
                        driver.find_element(By.XPATH, "//div[@aria-label='Press Enter to post']").click()
                        self._log(f"Auto-liked and replied to comment by {user_id} on {post_url}: {response}", "Info", account_id)
                        responded_comments.add(comment_id)
                        await asyncio.sleep(random.uniform(1, 2))

                await asyncio.sleep(check_interval)
        except asyncio.TimeoutError:
            self._log(f"Timeout in auto_reply_to_comments for {account_id}", "Error", account_id)
        except Exception as e:
            error_message = f"Error in auto_reply_to_comments for {account_id}: {str(e)}\n{traceback.format_exc()}"
            self._log(error_message, "Error", account_id)
            if QApplication.instance():
                QMessageBox.critical(None, "Error", f"Auto-reply failed: {str(e)}")
        finally:
            if driver:
                self.close_driver(account_id)

    def rotate_proxy(self, account_id: str) -> Optional[str]:
        try:
            proxies = self.config_manager.get("proxies", [])
            if not proxies:
                self._log("No proxies available for rotation", "Warning", account_id)
                return None
            proxy = random.choice(proxies)
            self._log(f"Rotated proxy for {account_id} to {proxy}", "Info", account_id)
            return proxy
        except Exception as e:
            self._log(f"Error rotating proxy for {account_id}: {str(e)}\n{traceback.format_exc()}", "Error", account_id)
            return None

    async def _verify_cookies(self, driver: webdriver.Chrome, cookies: str, account_id: str) -> bool:
        try:
            load_cookies(driver, self._sanitize_input(cookies), lambda msg: self.statusUpdated.emit(msg))
            driver.get("https://www.facebook.com")
            await asyncio.sleep(2)
            if "login" in driver.current_url.lower() or predictive_ban_detection(driver, self.config_manager, lambda msg: self.statusUpdated.emit(msg)):
                self.statusUpdated.emit(f"Re-authenticating {account_id} due to invalid cookies or ban")
                success = await asyncio.wait_for(
                    self.app.account_manager.login_account(account_id, None, None, "Selenium", False, None, reauth=True),
                    timeout=60
                )
                if not success:
                    self._log(f"Failed to re-authenticate {account_id}", "Error", account_id)
                    return False
                return True
            return True
        except asyncio.TimeoutError:
            self._log(f"Timeout verifying cookies for {account_id}", "Error", account_id)
            return False
        except Exception as e:
            self._log(f"Error verifying cookies for {account_id}: {str(e)}\n{traceback.format_exc()}", "Error", account_id)
            return False

def load_cookies(driver: webdriver.Chrome, cookies: str, update_status: Callable[[str], None]) -> None:
    try:
        driver.delete_all_cookies()
        driver.get("https://www.facebook.com")
        cookie_list = json.loads(decrypt_data(cookies.encode(), lambda x, y=None: None))
        for cookie in cookie_list:
            cookie["secure"] = True
            driver.add_cookie(cookie)
        driver.refresh()
        update_status("Cookies loaded successfully")
    except Exception as e:
        error_message = f"Error loading cookies: {str(e)}\n{traceback.format_exc()}"
        update_status(error_message)
        raise

def encrypt_data(data: str, config_manager: Callable[[str, Optional[Any]], Any]) -> str:
    try:
        key = _generate_key(config_manager)
        fernet = Fernet(key)
        return fernet.encrypt(str(data).encode()).decode()
    except Exception as e:
        raise Exception(f"Error encrypting data: {str(e)}\n{traceback.format_exc()}")

def decrypt_data(encrypted_data: bytes, config_manager: Callable[[str, Optional[Any]], Any]) -> str:
    try:
        key = _generate_key(config_manager)
        fernet = Fernet(key)
        return fernet.decrypt(encrypted_data).decode()
    except Exception as e:
        raise Exception(f"Error decrypting data: {str(e)}\n{traceback.format_exc()}")

def _generate_key(config_manager: Callable[[str, Optional[Any]], Any]) -> bytes:
    try:
        salt = config_manager.get("encryption_salt", b'smart_poster_salt').encode()
        kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt, iterations=100000)
        return base64.urlsafe_b64encode(kdf.derive(b"smart_poster_key"))
    except Exception as e:
        raise Exception(f"Error generating encryption key: {str(e)}\n{traceback.format_exc()}")

async def solve_captcha(driver: webdriver.Chrome, api_key: str, email: Optional[str] = None, 
                       update_status: Callable[[str], None] = None, max_retries: int = 10) -> bool:
    if "checkpoint" not in driver.current_url:
        if update_status:
            update_status("No CAPTCHA detected")
        return True
    try:
        site_key = WebDriverWait(driver, 10).until(EC.presence_of_element_located((By.XPATH, "//div[@class='g-recaptcha']"))).get_attribute("data-sitekey")
        url = driver.current_url
        response = await asyncio.wait_for(
            asyncio.to_thread(requests.post, "http://2captcha.com/in.php", data={
                "key": api_key, "method": "userrecaptcha", "googlekey": site_key, "pageurl": url
            }, timeout=10),
            timeout=15
        )
        if response.status_code != 200 or "OK" not in response.text:
            alt_response = await asyncio.wait_for(
                asyncio.to_thread(requests.post, "http://api.anti-captcha.com/createTask", json={
                    "clientKey": api_key, "task": {"type": "ReCaptchaV2TaskProxyless", "websiteURL": url, "websiteKey": site_key}
                }, timeout=10),
                timeout=15
            )
            if alt_response.status_code != 200 or alt_response.json().get("errorId", 1) != 0:
                if update_status:
                    update_status(f"Failed to submit CAPTCHA: 2Captcha and Anti-Captcha unavailable")
                return False
            captcha_id = alt_response.json()["taskId"]
            for _ in range(max_retries):
                result = await asyncio.wait_for(
                    asyncio.to_thread(requests.get, f"http://api.anti-captcha.com/getTaskResult?clientKey={api_key}&taskId={captcha_id}", timeout=10),
                    timeout=15
                )
                if result.json()["status"] == "ready":
                    token = result.json()["solution"]["gRecaptchaResponse"]
                    driver.execute_script(f"document.getElementById('g-recaptcha-response').innerHTML='{token}';")
                    driver.find_element(By.ID, "checkpointSubmitButton").click()
                    await asyncio.sleep(5)
                    if update_status:
                        update_status("CAPTCHA solved with Anti-Captcha")
                    return True
                await asyncio.sleep(5)
            if update_status:
                update_status("CAPTCHA solving timed out with Anti-Captcha")
            return False
        captcha_id = response.text.split("|")[1]
        for _ in range(max_retries):
            result = await asyncio.wait_for(
                asyncio.to_thread(requests.get, f"http://2captcha.com/res.php?key={api_key}&action=get&id={captcha_id}", timeout=10),
                timeout=15
            )
            if "CAPCHA_NOT_READY" not in result.text and "OK" in result.text:
                token = result.text.split("|")[1]
                driver.execute_script(f"document.getElementById('g-recaptcha-response').innerHTML='{token}';")
                driver.find_element(By.ID, "checkpointSubmitButton").click()
                await asyncio.sleep(5)
                if update_status:
                    update_status("CAPTCHA solved with 2Captcha")
                return True
            await asyncio.sleep(5)
        if update_status:
            update_status("CAPTCHA solving timed out with 2Captcha")
        return False
    except asyncio.TimeoutError:
        if update_status:
            update_status("CAPTCHA solving timed out")
        return False
    except Exception as e:
        if update_status:
            update_status(f"Failed to solve CAPTCHA: {str(e)}")
        return False

async def get_access_token(driver: webdriver.Chrome, config_manager: Callable[[str, Optional[Any]], Any], 
                          update_status: Callable[[str], None] = None) -> Optional[str]:
    try:
        driver.get("https://developers.facebook.com/tools/explorer/")
        token_field = WebDriverWait(driver, 20).until(EC.presence_of_element_located((By.XPATH, "//input[@id='access_token']")))
        token = token_field.get_attribute("value")
        if token:
            if update_status:
                update_status("Access Token extracted successfully")
            return token
        if update_status:
            update_status("Failed to extract Access Token")
        return None
    except Exception as e:
        if update_status:
            update_status(f"Error extracting Access Token: {str(e)}")
        return None

def predictive_ban_detection(driver: webdriver.Chrome, config_manager: Callable[[str, Optional[Any]], Any], 
                             update_status: Callable[[str], None] = None) -> bool:
    try:
        current_url = driver.current_url.lower()
        ban_keywords = config_manager.get("ban_keywords", ["login", "checkpoint", "suspended", "disabled", "banned"])
        if any(keyword in current_url for keyword in ban_keywords):
            if update_status:
                update_status("Potential ban detected in URL")
            return True
        ban_messages = driver.find_elements(By.XPATH, "//div[contains(text(), 'banned') or contains(text(), 'suspended')]")
        if ban_messages:
            if update_status:
                update_status("Ban confirmed by on-page message")
            return True
        response = requests.get(driver.current_url, timeout=5)
        ban_status_codes = config_manager.get("ban_status_codes", [403, 429])
        if response.status_code in ban_status_codes:
            if update_status:
                update_status(f"Ban detected via HTTP status code: {response.status_code}")
            return True
        return False
    except requests.RequestException:
        return False
    except Exception as e:
        if update_status:
            update_status(f"Error in ban detection: {str(e)}")
        return False

def spin_content(content: str, config_manager: Callable[[str, Optional[Any]], Any], update_status: Callable[[str], None] = None) -> str:
    try:
        usage = shutil.disk_usage(os.path.dirname(os.path.abspath(__file__)))
        if usage.free < 1024 * 1024:
            if update_status:
                update_status("Insufficient disk space for spinning content")
            return content

        synonyms = {
            "hello": ["hi", "hey", "greetings"], "great": ["awesome", "fantastic", "wonderful"],
            "good": ["fine", "nice", "perfect"], "check": ["see", "look", "explore"],
            "happy": ["glad", "joyful", "pleased"], "amazing": ["incredible", "stunning", "fabulous"],
            "love": ["adore", "enjoy", "like"], "new": ["fresh", "recent", "latest"],
            "today": ["now", "this day", "currently"], "best": ["top", "finest", "greatest"]
        }
        words = content.split()
        for i, word in enumerate(words):
            word_lower = word.lower()
            if word_lower in synonyms:
                words[i] = random.choice(synonyms[word_lower])
        spun_text = " ".join(words)

        custom_scripts = config_manager.get("custom_scripts", ["Thanks for your interest!"])
        if custom_scripts and random.random() < 0.5:
            spun_text += " " + random.choice(custom_scripts)

        image_extensions = ['.png', '.jpg', '.jpeg']
        if any(ext in content.lower() for ext in image_extensions) and os.path.exists(content):
            img = Image.open(content)
            draw = ImageDraw.Draw(img)
            font = ImageFont.load_default()
            draw.text((10, 10), spun_text, fill="black", font=font)
            output_path = f"spun_{os.path.basename(content)}"
            img.save(output_path)
            if update_status:
                update_status(f"Spun image saved as {output_path}")
            return output_path

        if update_status:
            update_status(f"Spun content: {spun_text}")
        return spun_text
    except Exception as e:
        if update_status:
            update_status(f"Error spinning content: {str(e)}")
        return content

async def simulate_human_behavior(driver: webdriver.Chrome, config_manager: Callable[[str, Optional[Any]], Any], 
                                 update_status: Callable[[str], None] = None) -> None:
    try:
        scroll_position = random.randint(100, 500)
        driver.execute_script(f"window.scrollTo(0, {scroll_position});")
        await asyncio.sleep(random.uniform(1, 3))
        if update_status:
            update_status("Simulating scroll behavior")

        like_buttons = driver.find_elements(By.XPATH, "//button[contains(@aria-label, 'Like')]")
        if like_buttons and random.choice([True, False]):
            WebDriverWait(driver, 10).until(EC.element_to_be_clickable(like_buttons[0])).click()
            if update_status:
                update_status("Simulated like action")
            await asyncio.sleep(random.uniform(1, 2))

        comment_boxes = driver.find_elements(By.XPATH, "//div[@role='textbox']")
        custom_scripts = config_manager.get("custom_scripts", ["Nice post!"])
        if comment_boxes and random.choice([True, False]):
            comment = random.choice(custom_scripts)
            WebDriverWait(driver, 10).until(EC.element_to_be_clickable(comment_boxes[0])).send_keys(comment)
            await asyncio.sleep(random.uniform(1, 2))
            submit_button = WebDriverWait(driver, 10).until(EC.element_to_be_clickable((By.XPATH, "//button[@type='submit']")))
            submit_button.click()
            if update_status:
                update_status(f"Simulated comment action: {comment}")
            await asyncio.sleep(random.uniform(1, 2))

        links = driver.find_elements(By.XPATH, "//a[@href]")
        if links and random.choice([True, False]):
            random_link = random.choice(links[:5])
            random_link.click()
            if update_status:
                update_status("Simulated link click action")
            await asyncio.sleep(random.uniform(2, 4))
            driver.back()
    except Exception as e:
        if update_status:
            update_status(f"Error simulating human behavior: {str(e)}")
        raise

base_dir = os.path.dirname(os.path.abspath(__file__))

if __name__ == "__main__":
    app = QApplication([])
    class DummyApp:
        class DummyLogManager:
            def add_log(self, fb_id, target, action, level, message):
                print(f"[{level}] {action}: {message}")
        log_manager = DummyLogManager()
        class DummyAccountManager:
            async def login_account(self, account_id, email=None, password=None, login_mode="Selenium", preliminary_interaction=False, chrome_options=None, reauth=False):
                print(f"Login {account_id}, reauth={reauth}")
                return True
        account_manager = DummyAccountManager()
        def rotate_proxy(self, session_id):
            return "http://proxy1:port"
    class DummyConfigManager:
        def get(self, key, default=None):
            return {
                "mobile_size": "360x640", "chrome_path": "drivers/chrome.exe", "chrome_version": "133",
                "proxies": ["http://proxy1:port"], "custom_scripts": ["Test script"], "encryption_salt": "smart_poster_salt"
            }.get(key, default)
    session_manager = SessionManager(DummyApp(), DummyConfigManager())
    driver = session_manager.get_driver("test_account")
    asyncio.run(session_manager.auto_reply_to_comments("test_account", "https://facebook.com/test_post", json.dumps([{"name": "test", "value": "test"}])))
    session_manager.close_all_drivers()
    app.exec_()