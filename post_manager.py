import asyncio
import random
import requests
import re
import os
import shutil
import json
from datetime import datetime
from typing import Optional, List, Dict, Any, Callable
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options
from PyQt5.QtWidgets import QMessageBox, QFileDialog, QApplication
from PyQt5.QtCore import pyqtSignal, QObject, Qt, QMetaObject, Q_ARG
import traceback
import chromedriver_autoinstaller
from utils import SessionManager, load_cookies, decrypt_data, solve_captcha, predictive_ban_detection, simulate_human_behavior, spin_content

class PostManager(QObject):
    statusUpdated = pyqtSignal(str)
    progressUpdated = pyqtSignal(int, int)

    def __init__(self, app, db, session_manager, config, log_manager):
        super().__init__()
        self.app = app
        self.db = db
        self.session_manager = session_manager
        self.config = config
        self.log_manager = log_manager
        if not self.log_manager:
            raise ValueError("LogManager is required")
        self.stop_flag = False
        self.posted_count = 0
        self.scheduler_task = None
        self._log("PostManager initialized successfully", "Info")

    def _log(self, message: str, level: str, account_id: str = "System", action: str = "Posts") -> None:
        try:
            sanitized_message = self._sanitize_input(message)
            sanitized_account_id = self._sanitize_input(account_id)
            sanitized_action = self._sanitize_input(action)
            self.log_manager.add_log(sanitized_account_id, None, sanitized_action, level, sanitized_message)
            self.statusUpdated.emit(f"{level}: {sanitized_message}")
        except Exception as e:
            error_message = f"Error logging: {str(e)}\n{traceback.format_exc()}"
            with open("fallback.log", "a", encoding="utf-8") as f:
                f.write(f"[{datetime.now()}] {error_message}\n")

    def _sanitize_input(self, value: Any) -> str:
        if value is None:
            return ""
        return str(value).replace("'", "''").replace(";", "").strip()

    def _get_chrome_options(self, index: int, mobile_view: bool = True, visible: bool = True) -> Options:
        chromedriver_autoinstaller.install()
        chrome_options = Options()
        chrome_options.add_argument("--disable-notifications")
        if mobile_view:
            chrome_options.add_argument(f"--window-size={self.config.get('mobile_size', '360x640').replace('x', ',')}")
        chrome_options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36")
        if not visible:
            chrome_options.add_argument("--headless")
        chrome_options.add_argument("--disable-gpu")
        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument(f"--window-position={index * 400 % 1600},{index * 400 // 1600}")
        chrome_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), self.config.get("chrome_path", "drivers/chrome.exe"))
        if os.path.exists(chrome_path):
            chrome_options.binary_location = chrome_path
        if self.config.get("proxy_rotation_enabled", True) and self.config.get("proxies"):
            proxy = self.session_manager.rotate_proxy(f"Session-{index}")
            if proxy:
                chrome_options.add_argument(f"--proxy-server={proxy}")
                self._log(f"Using proxy {proxy} for session {index}", "Info")
        return chrome_options

    def _backup_database(self):
        db_path = self.config.get("db_path", "database.db")
        if os.path.exists(db_path):
            backup_path = f"{db_path}.{datetime.now().strftime('%Y%m%d%H%M%S')}.bak"
            shutil.copy2(db_path, backup_path)
            self._log(f"Database backup created at {backup_path}", "Info")

    async def post_all_content(self, target: str = "Groups", tech: str = "Selenium (Primary)", content: str = "", 
                              per_account_content: Optional[str] = None, global_content: Optional[str] = None, 
                              schedule_times: str = "", allow_duplicates: bool = False, spin_content_flag: bool = False, 
                              delay: Optional[float] = None, timer: Optional[float] = None, random_time: bool = False, 
                              stop_after_posts: Optional[int] = None, stop_unit: str = "Posts", stop_every: Optional[int] = None, 
                              resume_after: Optional[int] = None, resume_unit: str = "Minutes", silent_mode: bool = False, 
                              selected_groups: Optional[List[str]] = None, selected_accounts: Optional[List[str]] = None, 
                              attachments: Optional[List[str]] = None, auto_reply_enabled: bool = False) -> None:
        try:
            usage = shutil.disk_usage(os.path.dirname(os.path.abspath(__file__)))
            if usage.free < 1024 * 1024:
                raise RuntimeError("Insufficient disk space")
            delay = delay or self.config.get("default_delay", 5)
            max_retries = self.config.get("max_retries", 3)
            if schedule_times:
                self._backup_database()
                for time_str in schedule_times.split(","):
                    time_str = self._sanitize_input(time_str.strip())
                    if not re.match(r"^\d{2}:\d{2}$", time_str):
                        self._log(f"Invalid time format: {time_str}", "Error")
                        continue
                    post_id = self.db.add_scheduled_post(
                        self._sanitize_input(",".join(selected_accounts) if selected_accounts else "all"),
                        self._sanitize_input(content), time_str, 
                        group_id=self._sanitize_input(",".join(selected_groups) if selected_groups else None),
                        post_type="Text" if not attachments else "Media"
                    )
                    self._log(f"Scheduled post {post_id} at {time_str}", "Info", action="Scheduled Posts")
                self._log("Scheduled posting tasks added to database", "Info")
                self.statusUpdated.emit("Scheduled posting tasks created")
                if not self.scheduler_task or self.scheduler_task.done():
                    self.scheduler_task = asyncio.create_task(self._check_scheduled_posts())
            else:
                for attempt in range(max_retries):
                    try:
                        await self._post_content(
                            target, tech, content, per_account_content, global_content, allow_duplicates, 
                            spin_content_flag, delay, timer, random_time, stop_after_posts, stop_unit, stop_every, 
                            resume_after, resume_unit, silent_mode, selected_groups, selected_accounts, attachments, 
                            auto_reply_enabled
                        )
                        break
                    except Exception as e:
                        if attempt < max_retries - 1:
                            error_message = f"Retry {attempt + 1}/{max_retries} failed: {str(e)}\n{traceback.format_exc()}"
                            self._log(error_message, "Warning")
                            await asyncio.sleep(delay)
                        else:
                            error_message = f"Posting failed after {max_retries} retries: {str(e)}\n{traceback.format_exc()}"
                            self._log(error_message, "Error")
                            raise
            self._log("Posting process completed", "Info")
            self.statusUpdated.emit("Posting process completed")
            if QApplication.instance():
                QMetaObject.invokeMethod(self.app.ui if hasattr(self.app, 'ui') else None, 
                                        "show_message", Qt.QueuedConnection, 
                                        Q_ARG(str, "Success"), Q_ARG(str, "Posting process completed"), 
                                        Q_ARG(str, "Information"))
        except Exception as e:
            error_message = f"Error during posting: {str(e)}\n{traceback.format_exc()}"
            self._log(error_message, "Error")
            self.statusUpdated.emit(f"Error: {str(e)}")
            if QApplication.instance():
                QMessageBox.critical(None, "Error", f"Posting failed: {str(e)}")

    async def _check_scheduled_posts(self) -> None:
        while not self.stop_flag:
            try:
                now = datetime.now().strftime("%H:%M")
                scheduled_posts = self.db.get_scheduled_posts()
                for post in scheduled_posts:
                    post_id, fb_id, content, time_str, account_id, group_id, post_type, status = post
                    if status != "Pending" or now < time_str:
                        continue
                    accounts = self._sanitize_input(fb_id).split(",") if "," in fb_id else [self._sanitize_input(fb_id)]
                    selected_groups = self._sanitize_input(group_id).split(",") if group_id and "," in group_id else [self._sanitize_input(group_id)] if group_id else None
                    attachments = None
                    await self._post_content(
                        "Groups", "Selenium (Primary)", self._sanitize_input(content), None, None, False, False, 5, None, False,
                        None, "Posts", None, None, "Minutes", False, selected_groups, accounts, attachments,
                        self.config.get("auto_reply_enabled", False)
                    )
                    self.db.update_scheduled_post_status(post_id, "Posted")
                    self._log(f"Executed scheduled post {post_id}", "Info", fb_id, group_id or "Scheduled Posts")
                await asyncio.sleep(60)
            except Exception as e:
                error_message = f"Error checking scheduled posts: {str(e)}\n{traceback.format_exc()}"
                self._log(error_message, "Error")
                await asyncio.sleep(60)

    async def _post_content(self, target: str, tech: str, content: str, per_account_content: Optional[str], 
                           global_content: Optional[str], allow_duplicates: bool, spin_content_flag: bool, 
                           delay: float, timer: Optional[float], random_time: bool, stop_after_posts: Optional[int], 
                           stop_unit: str, stop_every: Optional[int], resume_after: Optional[int], resume_unit: str, 
                           silent_mode: bool, selected_groups: Optional[List[str]], selected_accounts: Optional[List[str]], 
                           attachments: Optional[List[str]], auto_reply_enabled: bool) -> None:
        accounts = self.db.get_accounts(limit=10, offset=0)  # Lazy Loading
        if selected_accounts:
            accounts = [acc for acc in accounts if acc[0] in selected_accounts]
        if not accounts:
            self._log("No accounts available", "Warning")
            self.statusUpdated.emit("No accounts available")
            return
        posted_groups = set()
        per_account_dict = {}
        if per_account_content:
            for line in self._sanitize_input(per_account_content).strip().splitlines():
                parts = line.split("|")
                if len(parts) >= 2:
                    per_account_dict[self._sanitize_input(parts[0])] = self._sanitize_input(parts[1])
        total = len(accounts) * (len(selected_groups) if selected_groups else 1)
        tasks = []
        custom_scripts = self.config.get("custom_scripts", [])
        for i, account in enumerate(accounts):
            if self.stop_flag:
                break
            fb_id = self._sanitize_input(account[0])
            groups = [(g[2], g[3], g[4]) for g in self.db.get_groups(fb_id) if not selected_groups or g[2] in selected_groups]
            final_content = per_account_dict.get(fb_id, global_content if global_content else content)
            final_content = self._sanitize_input(final_content)
            if spin_content_flag:
                final_content = spin_content(final_content, self.config, lambda msg: self.statusUpdated.emit(msg))
            if custom_scripts and random.random() < 0.5:
                final_content += " " + random.choice(custom_scripts)
            chrome_options = self._get_chrome_options(i, mobile_view=True, visible=not silent_mode)
            if "Graph API" in tech and account[9]:
                task = asyncio.create_task(self.post_with_graph_api(
                    fb_id, account[4], groups, final_content, target, allow_duplicates, posted_groups, 
                    timer, random_time, stop_after_posts, stop_unit, stop_every, resume_after, resume_unit, attachments
                ))
            else:
                task = asyncio.create_task(self.post_with_selenium(
                    fb_id, account[5], groups, final_content, target, allow_duplicates, posted_groups, 
                    timer, random_time, stop_after_posts, stop_unit, stop_every, resume_after, resume_unit, 
                    silent_mode, attachments, auto_reply_enabled
                ))
            tasks.append(task)
            self.progressUpdated.emit(i + 1, total)
        results = await asyncio.gather(*tasks, return_exceptions=True)
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                self._log(f"Task failed for account {accounts[i][0]}: {str(result)}", "Error", accounts[i][0])

    async def post_with_selenium(self, account_id: str, cookies: Optional[str], groups: List[tuple], content: str, 
                                target: str, allow_duplicates: bool, posted_groups: set, timer: Optional[float], 
                                random_time: bool, stop_after_posts: Optional[int], stop_unit: str, stop_every: Optional[int], 
                                resume_after: Optional[int], resume_unit: str, silent_mode: bool, 
                                attachments: Optional[List[str]], auto_reply_enabled: bool) -> None:
        driver = None
        try:
            chrome_options = self._get_chrome_options(0, mobile_view=True, visible=not silent_mode)
            driver = self.session_manager.get_driver(account_id, chrome_options=chrome_options)
            if not await self._verify_cookies(driver, cookies, account_id):
                return
            post_count = 0
            for group_id, group_name, _ in groups:
                group_id = self._sanitize_input(group_id)
                group_name = self._sanitize_input(group_name)
                if self.stop_flag or (stop_after_posts and stop_unit == "Posts" and post_count >= stop_after_posts):
                    break
                if not allow_duplicates and group_id in posted_groups:
                    continue
                driver.get(f"https://www.facebook.com/groups/{group_id}")
                await asyncio.sleep(random.uniform(1, 2))
                post_box = WebDriverWait(driver, 10).until(EC.presence_of_element_located((By.XPATH, "//div[@aria-label='Write something...']")))
                post_box.send_keys(content)
                if attachments:
                    for attachment in attachments:
                        if attachment.endswith(('.jpg', '.jpeg', '.png', '.mp4', '.avi')) and os.path.exists(attachment):
                            driver.find_element(By.XPATH, "//input[@type='file']").send_keys(attachment)
                            await asyncio.sleep(1)
                post_button = WebDriverWait(driver, 10).until(EC.element_to_be_clickable((By.XPATH, "//div[@aria-label='Post']")))
                post_button.click()
                posted_groups.add(group_id)
                self.posted_count += 1
                self._log(f"Posted: {content[:50]}...", "Info", account_id, group_id)
                if not silent_mode:
                    self.statusUpdated.emit(f"Posted to {group_name} with {account_id} via Selenium")
                await asyncio.sleep(2)
                post_elements = driver.find_elements(By.XPATH, "//a[contains(@href, '/posts/')]")
                post_url = post_elements[-1].get_attribute("href") if post_elements else None
                if post_url and auto_reply_enabled:
                    self._log(f"Auto-reply enabled for post {post_url}", "Info", account_id, group_id)
                    asyncio.create_task(self.auto_interact_with_comments(account_id, post_url, cookies))
                post_count += 1
                if stop_every and stop_unit == "Posts" and post_count % stop_every == 0 and resume_after:
                    await asyncio.sleep(self._convert_time(resume_after, resume_unit))
                await asyncio.sleep(random.uniform(max(2, delay - 1), delay + 1) if not random_time else random.uniform(2, timer or 10))
        except Exception as e:
            error_message = f"Error in post_with_selenium: {str(e)}\n{traceback.format_exc()}"
            self._log(error_message, "Error", account_id)
            self.statusUpdated.emit(f"Error: {str(e)}")
            if QApplication.instance():
                QMessageBox.critical(None, "Error", f"Selenium posting failed: {str(e)}")
        finally:
            if driver:
                self.session_manager.close_driver(account_id)

    async def post_with_graph_api(self, account_id: str, access_token: str, groups: List[tuple], content: str, 
                                 target: str, allow_duplicates: bool, posted_groups: set, timer: Optional[float], 
                                 random_time: bool, stop_after_posts: Optional[int], stop_unit: str, stop_every: Optional[int], 
                                 resume_after: Optional[int], resume_unit: str, attachments: Optional[List[str]]) -> None:
        try:
            access_token = self._sanitize_input(access_token)
            response = requests.get(f"https://graph.facebook.com/me?access_token={access_token}", timeout=5)
            if response.status_code != 200:
                raise ValueError(f"Invalid access token: {response.json().get('error', 'Unknown error')}")
            post_count = 0
            for group_id, group_name, _ in groups:
                group_id = self._sanitize_input(group_id)
                group_name = self._sanitize_input(group_name)
                if self.stop_flag or (stop_after_posts and stop_unit == "Posts" and post_count >= stop_after_posts):
                    break
                if not allow_duplicates and group_id in posted_groups:
                    continue
                url = f"https://graph.facebook.com/v20.0/{group_id}/feed"
                params = {"access_token": access_token, "message": content}
                files = {}
                if attachments:
                    for i, attachment in enumerate(attachments):
                        if attachment.endswith(('.jpg', '.jpeg', '.png')) and os.path.exists(attachment):
                            files[f'source{i}'] = (os.path.basename(attachment), open(attachment, 'rb'), 'image/jpeg')
                        elif attachment.endswith(('.mp4', '.avi')) and os.path.exists(attachment):
                            files[f'source{i}'] = (os.path.basename(attachment), open(attachment, 'rb'), 'video/mp4')
                response = requests.post(url, data=params, files=files if files else None, timeout=10)
                for _, file_obj in files.items():
                    file_obj.close()
                if response.status_code == 200 and "id" in response.json():
                    posted_groups.add(group_id)
                    self.posted_count += 1
                    self._log(f"Posted via Graph API: {content[:50]}...", "Info", account_id, group_id)
                    self.statusUpdated.emit(f"Posted to {group_name} with {account_id} via Graph API")
                    post_count += 1
                    if stop_every and stop_unit == "Posts" and post_count % stop_every == 0 and resume_after:
                        await asyncio.sleep(self._convert_time(resume_after, resume_unit))
                else:
                    self._log(f"Failed via Graph API: {response.json().get('error', 'Unknown Error')}", "Error", account_id, group_id)
                await asyncio.sleep(random.uniform(max(2, delay - 1), delay + 1) if not random_time else random.uniform(2, timer or 10))
        except Exception as e:
            error_message = f"Error in post_with_graph_api: {str(e)}\n{traceback.format_exc()}"
            self._log(error_message, "Error", account_id)
            self.statusUpdated.emit(f"Error: {str(e)}")
            if QApplication.instance():
                QMessageBox.critical(None, "Error", f"Graph API posting failed: {str(e)}")

    async def auto_interact_with_comments(self, account_id: str, post_url: str, cookies: str, 
                                         max_checks: int = 10, check_interval: int = 300) -> None:
        driver = None
        try:
            chrome_options = self._get_chrome_options(0, mobile_view=True, visible=False)
            driver = self.session_manager.get_driver(account_id, chrome_options=chrome_options)
            if not await self._verify_cookies(driver, cookies, account_id):
                return
            keywords_responses = {
                "رقم": f"للتواصل والاستفسار: {self.config.get('phone_number', '01225398839')}",
                "تليفون": f"للتواصل والاستفسار: {self.config.get('phone_number', '01225398839')}",
                "هاتف": f"للتواصل والاستفسار: {self.config.get('phone_number', '01225398839')}",
                "اتصال": f"للتواصل والاستفسار: {self.config.get('phone_number', '01225398839')}",
                "تواصل": f"للتواصل والاستفسار: {self.config.get('phone_number', '01225398839')}",
                "مواعيد": f"يرجى الاتصال على {self.config.get('phone_number', '01225398839')} لمعرفة المواعيد",
                "السلام عليكم": f"وعليكم السلام! للتواصل: {self.config.get('phone_number', '01225398839')}"
            }
            default_response = random.choice(self.config.get("custom_scripts", ["شكرًا على تفاعلك! للتواصل: 01225398839"]))
            responded_comments = set()
            responded_likes = set()
            for _ in range(max_checks):
                if self.stop_flag:
                    break
                driver.get(post_url)
                await asyncio.sleep(random.uniform(2, 4))
                like_elements = driver.find_elements(By.XPATH, "//span[contains(text(), 'Like')]//ancestor::a[@role='button']")
                for like_elem in like_elements[:5]:
                    user_id = self._sanitize_input(like_elem.get_attribute("href").split("id=")[-1] if "id=" in like_elem.get_attribute("href") else like_elem.get_attribute("href").split("/")[-2])
                    if user_id not in responded_likes:
                        like_elem.click()
                        await asyncio.sleep(1)
                        comment_box = WebDriverWait(driver, 10).until(EC.presence_of_element_located((By.XPATH, "//div[@aria-label='Write a comment...']")))
                        comment_box.send_keys(default_response)
                        driver.find_element(By.XPATH, "//div[@aria-label='Press Enter to post']").click()
                        self._log(f"Auto-liked and replied to like by {user_id}", "Info", account_id, post_url)
                        responded_likes.add(user_id)
                        await asyncio.sleep(1)
                comment_elements = driver.find_elements(By.XPATH, "//div[@data-visualcompletion='ignore-dynamic']//div[@role='article']")
                for comment in comment_elements[:5]:
                    comment_text = self._sanitize_input(comment.text.lower())
                    user_elements = comment.find_elements(By.XPATH, ".//a[@role='link']")
                    if not user_elements:
                        continue
                    user_id = self._sanitize_input(user_elements[0].get_attribute("href").split("id=")[-1] if "id=" in user_elements[0].get_attribute("href") else user_elements[0].get_attribute("href").split("/")[-2])
                    comment_id = f"{user_id}_{comment_text[:20]}"
                    if comment_id not in responded_comments:
                        like_button = comment.find_element(By.XPATH, ".//span[contains(text(), 'Like')]")
                        like_button.click()
                        response = default_response
                        for keyword, reply in keywords_responses.items():
                            if keyword in comment_text:
                                response = reply
                                break
                        reply_box = comment.find_element(By.XPATH, ".//div[@aria-label='Write a reply...']")
                        reply_box.send_keys(response)
                        driver.find_element(By.XPATH, ".//div[@aria-label='Press Enter to post']").click()
                        self._log(f"Auto-liked and replied to comment by {user_id}", "Info", account_id, post_url)
                        responded_comments.add(comment_id)
                        await asyncio.sleep(1)
                await asyncio.sleep(check_interval)
        except Exception as e:
            error_message = f"Error in auto_interact_with_comments: {str(e)}\n{traceback.format_exc()}"
            self._log(error_message, "Error", account_id)
            self.statusUpdated.emit(f"Error: {str(e)}")
            if QApplication.instance():
                QMessageBox.critical(None, "Error", f"Auto-interaction failed: {str(e)}")
        finally:
            if driver:
                self.session_manager.close_driver(account_id)

    def stop_posting(self) -> None:
        self.stop_flag = True
        if self.scheduler_task and not self.scheduler_task.done():
            self.scheduler_task.cancel()
        self._log("Posting stopped manually", "Info")
        self.statusUpdated.emit("Posting stopped")
        if QApplication.instance():
            QMetaObject.invokeMethod(self.app.ui if hasattr(self.app, 'ui') else None, 
                                    "show_message", Qt.QueuedConnection, 
                                    Q_ARG(str, "Success"), Q_ARG(str, "Posting stopped"), 
                                    Q_ARG(str, "Information"))

    def attach_media(self) -> Optional[List[str]]:
        try:
            usage = shutil.disk_usage(os.path.dirname(os.path.abspath(__file__)))
            if usage.free < 1024 * 1024:
                raise RuntimeError("Insufficient disk space")
            file_dialog = QFileDialog()
            attachments, _ = file_dialog.getOpenFileNames(
                self.app.ui if hasattr(self.app, 'ui') else None, 
                "Select Media Files", "", "Image Files (*.jpg *.jpeg *.png);;Video Files (*.mp4 *.avi)"
            )
            if attachments:
                self._log(f"Selected {len(attachments)} media files", "Info")
                self.statusUpdated.emit(f"Selected {len(attachments)} media files")
                return attachments
            self._log("No media files selected", "Warning")
            self.statusUpdated.emit("No media files selected")
            return None
        except Exception as e:
            error_message = f"Error attaching media: {str(e)}\n{traceback.format_exc()}"
            self._log(error_message, "Error")
            self.statusUpdated.emit(f"Error attaching media: {str(e)}")
            if QApplication.instance():
                QMessageBox.critical(None, "Error", f"Media attachment failed: {str(e)}")
            return None

    def save_post(self, content: str, group_id: Optional[str] = None) -> None:
        try:
            usage = shutil.disk_usage(os.path.dirname(os.path.abspath(__file__)))
            if usage.free < 1024 * 1024:
                raise RuntimeError("Insufficient disk space")
            post_id = f"saved_{datetime.now().strftime('%Y%m%d%H%M%S')}"
            self.db.add_saved_post(post_id, None, self._sanitize_input(content))
            self._log(f"Saved post {content[:50]}...", "Info", action=group_id or "Posts")
            self.statusUpdated.emit(f"Saved post {content[:50]}...")
            if QApplication.instance():
                QMetaObject.invokeMethod(self.app.ui if hasattr(self.app, 'ui') else None, 
                                        "show_message", Qt.QueuedConnection, 
                                        Q_ARG(str, "Success"), Q_ARG(str, f"Saved post {content[:50]}..."), 
                                        Q_ARG(str, "Information"))
        except Exception as e:
            error_message = f"Error saving post: {str(e)}\n{traceback.format_exc()}"
            self._log(error_message, "Error")
            self.statusUpdated.emit(f"Error saving post: {str(e)}")
            if QApplication.instance():
                QMessageBox.critical(None, "Error", f"Post saving failed: {str(e)}")

    async def schedule_post(self, fb_id: str, content: str, time: str, group_id: Optional[str] = None, 
                           attachments: Optional[List[str]] = None) -> None:
        try:
            usage = shutil.disk_usage(os.path.dirname(os.path.abspath(__file__)))
            if usage.free < 1024 * 1024:
                raise RuntimeError("Insufficient disk space")
            time = self._sanitize_input(time.strip())
            if not re.match(r"^\d{2}:\d{2}$", time):
                self._log(f"Invalid time format: {time}", "Error", fb_id)
                self.statusUpdated.emit(f"Invalid time format: {time}")
                return
            self._backup_database()
            post_id = self.db.add_scheduled_post(
                self._sanitize_input(fb_id), self._sanitize_input(content), time, 
                group_id=self._sanitize_input(group_id), post_type="Text" if not attachments else "Media"
            )
            self._log(f"Scheduled post {post_id} at {time}", "Info", fb_id, group_id or "Scheduled Posts")
            self.statusUpdated.emit(f"Scheduled post {content[:50]}... at {time}")
            if QApplication.instance():
                QMetaObject.invokeMethod(self.app.ui if hasattr(self.app, 'ui') else None, 
                                        "show_message", Qt.QueuedConnection, 
                                        Q_ARG(str, "Success"), Q_ARG(str, f"Scheduled post at {time}"), 
                                        Q_ARG(str, "Information"))
        except Exception as e:
            error_message = f"Error scheduling post: {str(e)}\n{traceback.format_exc()}"
            self._log(error_message, "Error", fb_id)
            self.statusUpdated.emit(f"Error scheduling post: {str(e)}")
            if QApplication.instance():
                QMessageBox.critical(None, "Error", f"Post scheduling failed: {str(e)}")

    async def _verify_cookies(self, driver: webdriver.Chrome, cookies: str, account_id: str) -> bool:
        try:
            load_cookies(driver, cookies, lambda msg: self.statusUpdated.emit(msg))
            driver.get("https://www.facebook.com")
            await asyncio.sleep(2)
            if "login" in driver.current_url.lower() or predictive_ban_detection(driver, self.config, lambda msg: self.statusUpdated.emit(msg)):
                self.statusUpdated.emit(f"Re-authenticating {account_id} due to invalid cookies or ban")
                from account_manager import AccountManager
                account_manager = AccountManager(self.app, self.config, self.db, self.log_manager)
                account = self.db.get_account(account_id)
                if not account:
                    self._log(f"Account {account_id} not found", "Error", account_id)
                    return False
                chrome_options = self._get_chrome_options(0, mobile_view=True, visible=True)
                success = await account_manager.login_account(account_id, account[1], account[2], "Selenium", False, chrome_options, reauth=True)
                if not success:
                    self._log(f"Failed to re-authenticate {account_id}", "Error", account_id)
                    return False
                new_cookies = encrypt_data(json.dumps(driver.get_cookies()), self.config)
                self.db.update_account(account_id, cookies=new_cookies)
                return True
            return True
        except Exception as e:
            error_message = f"Error verifying cookies: {str(e)}\n{traceback.format_exc()}"
            self._log(error_message, "Error", account_id)
            return False

    def _convert_time(self, value: int, unit: str) -> int:
        try:
            if unit == "Minutes":
                return value * 60
            elif unit == "Hours":
                return value * 3600
            return value
        except Exception as e:
            self._log(f"Error converting time: {str(e)}\n{traceback.format_exc()}", "Error")
            return value

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
        async def start_task(self, coro):
            await coro
    class DummyConfig:
        def get(self, key, default=None):
            defaults = {
                "default_delay": 5,
                "max_retries": 3,
                "mobile_size": "360x640",
                "chrome_path": "drivers/chrome.exe",
                "chromedriver_path": "drivers/chromedriver.exe",
                "2captcha_api_key": "test_key",
                "custom_scripts": ["Test script"],
                "phone_number": "01225398839",
                "proxies": ["http://proxy1:port"],
                "auto_reply_enabled": True,
                "db_path": "database.db"
            }
            return defaults.get(key, default)
    class DummyDatabase:
        def get_accounts(self, limit=10, offset=0):
            return [("fb1", "pass", "email@example.com", None, None, json.dumps([]), "Logged In", None, 0, 1)]
        def add_scheduled_post(self, fb_id, content, time, group_id=None, post_type="Text"):
            print(f"Scheduled post for {fb_id} at {time}")
            return 1
        def get_scheduled_posts(self):
            return [(1, "fb1", "Test content", "00:00", "fb1", "group1", "Text", "Pending")]
        def update_scheduled_post_status(self, post_id, status):
            print(f"Updated post {post_id} to {status}")
        def add_saved_post(self, post_id, fb_id, content):
            print(f"Saved post {post_id}: {content}")
        def get_groups(self, fb_id):
            return [(1, "fb1", "group1", "Test Group", 0, "", "", "false", 100, "Active", "")]
        def get_account(self, fb_id):
            return ("fb1", "pass", "email@example.com", None, None, json.dumps([]), "Logged In", None, 0, 1)
        def update_account(self, fb_id, cookies=None):
            print(f"Updated account {fb_id} with new cookies")
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
                def get_cookies(self): return []
            return DummyDriver()
        def close_driver(self, account_id): pass
        def close_all_drivers(self): pass
        def rotate_proxy(self, session_id): return "http://proxy1:port"
    class DummyAccountManager:
        async def login_account(self, fb_id, password, email, tech, headless, chrome_options, reauth=False):
            print(f"Logged in {fb_id}")
            return True
    dummy_app = DummyApp()
    post_manager = PostManager(dummy_app, DummyDatabase(), DummySessionManager(), DummyConfig(), DummyLogManager())
    asyncio.run(post_manager.post_all_content(content="Test post", schedule_times="00:00"))
    sys.exit(app.exec_())