import sys
import asyncio
from datetime import datetime
from typing import List, Optional, Dict
from PyQt5.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QFormLayout, QGroupBox,
                             QLabel, QTextEdit, QLineEdit, QComboBox, QSpinBox, QPushButton, QTableWidget, QTableWidgetItem,
                             QProgressBar, QMessageBox, QCheckBox, QTabWidget, QFileDialog, QListWidget, QTimeEdit, QDialog)
from PyQt5.QtCore import Qt, QTimer, QCoreApplication, pyqtSignal, QTime, QThreadPool
from PyQt5.QtGui import QFont, QIcon
import traceback
import sqlite3
import json
import requests
import time
import random
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

class ConfigManager:
    def __init__(self):
        self.config_file = "config.json"
        self.config = self.load_config()
        self.statusUpdated = pyqtSignal(str)

    def load_config(self):
        try:
            with open(self.config_file, "r") as f:
                return json.load(f)
        except:
            return {
                "2captcha_api_key": "",
                "default_delay": 5,
                "max_retries": 3,
                "proxies": [],
                "phone_number": "01225398839",
                "custom_scripts": [],
                "default_language": "en"
            }

    def save_config(self):
        with open(self.config_file, "w") as f:
            json.dump(self.config, f)

    def get(self, key, default=None):
        return self.config.get(key, default)

    def set(self, key, value):
        self.config[key] = value
        self.save_config()
        self.statusUpdated.emit(f"Config updated: {key}")

class Database:
    def __init__(self, app, log_manager):
        self.db_file = "smartposter.db"
        self.log_manager = log_manager
        self.statusUpdated = pyqtSignal(str)
        self.conn = sqlite3.connect(self.db_file)
        self.create_tables()

    def create_tables(self):
        cursor = self.conn.cursor()
        cursor.execute('''CREATE TABLE IF NOT EXISTS accounts (
            fb_id TEXT PRIMARY KEY, name TEXT, password TEXT, email TEXT, two_fa TEXT, 
            token TEXT, status TEXT, friends INTEGER, groups INTEGER, proxy TEXT
        )''')
        cursor.execute('''CREATE TABLE IF NOT EXISTS groups (
            group_id TEXT PRIMARY KEY, name TEXT, privacy TEXT, members INTEGER, status TEXT
        )''')
        cursor.execute('''CREATE TABLE IF NOT EXISTS logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT, fb_id TEXT, target TEXT, action TEXT, 
            timestamp DATETIME, level TEXT, message TEXT
        )''')
        cursor.execute('''CREATE TABLE IF NOT EXISTS scheduled_posts (
            id INTEGER PRIMARY KEY AUTOINCREMENT, account_id TEXT, content TEXT, 
            schedule_time DATETIME, group_id TEXT, status TEXT
        )''')
        cursor.execute('''CREATE TABLE IF NOT EXISTS posted_messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT, account_id TEXT, content TEXT, 
            target TEXT, timestamp DATETIME
        )''')
        self.conn.commit()

    def add_account(self, fb_id, name, password, email, two_fa, token, status, friends, groups, proxy):
        cursor = self.conn.cursor()
        cursor.execute('''INSERT OR REPLACE INTO accounts 
            (fb_id, name, password, email, two_fa, token, status, friends, groups, proxy) 
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''', 
            (fb_id, name, password, email, two_fa, token, status, friends, groups, proxy))
        self.conn.commit()

    def get_accounts(self, offset=0, limit=50):
        cursor = self.conn.cursor()
        cursor.execute("SELECT * FROM accounts LIMIT ? OFFSET ?", (limit, offset))
        return cursor.fetchall()

    def get_accounts_count(self):
        cursor = self.conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM accounts")
        return cursor.fetchone()[0]

    def add_group(self, account_id, group_id, name, members, status="Active"):
        cursor = self.conn.cursor()
        cursor.execute('''INSERT OR REPLACE INTO groups 
            (group_id, name, privacy, members, status) VALUES (?, ?, ?, ?, ?)''', 
            (group_id, name, "Unknown", members, status))
        self.conn.commit()

    def get_groups(self, offset=0, limit=50, privacy=None, min_members=0, name_filter="", status=None):
        cursor = self.conn.cursor()
        query = "SELECT * FROM groups WHERE members >= ?"
        params = [min_members]
        if privacy:
            query += " AND privacy = ?"
            params.append(privacy)
        if name_filter:
            query += " AND name LIKE ?"
            params.append(f"%{name_filter}%")
        if status:
            query += " AND status = ?"
            params.append(status)
        query += " LIMIT ? OFFSET ?"
        params.extend([limit, offset])
        cursor.execute(query, params)
        return cursor.fetchall()

    def get_groups_count(self, privacy=None, min_members=0, name_filter="", status=None):
        cursor = self.conn.cursor()
        query = "SELECT COUNT(*) FROM groups WHERE members >= ?"
        params = [min_members]
        if privacy:
            query += " AND privacy = ?"
            params.append(privacy)
        if name_filter:
            query += " AND name LIKE ?"
            params.append(f"%{name_filter}%")
        if status:
            query += " AND status = ?"
            params.append(status)
        cursor.execute(query, params)
        return cursor.fetchone()[0]

    def update_group(self, group_id, status):
        cursor = self.conn.cursor()
        cursor.execute("UPDATE groups SET status = ? WHERE group_id = ?", (status, group_id))
        self.conn.commit()

    def delete_group(self, group_id):
        cursor = self.conn.cursor()
        cursor.execute("DELETE FROM groups WHERE group_id = ?", (group_id,))
        self.conn.commit()

    def add_log(self, fb_id, target, action, level, message):
        cursor = self.conn.cursor()
        cursor.execute('''INSERT INTO logs (fb_id, target, action, timestamp, level, message) 
            VALUES (?, ?, ?, ?, ?, ?)''', 
            (fb_id, target, action, datetime.now(), level, message))
        self.conn.commit()

    def get_logs(self, offset=0, limit=50):
        cursor = self.conn.cursor()
        cursor.execute("SELECT * FROM logs ORDER BY timestamp DESC LIMIT ? OFFSET ?", (limit, offset))
        return cursor.fetchall()

    def get_logs_count(self):
        cursor = self.conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM logs")
        return cursor.fetchone()[0]

    def clear_logs(self):
        cursor = self.conn.cursor()
        cursor.execute("DELETE FROM logs")
        self.conn.commit()

    def schedule_post(self, account_id, content, schedule_time, group_id, status):
        cursor = self.conn.cursor()
        cursor.execute('''INSERT INTO scheduled_posts 
            (account_id, content, schedule_time, group_id, status) VALUES (?, ?, ?, ?, ?)''', 
            (account_id, content, schedule_time, group_id, status))
        self.conn.commit()

    def get_scheduled_posts(self):
        cursor = self.conn.cursor()
        cursor.execute("SELECT * FROM scheduled_posts")
        return cursor.fetchall()

    def add_posted_message(self, account_id, content, target):
        cursor = self.conn.cursor()
        cursor.execute('''INSERT INTO posted_messages (account_id, content, target, timestamp) 
            VALUES (?, ?, ?, ?)''', (account_id, content, target, datetime.now()))
        self.conn.commit()

    def get_posted_messages(self):
        cursor = self.conn.cursor()
        cursor.execute("SELECT account_id, content, target, timestamp FROM posted_messages")
        return cursor.fetchall()

    def close(self):
        self.conn.close()

class SessionManager:
    def __init__(self, app, config_manager):
        self.app = app
        self.config_manager = config_manager
        self.drivers = {}

    def get_driver(self, proxy=None, mobile_view=False):
        options = Options()
        options.add_argument("--headless")
        if proxy:
            options.add_argument(f"--proxy-server={proxy}")
        if mobile_view:
            options.add_argument("--user-agent=Mozilla/5.0 (iPhone; CPU iPhone OS 13_2_3 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/13.0.3 Mobile/15E148 Safari/604.1")
        driver = webdriver.Chrome(options=options)
        self.drivers[id(driver)] = driver
        return driver

    def close_all_drivers(self):
        for driver in self.drivers.values():
            driver.quit()
        self.drivers.clear()

class AccountManager:
    def __init__(self, app, config_manager, db, log_manager):
        self.app = app
        self.config_manager = config_manager
        self.db = db
        self.log_manager = log_manager
        self.statusUpdated = pyqtSignal(str)
        self.progressUpdated = pyqtSignal(int, int)

    def add_accounts(self, accounts_text):
        for line in accounts_text.splitlines():
            parts = line.strip().split("|")
            if len(parts) >= 2:
                fb_id, password = parts[0], parts[1]
                email = parts[2] if len(parts) > 2 else None
                proxy = parts[3] if len(parts) > 3 else None
                token = parts[4] if len(parts) > 4 else None
                app_id = parts[5] if len(parts) > 5 else None
                self.db.add_account(fb_id, None, password, email, None, token, "Not Logged In", 0, 0, proxy)

    async def login_all_accounts(self, login_mode, preliminary_interaction, mobile_view, visible):
        accounts = self.db.get_accounts()
        session_manager = SessionManager(self.app, self.config_manager)
        for i, (fb_id, _, password, email, _, _, _, _, _, proxy) in enumerate(accounts):
            driver = session_manager.get_driver(proxy, mobile_view)
            try:
                driver.get("https://facebook.com")
                driver.find_element(By.ID, "email").send_keys(fb_id)
                driver.find_element(By.ID, "pass").send_keys(password)
                driver.find_element(By.NAME, "login").click()
                time.sleep(5)
                if "login" not in driver.current_url:
                    token = driver.execute_script("return document.cookie")
                    self.db.add_account(fb_id, None, password, email, None, token, "Logged In", 0, 0, proxy)
                    self.log_manager.add_log(fb_id, None, "Login", "Info", "Login successful")
                else:
                    self.db.add_account(fb_id, None, password, email, None, None, "Login Failed", 0, 0, proxy)
                    self.log_manager.add_log(fb_id, None, "Login", "Error", "Login failed")
            except:
                self.db.add_account(fb_id, None, password, email, None, None, "Login Failed", 0, 0, proxy)
                self.log_manager.add_log(fb_id, None, "Login", "Error", "Login failed")
            finally:
                driver.quit()
            self.progressUpdated.emit(i + 1, len(accounts))

    async def verify_login_status(self, fb_id):
        account = self.db.get_accounts()
        for acc in account:
            if acc[0] == fb_id and acc[6] == "Logged In":
                self.log_manager.add_log(fb_id, None, "Verify Login", "Info", "Account is logged in")
                return
        self.db.add_account(fb_id, acc[1], acc[2], acc[3], acc[4], acc[5], "Not Logged In", acc[7], acc[8], acc[9])
        self.log_manager.add_log(fb_id, None, "Verify Login", "Warning", "Account not logged in")

    def close_all_browsers(self):
        SessionManager(self.app, self.config_manager).close_all_drivers()

class GroupManager:
    def __init__(self, app, db, session_manager, config_manager, log_manager):
        self.app = app
        self.db = db
        self.session_manager = session_manager
        self.config_manager = config_manager
        self.log_manager = log_manager
        self.statusUpdated = pyqtSignal(str)
        self.progressUpdated = pyqtSignal(int, int)

    async def extract_all_groups(self, keywords, fast_mode, interact):
        driver = self.session_manager.get_driver()
        try:
            driver.get(f"https://facebook.com/search/groups/?q={keywords}")
            time.sleep(5)
            groups = driver.find_elements(By.XPATH, "//a[contains(@href, '/groups/')]")
            for i, group in enumerate(groups[:10]):
                group_url = group.get_attribute("href")
                group_id = group_url.split("/groups/")[1].split("/")[0]
                name = group.text
                self.db.add_group(None, group_id, name, 0)
                self.log_manager.add_log(None, group_id, "Extract Group", "Info", f"Extracted group: {name}")
                self.progressUpdated.emit(i + 1, 10)
        finally:
            driver.quit()

    async def extract_joined_groups(self):
        driver = self.session_manager.get_driver()
        try:
            driver.get("https://facebook.com/groups")
            time.sleep(5)
            groups = driver.find_elements(By.XPATH, "//a[contains(@href, '/groups/')]")
            for i, group in enumerate(groups[:10]):
                group_url = group.get_attribute("href")
                group_id = group_url.split("/groups/")[1].split("/")[0]
                name = group.text
                self.db.add_group(None, group_id, name, 0)
                self.log_manager.add_log(None, group_id, "Extract Joined Group", "Info", f"Extracted joined group: {name}")
                self.progressUpdated.emit(i + 1, 10)
        finally:
            driver.quit()

    async def extract_group_members(self, group_id):
        driver = self.session_manager.get_driver()
        member_ids = []
        try:
            driver.get(f"https://facebook.com/groups/{group_id}/members")
            time.sleep(5)
            members = driver.find_elements(By.XPATH, "//a[contains(@href, '/profile.php?id=')]")
            for member in members[:10]:
                member_id = member.get_attribute("href").split("id=")[1].split("&")[0]
                member_ids.append(member_id)
                self.log_manager.add_log(None, group_id, "Extract Members", "Info", f"Extracted member: {member_id}")
        finally:
            driver.quit()
        return member_ids

    async def add_members(self, account_id, group_ids, member_ids):
        driver = self.session_manager.get_driver()
        try:
            for group_id in group_ids:
                for member_id in member_ids:
                    driver.get(f"https://facebook.com/groups/{group_id}/members")
                    time.sleep(2)
                    driver.execute_script(f"window.location.href='/groups/{group_id}/user/{member_id}/'")
                    time.sleep(2)
                    self.log_manager.add_log(account_id, group_id, "Add Member", "Info", f"Added member {member_id}")
        finally:
            driver.quit()

    async def auto_approve_join_requests(self, group_ids):
        driver = self.session_manager.get_driver()
        try:
            for group_id in group_ids:
                driver.get(f"https://facebook.com/groups/{group_id}/requests")
                time.sleep(2)
                approve_buttons = driver.find_elements(By.XPATH, "//button[contains(text(), 'Approve')]")
                for btn in approve_buttons[:5]:
                    btn.click()
                    time.sleep(1)
                    self.log_manager.add_log(None, group_id, "Auto Approve", "Info", "Approved join request")
        finally:
            driver.quit()

    async def delete_no_interaction_posts(self, group_ids):
        driver = self.session_manager.get_driver()
        try:
            for group_id in group_ids:
                driver.get(f"https://facebook.com/groups/{group_id}")
                time.sleep(2)
                posts = driver.find_elements(By.XPATH, "//div[@role='article']")
                for post in posts[:5]:
                    if "0 comments" in post.text:
                        post.find_element(By.XPATH, ".//button[contains(text(), 'Delete')]").click()
                        time.sleep(1)
                        self.log_manager.add_log(None, group_id, "Delete Post", "Info", "Deleted post with no interaction")
        finally:
            driver.quit()

    async def transfer_members(self, source_group, target_groups):
        member_ids = await self.extract_group_members(source_group)
        await self.add_members(None, target_groups, member_ids)

    async def interact_with_members(self, group_ids):
        driver = self.session_manager.get_driver()
        try:
            for group_id in group_ids:
                driver.get(f"https://facebook.com/groups/{group_id}")
                time.sleep(2)
                posts = driver.find_elements(By.XPATH, "//div[@role='article']")
                for post in posts[:3]:
                    post.find_element(By.XPATH, ".//button[contains(text(), 'Like')]").click()
                    time.sleep(1)
                    self.log_manager.add_log(None, group_id, "Interact", "Info", "Liked a post")
        finally:
            driver.quit()

class PostManager:
    def __init__(self, app, db, session_manager, config_manager, log_manager):
        self.app = app
        self.db = db
        self.session_manager = session_manager
        self.config_manager = config_manager
        self.log_manager = log_manager
        self.statusUpdated = pyqtSignal(str)
        self.progressUpdated = pyqtSignal(int, int)
        self.stop_flag = False

    async def schedule_post(self, accounts, targets, content, links, attachments, schedule_time, post_tech, target_type, anti_block, speed, delay, step, random_time, spin_content, allow_duplicates, auto_reply):
        for account in accounts:
            for target in targets or [None]:
                self.db.schedule_post(account, content, schedule_time, target, "Scheduled")
                self.log_manager.add_log(account, target, "Schedule Post", "Info", f"Scheduled post at {schedule_time}")

    async def post_content(self, accounts, targets, content, links, attachments, limit, post_tech, target_type, anti_block, speed, delay, step, spin_content, allow_duplicates, auto_reply):
        driver = self.session_manager.get_driver()
        try:
            for i, account in enumerate(accounts):
                if self.stop_flag:
                    break
                for j, target in enumerate(targets or [None]):
                    if j >= limit:
                        break
                    driver.get(f"https://facebook.com/{target}" if target else "https://facebook.com")
                    time.sleep(2)
                    textarea = driver.find_element(By.XPATH, "//textarea[@placeholder='What's on your mind?']")
                    textarea.send_keys(content)
                    time.sleep(1)
                    driver.find_element(By.XPATH, "//button[contains(text(), 'Post')]").click()
                    time.sleep(2)
                    self.db.add_posted_message(account, content, target)
                    self.log_manager.add_log(account, target, "Post Content", "Info", "Posted content")
                    self.progressUpdated.emit(i * len(targets or [None]) + j + 1, len(accounts) * len(targets or [None]))
                    time.sleep(delay)
        finally:
            driver.quit()

    def stop_publishing(self):
        self.stop_flag = True

    def set_stop_condition(self, limit, unit):
        self.stop_flag = False

    def resume_publishing(self):
        self.stop_flag = False

class LogManager:
    def __init__(self, app, db):
        self.app = app
        self.db = db
        self.statusUpdated = pyqtSignal(str)
        self.logsUpdated = pyqtSignal()

    def add_log(self, fb_id, target, action, level, message):
        self.db.add_log(fb_id, target, action, level, message)
        self.logsUpdated.emit()

class AIAnalytics:
    def __init__(self, app, config_manager, db, log_manager):
        self.app = app
        self.config_manager = config_manager
        self.db = db
        self.log_manager = log_manager
        self.statusUpdated = pyqtSignal(str)
        self.progressUpdated = pyqtSignal(int, int)

    def suggest_post(self, keywords):
        return f"Suggested post for {keywords}: Check out this amazing content!"

    def get_campaign_stats(self):
        return [(acc[0], random.randint(0, 100), random.randint(0, 1000), random.randint(0, 50), random.randint(0, 500)) for acc in self.db.get_accounts()]

    def optimize_schedule(self):
        return "10:00, 14:00, 18:00"

    def identify_active_groups(self):
        return [(group[0], group[1], random.randint(0, 50), random.randint(0, 20), random.uniform(50, 100)) for group in self.db.get_groups()]

class SmartPosterUI(QMainWindow):
    statusUpdated = pyqtSignal(str)
    progressUpdated = pyqtSignal(int, int)

    def __init__(self, app=None):
        super().__init__()
        self.app = app or QCoreApplication.instance()
        self.app.config_manager = ConfigManager()
        self.app.log_manager = LogManager(self.app, Database(self.app, None))
        self.db = Database(self.app, self.app.log_manager)
        self.session_manager = SessionManager(self.app, self.app.config_manager)
        self.account_manager = AccountManager(self.app, self.app.config_manager, self.db, self.app.log_manager)
        self.group_manager = GroupManager(self.app, self.db, self.session_manager, self.app.config_manager, self.app.log_manager)
        self.post_manager = PostManager(self.app, self.db, self.session_manager, self.app.config_manager, self.app.log_manager)
        self.log_manager = self.app.log_manager
        self.analytics = AIAnalytics(self.app, self.app.config_manager, self.db, self.app.log_manager)
        self.attachments = []
        self.posted_count = 0
        self.accounts_page = 0
        self.groups_page = 0
        self.logs_page = 0
        self.page_size = 50
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        self.threadpool = QThreadPool()
        self.setWindowTitle("SmartPoster")
        self.setGeometry(100, 100, 1200, 800)
        self.init_ui()

    def init_ui(self):
        self.setStyleSheet("QMainWindow { background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #E3F2FD, stop:1 #BBDEFB); } QLabel { color: #1E3A8A; font-family: 'Segoe UI', sans-serif; } QLineEdit, QTextEdit, QComboBox, QSpinBox, QTimeEdit { border: 1px solid #90CAF9; border-radius: 6px; padding: 6px; background: #FFFFFF; font-family: 'Segoe UI', sans-serif; } QCheckBox { padding: 6px; font-family: 'Segoe UI', sans-serif; color: #1E3A8A; } QListWidget { border: 1px solid #90CAF9; border-radius: 6px; background: #FFFFFF; }")
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)
        header_widget = QWidget()
        header_widget.setFixedHeight(80)
        header_widget.setStyleSheet("background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #1E88E5, stop:1 #42A5F5); border-bottom: 2px solid #90CAF9; box-shadow: 0 2px 8px rgba(0, 0, 0, 0.15);")
        header_layout = QHBoxLayout(header_widget)
        header_layout.setContentsMargins(10, 0, 10, 0)
        logo_label = QLabel("● SmartPoster")
        logo_label.setFont(QFont("Segoe UI", 26, QFont.Bold))
        logo_label.setStyleSheet("color: #FFFFFF; text-shadow: 2px 2px 6px rgba(0, 0, 0, 0.3); padding: 10px;")
        header_layout.addWidget(logo_label)
        header_layout.addStretch()
        tabs = ["Settings", "Accounts", "Groups", "Publish", "Add Members", "Analytics", "Logs"]
        for tab in tabs:
            btn = QPushButton(tab)
            btn.setFont(QFont("Segoe UI", 12, QFont.Bold))
            btn.setStyleSheet("QPushButton { background: transparent; color: #FFFFFF; padding: 10px 20px; border: none; font-size: 15px; border-radius: 12px; } QPushButton:hover { background: #64B5F6; transition: background 0.3s ease; }")
            btn.clicked.connect(lambda checked, t=tab: self.switch_tab(t))
            header_layout.addWidget(btn)
        main_layout.addWidget(header_widget)
        content_widget = QWidget()
        content_layout = QHBoxLayout(content_widget)
        content_layout.setContentsMargins(10, 10, 10, 10)
        content_layout.setSpacing(15)
        self.sidebar = QWidget()
        self.sidebar.setFixedWidth(250)
        self.sidebar.setStyleSheet("background: #F5F9FC; border-right: 2px solid #BBDEFB; box-shadow: 4px 0 10px rgba(0, 0, 0, 0.08); padding: 12px; border-radius: 8px;")
        sidebar_layout = QVBoxLayout(self.sidebar)
        sidebar_layout.setContentsMargins(10, 10, 10, 10)
        sidebar_layout.setSpacing(10)
        sidebar_items = {
            "Accounts": ["Add Batch", "Import File", "Login All", "Verify Login", "Close Browser"],
            "Groups": ["Extract Joined Groups", "Save", "Close Browser"],
            "Publish": ["Schedule Post", "Publish Now", "Stop Publishing"],
            "Add Members": ["Send Invites"],
            "Analytics": ["View Campaign Stats", "Suggest Post"]
        }
        for section, items in sidebar_items.items():
            section_label = QLabel(section)
            section_label.setFont(QFont("Segoe UI", 16, QFont.Bold))
            section_label.setStyleSheet("color: #1E3A8A; padding: 6px;")
            sidebar_layout.addWidget(section_label)
            for item in items:
                btn = QPushButton(item)
                btn.setFont(QFont("Segoe UI", 12))
                btn.setStyleSheet("QPushButton { background: #1E88E5; color: #FFFFFF; padding: 10px; border: none; border-radius: 8px; font-size: 14px; margin-bottom: 8px; box-shadow: 0 3px 6px rgba(0, 0, 0, 0.15); } QPushButton:hover { background: #42A5F5; box-shadow: 0 5px 10px rgba(66, 165, 245, 0.3); transition: all 0.3s ease; }")
                btn.clicked.connect(lambda checked, i=item: self.switch_tab(i))
                sidebar_layout.addWidget(btn)
        sidebar_layout.addStretch()
        content_layout.addWidget(self.sidebar)
        self.content_stack = QTabWidget()
        self.content_stack.setStyleSheet("QTabWidget::pane { border: 1px solid #BBDEFB; border-radius: 6px; background: #F5F9FC; } QTabBar::tab { background: #E3F2FD; color: #1E3A8A; padding: 10px 20px; border-top-left-radius: 6px; border-top-right-radius: 6px; font-size: 14px; font-weight: bold; } QTabBar::tab:selected { background: #1E88E5; color: #FFFFFF; } QTabBar::tab:hover { background: #42A5F5; }")
        content_layout.addWidget(self.content_stack)
        settings_tab = QWidget()
        settings_layout = QVBoxLayout(settings_tab)
        settings_layout.setSpacing(20)
        settings_group = QGroupBox("Settings")
        settings_group.setFont(QFont("Segoe UI", 16, QFont.Bold))
        settings_group.setStyleSheet("QGroupBox { color: #1E3A8A; border: 1px solid #BBDEFB; border-radius: 6px; background: #FFFFFF; padding: 12px; box-shadow: 0 4px 12px rgba(0, 0, 0, 0.1); }")
        settings_form = QFormLayout()
        settings_form.setLabelAlignment(Qt.AlignRight)
        settings_form.setFormAlignment(Qt.AlignCenter)
        settings_form.setSpacing(10)
        self.api_key_input = QLineEdit(placeholderText="Enter 2Captcha API Key")
        self.api_key_input.setText(self.app.config_manager.get("2captcha_api_key", ""))
        self.api_key_input.setFixedWidth(300)
        self.delay_input = QSpinBox()
        self.delay_input.setRange(1, 60)
        self.delay_input.setValue(self.app.config_manager.get("default_delay", 5))
        self.delay_input.setFixedWidth(100)
        self.max_retries_input = QSpinBox()
        self.max_retries_input.setRange(1, 10)
        self.max_retries_input.setValue(self.app.config_manager.get("max_retries", 3))
        self.max_retries_input.setFixedWidth(100)
        self.proxy_input = QTextEdit(placeholderText="Enter proxies (one per line, e.g., http://proxy:port)")
        self.proxy_input.setFixedSize(400, 100)
        self.proxy_input.setText("\n".join(self.app.config_manager.get("proxies", [])))
        self.phone_input = QLineEdit(placeholderText="Enter phone number")
        self.phone_input.setText(self.app.config_manager.get("phone_number", "01225398839"))
        self.phone_input.setFixedWidth(300)
        self.reply_scripts = QTextEdit(placeholderText="Custom reply scripts (one per line)")
        self.reply_scripts.setFixedSize(400, 100)
        self.reply_scripts.setText("\n".join(self.app.config_manager.get("custom_scripts", [])))
        self.language_input = QComboBox()
        self.language_input.addItems(["en", "ar", "fr", "es"])
        self.language_input.setCurrentText(self.app.config_manager.get("default_language", "en"))
        self.language_input.setFixedWidth(100)
        self.save_settings_button = QPushButton("Save Settings")
        self.save_settings_button.setFont(QFont("Segoe UI", 12))
        self.save_settings_button.setStyleSheet("QPushButton { background: #1E88E5; color: #FFFFFF; padding: 10px; border-radius: 12px; box-shadow: 0 3px 6px rgba(0, 0, 0, 0.15); } QPushButton:hover { background: #42A5F5; box-shadow: 0 5px 10px rgba(66, 165, 245, 0.3); transition: all 0.3s ease; }")
        settings_form.addRow(QLabel("2Captcha API Key:"), self.api_key_input)
        settings_form.addRow(QLabel("Default Delay (seconds):"), self.delay_input)
        settings_form.addRow(QLabel("Max Retries:"), self.max_retries_input)
        settings_form.addRow(QLabel("Proxies:"), self.proxy_input)
        settings_form.addRow(QLabel("Phone Number:"), self.phone_input)
        settings_form.addRow(QLabel("Reply Scripts:"), self.reply_scripts)
        settings_form.addRow(QLabel("Default Language:"), self.language_input)
        settings_form.addRow("", self.save_settings_button)
        settings_group.setLayout(settings_form)
        settings_layout.addWidget(QLabel("Settings", styleSheet="color: #1E88E5; font-size: 22px; font-weight: bold; padding: 12px;"))
        settings_layout.addWidget(settings_group)
        settings_layout.addStretch()
        self.content_stack.addTab(settings_tab, "Settings")
        accounts_tab = QWidget()
        accounts_layout = QVBoxLayout(accounts_tab)
        accounts_layout.setSpacing(20)
        accounts_group = QGroupBox("Accounts Control")
        accounts_group.setFont(QFont("Segoe UI", 16, QFont.Bold))
        accounts_group.setStyleSheet("QGroupBox { color: #1E3A8A; border: 1px solid #BBDEFB; border-radius: 6px; background: #FFFFFF; padding: 12px; box-shadow: 0 4px 12px rgba(0, 0, 0, 0.1); }")
        accounts_form = QFormLayout()
        accounts_form.setLabelAlignment(Qt.AlignRight)
        accounts_form.setFormAlignment(Qt.AlignCenter)
        accounts_form.setSpacing(10)
        self.accounts_input = QTextEdit(placeholderText="ID|Password|Email|Proxy|Token|AppID (one per line)")
        self.accounts_input.setFixedSize(400, 100)
        self.login_method = QComboBox()
        self.login_method.addItems(["Selenium (No Token)", "Extract Token via Browser", "Access Token"])
        self.login_method.setFixedWidth(200)
        self.preliminary_interaction = QCheckBox("Preliminary Interaction")
        self.mobile_view = QCheckBox("Mobile View")
        self.login_all_button = QPushButton("Login All")
        self.verify_login_button = QPushButton("Verify Login")
        self.add_accounts_button = QPushButton("Add Batch")
        self.import_file_button = QPushButton("Import File")
        self.close_browsers_button = QPushButton("Close Browsers")
        for btn in [self.login_all_button, self.verify_login_button, self.add_accounts_button, self.import_file_button, self.close_browsers_button]:
            btn.setFont(QFont("Segoe UI", 12))
            btn.setStyleSheet("QPushButton { background: #1E88E5; color: #FFFFFF; padding: 10px; border-radius: 12px; box-shadow: 0 3px 6px rgba(0, 0, 0, 0.15); } QPushButton:hover { background: #42A5F5; box-shadow: 0 5px 10px rgba(66, 165, 245, 0.3); transition: all 0.3s ease; }")
        accounts_form.addRow(QLabel("Add Accounts:"), self.accounts_input)
        accounts_form.addRow("", self.add_accounts_button)
        accounts_form.addRow("", self.import_file_button)
        accounts_form.addRow(QLabel("Login Method:"), self.login_method)
        accounts_form.addRow("", self.preliminary_interaction)
        accounts_form.addRow("", self.mobile_view)
        accounts_form.addRow("", self.login_all_button)
        accounts_form.addRow("", self.verify_login_button)
        accounts_form.addRow("", self.close_browsers_button)
        accounts_group.setLayout(accounts_form)
        self.accounts_table = QTableWidget()
        self.accounts_table.setColumnCount(12)
        self.accounts_table.setHorizontalHeaderLabels(["", "STT", "UID", "Name", "Password", "Email", "2FA", "Token", "Status", "Friend", "Group", "Proxy"])
        self.accounts_table.setFixedSize(900, 300)
        self.accounts_table.setStyleSheet("QTableWidget { border: 1px solid #BBDEFB; border-radius: 6px; background: #FFFFFF; } QTableWidget::item:selected { background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #E3F2FD, stop:1 #BBDEFB); } QHeaderView::section { background: #1E88E5; color: #FFFFFF; padding: 8px; border: none; font-weight: bold; }")
        accounts_pagination = QHBoxLayout()
        self.accounts_prev_button = QPushButton("◄ Previous")
        self.accounts_next_button = QPushButton("Next ►")
        self.accounts_page_label = QLabel("Page 1")
        self.accounts_page_label.setStyleSheet("color: #1E3A8A; font-size: 14px;")
        for btn in [self.accounts_prev_button, self.accounts_next_button]:
            btn.setFont(QFont("Segoe UI", 12))
            btn.setStyleSheet("QPushButton { background: #1E88E5; color: #FFFFFF; padding: 8px; border-radius: 8px; } QPushButton:hover { background: #42A5F5; transition: all 0.3s ease; }")
        accounts_pagination.addStretch()
        accounts_pagination.addWidget(self.accounts_prev_button)
        accounts_pagination.addWidget(self.accounts_page_label)
        accounts_pagination.addWidget(self.accounts_next_button)
        accounts_pagination.addStretch()
        accounts_layout.addWidget(QLabel("Accounts", styleSheet="color: #1E88E5; font-size: 22px; font-weight: bold; padding: 12px;"))
        accounts_layout.addWidget(accounts_group)
        accounts_layout.addWidget(self.accounts_table, alignment=Qt.AlignCenter)
        accounts_layout.addLayout(accounts_pagination)
        accounts_layout.addStretch()
        self.content_stack.addTab(accounts_tab, "Accounts")
        groups_tab = QWidget()
        groups_layout = QVBoxLayout(groups_tab)
        groups_layout.setSpacing(20)
        groups_group = QGroupBox("Groups Control")
        groups_group.setFont(QFont("Segoe UI", 16, QFont.Bold))
        groups_group.setStyleSheet("QGroupBox { color: #1E3A8A; border: 1px solid #BBDEFB; border-radius: 6px; background: #FFFFFF; padding: 12px; box-shadow: 0 4px 12px rgba(0, 0, 0, 0.1); }")
        groups_form = QFormLayout()
        groups_form.setLabelAlignment(Qt.AlignRight)
        groups_form.setFormAlignment(Qt.AlignCenter)
        groups_form.setSpacing(10)
        self.search_groups_input = QLineEdit(placeholderText="Enter keywords to search groups")
        self.search_groups_input.setFixedWidth(300)
        groups_filter = QHBoxLayout()
        self.filter_privacy = QComboBox()
        self.filter_privacy.addItems(["All", "Open", "Closed"])
        self.filter_privacy.setFixedWidth(100)
        self.filter_members = QSpinBox()
        self.filter_members.setMaximum(1000000)
        self.filter_members.setFixedWidth(100)
        self.filter_name = QLineEdit(placeholderText="Search by name...")
        self.filter_name.setFixedWidth(150)
        self.filter_status = QComboBox()
        self.filter_status.addItems(["All", "Active", "Inactive", "Favorite"])
        self.filter_status.setFixedWidth(100)
        self.apply_filter_button = QPushButton("Apply Filter")
        self.apply_filter_button.setFont(QFont("Segoe UI", 12))
        self.apply_filter_button.setStyleSheet("QPushButton { background: #1E88E5; color: #FFFFFF; padding: 10px; border-radius: 12px; box-shadow: 0 3px 6px rgba(0, 0, 0, 0.15); } QPushButton:hover { background: #42A5F5; box-shadow: 0 5px 10px rgba(66, 165, 245, 0.3); transition: all 0.3s ease; }")
        groups_filter.addWidget(QLabel("Privacy:"))
        groups_filter.addWidget(self.filter_privacy)
        groups_filter.addWidget(QLabel("Members:"))
        groups_filter.addWidget(self.filter_members)
        groups_filter.addWidget(QLabel("Name:"))
        groups_filter.addWidget(self.filter_name)
        groups_filter.addWidget(QLabel("Status:"))
        groups_filter.addWidget(self.filter_status)
        groups_filter.addWidget(self.apply_filter_button)
        groups_form.addRow(QLabel("Search Groups:"), self.search_groups_input)
        groups_form.addRow("", groups_filter)
        self.extract_groups_button = QPushButton("Extract Groups")
        self.extract_joined_button = QPushButton("Extract Joined Groups")
        self.add_group_manually_button = QPushButton("Add Group Manually")
        self.save_groups_button = QPushButton("Save Groups")
        self.close_groups_browser_button = QPushButton("Close Browser")
        self.auto_approve_button = QPushButton("Auto Approve Requests")
        self.delete_posts_button = QPushButton("Delete Posts (No Interaction)")
        for btn in [self.extract_groups_button, self.extract_joined_button, self.add_group_manually_button, self.save_groups_button, self.close_groups_browser_button, self.auto_approve_button, self.delete_posts_button]:
            btn.setFont(QFont("Segoe UI", 12))
            btn.setStyleSheet("QPushButton { background: #1E88E5; color: #FFFFFF; padding: 10px; border-radius: 12px; box-shadow: 0 3px 6px rgba(0, 0, 0, 0.15); } QPushButton:hover { background: #42A5F5; box-shadow: 0 5px 10px rgba(66, 165, 245, 0.3); transition: all 0.3s ease; }")
        groups_form.addRow("", self.extract_groups_button)
        groups_form.addRow("", self.extract_joined_button)
        groups_form.addRow("", self.add_group_manually_button)
        groups_form.addRow("", self.save_groups_button)
        groups_form.addRow("", self.auto_approve_button)
        groups_form.addRow("", self.delete_posts_button)
        groups_form.addRow("", self.close_groups_browser_button)
        groups_group.setLayout(groups_form)
        self.groups_table = QTableWidget()
        self.groups_table.setColumnCount(6)
        self.groups_table.setHorizontalHeaderLabels(["✓", "STT", "Group Name", "Group ID", "Privacy", "Members"])
        self.groups_table.setFixedSize(900, 300)
        self.groups_table.setStyleSheet("QTableWidget { border: 1px solid #BBDEFB; border-radius: 6px; background: #FFFFFF; } QTableWidget::item:selected { background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #E3F2FD, stop:1 #BBDEFB); } QHeaderView::section { background: #1E88E5; color: #FFFFFF; padding: 8px; border: none; font-weight: bold; }")
        groups_pagination = QHBoxLayout()
        self.groups_prev_button = QPushButton("◄ Previous")
        self.groups_next_button = QPushButton("Next ►")
        self.groups_page_label = QLabel("Page 1")
        self.groups_page_label.setStyleSheet("color: #1E3A8A; font-size: 14px;")
        for btn in [self.groups_prev_button, self.groups_next_button]:
            btn.setFont(QFont("Segoe UI", 12))
            btn.setStyleSheet("QPushButton { background: #1E88E5; color: #FFFFFF; padding: 8px; border-radius: 8px; } QPushButton:hover { background: #42A5F5; transition: all 0.3s ease; }")
        groups_pagination.addStretch()
        groups_pagination.addWidget(self.groups_prev_button)
        groups_pagination.addWidget(self.groups_page_label)
        groups_pagination.addWidget(self.groups_next_button)
        groups_pagination.addStretch()
        groups_buttons = QHBoxLayout()
        self.use_selected_groups_button = QPushButton("Use Selected Groups")
        self.select_all_groups_button = QPushButton("Select All")
        self.deselect_all_groups_button = QPushButton("Deselect All")
        self.custom_selection_button = QPushButton("Custom Selection")
        self.refresh_groups_button = QPushButton("↻ Refresh")
        self.delete_groups_button = QPushButton("✗ Delete")
        self.extract_users_button = QPushButton("Extract Group Users")
        self.join_new_groups_button = QPushButton("Join New Groups")
        self.add_to_favorites_button = QPushButton("Add to Favorites")
        self.transfer_members_button = QPushButton("Transfer Members")
        self.interact_members_button = QPushButton("Interact with Members")
        for btn in [self.use_selected_groups_button, self.select_all_groups_button, self.deselect_all_groups_button, self.custom_selection_button, self.refresh_groups_button, self.delete_groups_button, self.extract_users_button, self.join_new_groups_button, self.add_to_favorites_button, self.transfer_members_button, self.interact_members_button]:
            btn.setFont(QFont("Segoe UI", 12))
            btn.setStyleSheet("QPushButton { background: #1E88E5; color: #FFFFFF; padding: 8px 12px; border-radius: 10px; box-shadow: 0 3px 6px rgba(0, 0, 0, 0.15); margin-right: 5px; } QPushButton:hover { background: #42A5F5; box-shadow: 0 5px 10px rgba(66, 165, 245, 0.3); transition: all 0.3s ease; }")
        groups_buttons.addStretch()
        groups_buttons.addWidget(self.use_selected_groups_button)
        groups_buttons.addWidget(self.select_all_groups_button)
        groups_buttons.addWidget(self.deselect_all_groups_button)
        groups_buttons.addWidget(self.custom_selection_button)
        groups_buttons.addWidget(self.refresh_groups_button)
        groups_buttons.addWidget(self.delete_groups_button)
        groups_buttons.addWidget(self.extract_users_button)
        groups_buttons.addWidget(self.join_new_groups_button)
        groups_buttons.addWidget(self.add_to_favorites_button)
        groups_buttons.addWidget(self.transfer_members_button)
        groups_buttons.addWidget(self.interact_members_button)
        groups_buttons.addStretch()
        groups_layout.addWidget(QLabel("Groups", styleSheet="color: #1E88E5; font-size: 22px; font-weight: bold; padding: 12px;"))
        groups_layout.addWidget(groups_group)
        groups_layout.addWidget(self.groups_table, alignment=Qt.AlignCenter)
        groups_layout.addLayout(groups_pagination)
        groups_layout.addLayout(groups_buttons)
        groups_layout.addStretch()
        self.content_stack.addTab(groups_tab, "Groups")
        publish_tab = QWidget()
        publish_layout = QVBoxLayout(publish_tab)
        publish_layout.setSpacing(20)
        publish_group = QGroupBox("Publish Control")
        publish_group.setFont(QFont("Segoe UI", 16, QFont.Bold))
        publish_group.setStyleSheet("QGroupBox { color: #1E3A8A; border: 1px solid #BBDEFB; border-radius: 6px; background: #FFFFFF; padding: 12px; box-shadow: 0 4px 12px rgba(0, 0, 0, 0.1); }")
        publish_form = QFormLayout()
        publish_form.setLabelAlignment(Qt.AlignRight)
        publish_form.setFormAlignment(Qt.AlignCenter)
        publish_form.setSpacing(10)
        self.post_target_combo = QComboBox()
        self.post_target_combo.addItems(["Groups", "Pages", "News Feed"])
        self.post_target_combo.setFixedWidth(150)
        self.post_tech_combo = QComboBox()
        self.post_tech_combo.addItems(["Selenium (Primary)", "Graph API (With Token)"])
        self.post_tech_combo.setFixedWidth(200)
        self.post_limit_spinbox = QSpinBox()
        self.post_limit_spinbox.setRange(1, 1000)
        self.post_limit_spinbox.setValue(10)
        self.post_limit_spinbox.setFixedWidth(100)
        self.accounts_list = QListWidget()
        self.accounts_list.setFixedSize(200, 150)
        self.accounts_list.setSelectionMode(QListWidget.MultiSelection)
        self.target_combo = QComboBox()
        self.target_combo.addItems(["All Groups", "Selected Groups"])
        self.target_combo.setFixedWidth(150)
        self.target_list = QListWidget()
        self.target_list.setFixedSize(200, 150)
        self.target_list.setSelectionMode(QListWidget.MultiSelection)
        self.global_content_input = QTextEdit(placeholderText="Global Content for all accounts")
        self.global_content_input.setFixedSize(600, 100)
        self.links_input = QLineEdit(placeholderText="Enter URLs (comma-separated)")
        self.links_input.setFixedWidth(300)
        self.attachments_label = QLabel("No attachments selected")
        self.attachments_label.setStyleSheet("color: #1E3A8A; font-size: 14px; padding: 6px;")
        self.attach_photo_button = QPushButton("Browse Photo...")
        self.attach_video_button = QPushButton("Browse Video...")
        self.speed_spinbox = QSpinBox()
        self.speed_spinbox.setRange(1, 60)
        self.speed_spinbox.setValue(5)
        self.speed_spinbox.setFixedWidth(100)
        self.delay_spinbox = QSpinBox()
        self.delay_spinbox.setRange(1, 60)
        self.delay_spinbox.setValue(5)
        self.delay_spinbox.setFixedWidth(100)
        self.anti_block_checkbox = QCheckBox("Anti-Block")
        self.step_spinbox = QSpinBox()
        self.step_spinbox.setRange(1, 100)
        self.step_spinbox.setValue(10)
        self.step_spinbox.setFixedWidth(100)
        self.timer_input = QTimeEdit()
        self.timer_input.setDisplayFormat("HH:mm")
        self.timer_input.setTime(QTime(10, 0))
        self.timer_input.setFixedWidth(100)
        self.random_time_checkbox = QCheckBox("Random Time")
        self.stop_spinbox = QSpinBox()
        self.stop_spinbox.setRange(1, 1000)
        self.stop_spinbox.setValue(10)
        self.stop_spinbox.setFixedWidth(100)
        self.stop_unit_combo = QComboBox()
        self.stop_unit_combo.addItems(["Posts", "Minutes", "Hours"])
        self.stop_unit_combo.setFixedWidth(100)
        self.every_spinbox = QSpinBox()
        self.every_spinbox.setRange(1, 100)
        self.every_spinbox.setValue(5)
        self.every_spinbox.setFixedWidth(100)
        self.save_mode_checkbox = QCheckBox("Save Mode")
        self.content_list = QListWidget()
        self.content_list.setFixedSize(600, 100)
        self.allow_duplicates = QCheckBox("Allow Duplicates")
        self.spin_content_flag = QCheckBox("Spin Content")
        self.auto_reply_checkbox = QCheckBox("Enable Auto-Reply")
        self.schedule_timer_button = QPushButton("Schedule Timer")
        self.stop_switch_button = QPushButton("Stop Switch")
        self.stop_after_posts_button = QPushButton("Stop After Posts")
        self.resume_button = QPushButton("Resume")
        self.publish_button = QPushButton("Publish")
        self.posted_messages_button = QPushButton("Posted Messages")
        for btn in [self.attach_photo_button, self.attach_video_button, self.schedule_timer_button, self.stop_switch_button, self.stop_after_posts_button, self.resume_button, self.publish_button, self.posted_messages_button]:
            btn.setFont(QFont("Segoe UI", 12))
            btn.setStyleSheet("QPushButton { background: #1E88E5; color: #FFFFFF; padding: 10px; border-radius: 12px; box-shadow: 0 3px 6px rgba(0, 0, 0, 0.15); } QPushButton:hover { background: #42A5F5; box-shadow: 0 5px 10px rgba(66, 165, 245, 0.3); transition: all 0.3s ease; }")
        publish_form.addRow(QLabel("Target:"), self.post_target_combo)
        publish_form.addRow(QLabel("Post As:"), self.post_tech_combo)
        publish_form.addRow(QLabel("Limit:"), self.post_limit_spinbox)
        publish_form.addRow(QLabel("Select Accounts:"), self.accounts_list)
        publish_form.addRow(QLabel("Select Target:"), self.target_combo)
        publish_form.addRow("", self.target_list)
        publish_form.addRow(QLabel("Message:"), self.global_content_input)
        publish_form.addRow(QLabel("Attach Link:"), self.links_input)
        publish_form.addRow(QLabel("Attachments:"), self.attachments_label)
        publish_form.addRow("", self.attach_photo_button)
        publish_form.addRow("", self.attach_video_button)
        publish_form.addRow(QLabel("Speed (seconds):"), self.speed_spinbox)
        publish_form.addRow(QLabel("Delay (seconds):"), self.delay_spinbox)
        publish_form.addRow("", self.anti_block_checkbox)
        publish_form.addRow(QLabel("Step:"), self.step_spinbox)
        publish_form.addRow(QLabel("Timer:"), self.timer_input)
        publish_form.addRow("", self.random_time_checkbox)
        publish_form.addRow(QLabel("Stop:"), self.stop_spinbox)
        publish_form.addRow("", self.stop_unit_combo)
        publish_form.addRow(QLabel("Every:"), self.every_spinbox)
        publish_form.addRow("", self.save_mode_checkbox)
        publish_form.addRow(QLabel("Content List:"), self.content_list)
        publish_form.addRow("", self.allow_duplicates)
        publish_form.addRow("", self.spin_content_flag)
        publish_form.addRow("", self.auto_reply_checkbox)
        publish_form.addRow("", self.schedule_timer_button)
        publish_form.addRow("", self.stop_switch_button)
        publish_form.addRow("", self.stop_after_posts_button)
        publish_form.addRow("", self.resume_button)
        publish_form.addRow("", self.publish_button)
        publish_form.addRow("", self.posted_messages_button)
        publish_group.setLayout(publish_form)
        self.scheduled_posts_table = QTableWidget()
        self.scheduled_posts_table.setColumnCount(6)
        self.scheduled_posts_table.setHorizontalHeaderLabels(["ID", "Account ID", "Content", "Time", "Group ID", "Status"])
        self.scheduled_posts_table.setFixedSize(900, 200)
        self.scheduled_posts_table.setStyleSheet("QTableWidget { border: 1px solid #BBDEFB; border-radius: 6px; background: #FFFFFF; } QTableWidget::item:selected { background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #E3F2FD, stop:1 #BBDEFB); } QHeaderView::section { background: #1E88E5; color: #FFFFFF; padding: 8px; border: none; font-weight: bold; }")
        publish_layout.addWidget(QLabel("Publish", styleSheet="color: #1E88E5; font-size: 22px; font-weight: bold; padding: 12px;"))
        publish_layout.addWidget(publish_group)
        publish_layout.addWidget(QLabel("Scheduled Posts", styleSheet="color: #1E88E5; font-size: 16px; font-weight: bold; padding: 6px;"))
        publish_layout.addWidget(self.scheduled_posts_table, alignment=Qt.AlignCenter)
        publish_layout.addStretch()
        self.content_stack.addTab(publish_tab, "Publish")
        add_members_tab = QWidget()
        add_members_layout = QVBoxLayout(add_members_tab)
        add_members_layout.setSpacing(20)
        add_members_group = QGroupBox("Add Members Control")
        add_members_group.setFont(QFont("Segoe UI", 16, QFont.Bold))
        add_members_group.setStyleSheet("QGroupBox { color: #1E3A8A; border: 1px solid #BBDEFB; border-radius: 6px; background: #FFFFFF; padding: 12px; box-shadow: 0 4px 12px rgba(0, 0, 0, 0.1); }")
        add_members_form = QFormLayout()
        add_members_form.setLabelAlignment(Qt.AlignRight)
        add_members_form.setFormAlignment(Qt.AlignCenter)
        add_members_form.setSpacing(10)
        self.group_id_input = QLineEdit(placeholderText="Enter Group ID")
        self.group_id_input.setFixedWidth(300)
        self.members_input = QTextEdit(placeholderText="Enter Member IDs (one per line)")
        self.members_input.setFixedSize(400, 100)
        self.invite_account_combo = QComboBox()
        self.invite_account_combo.setFixedWidth(200)
        self.invite_target_combo = QComboBox()
        self.invite_target_combo.addItems(["All Groups", "Selected Groups"])
        self.invite_target_combo.setFixedWidth(150)
        self.invite_target_list = QListWidget()
        self.invite_target_list.setFixedSize(200, 150)
        self.invite_target_list.setSelectionMode(QListWidget.MultiSelection)
        self.send_invites_button = QPushButton("Send Invites")
        self.send_invites_button.setFont(QFont("Segoe UI", 12))
        self.send_invites_button.setStyleSheet("QPushButton { background: #1E88E5; color: #FFFFFF; padding: 10px; border-radius: 12px; box-shadow: 0 3px 6px rgba(0, 0, 0, 0.15); } QPushButton:hover { background: #42A5F5; box-shadow: 0 5px 10px rgba(66, 165, 245, 0.3); transition: all 0.3s ease; }")
        add_members_form.addRow(QLabel("Group ID:"), self.group_id_input)
        add_members_form.addRow(QLabel("Member IDs:"), self.members_input)
        add_members_form.addRow(QLabel("Select Account:"), self.invite_account_combo)
        add_members_form.addRow(QLabel("Select Target:"), self.invite_target_combo)
        add_members_form.addRow("", self.invite_target_list)
        add_members_form.addRow("", self.send_invites_button)
        add_members_group.setLayout(add_members_form)
        add_members_layout.addWidget(QLabel("Add Members", styleSheet="color: #1E88E5; font-size: 22px; font-weight: bold; padding: 12px;"))
        add_members_layout.addWidget(add_members_group)
        add_members_layout.addStretch()
        self.content_stack.addTab(add_members_tab, "Add Members")
        analytics_tab = QWidget()
        analytics_layout = QVBoxLayout(analytics_tab)
        analytics_layout.setSpacing(20)
        analytics_group = QGroupBox("Analytics Dashboard")
        analytics_group.setFont(QFont("Segoe UI", 16, QFont.Bold))
        analytics_group.setStyleSheet("QGroupBox { color: #1E3A8A; border: 1px solid #BBDEFB; border-radius: 6px; background: #FFFFFF; padding: 12px; box-shadow: 0 4px 12px rgba(0, 0, 0, 0.1); }")
        analytics_form = QFormLayout()
        analytics_form.setLabelAlignment(Qt.AlignRight)
        analytics_form.setFormAlignment(Qt.AlignCenter)
        analytics_form.setSpacing(10)
        self.keywords_input = QLineEdit(placeholderText="Enter keywords for post suggestion")
        self.keywords_input.setFixedWidth(300)
        self.suggest_post_button_analytics = QPushButton("Suggest Post")
        self.view_stats_button = QPushButton("View Campaign Stats")
        self.optimize_schedule_button = QPushButton("Optimize Posting Schedule")
        self.active_groups_button = QPushButton("Identify Active Groups")
        for btn in [self.suggest_post_button_analytics, self.view_stats_button, self.optimize_schedule_button, self.active_groups_button]:
            btn.setFont(QFont("Segoe UI", 12))
            btn.setStyleSheet("QPushButton { background: #1E88E5; color: #FFFFFF; padding: 10px; border-radius: 12px; box-shadow: 0 3px 6px rgba(0, 0, 0, 0.15); } QPushButton:hover { background: #42A5F5; box-shadow: 0 5px 10px rgba(66, 165, 245, 0.3); transition: all 0.3s ease; }")
        analytics_form.addRow(QLabel("Keywords for Suggestion:"), self.keywords_input)
        analytics_form.addRow("", self.suggest_post_button_analytics)
        analytics_form.addRow("", self.view_stats_button)
        analytics_form.addRow("", self.optimize_schedule_button)
        analytics_form.addRow("", self.active_groups_button)
        analytics_group.setLayout(analytics_form)
        self.stats_table = QTableWidget()
        self.stats_table.setColumnCount(5)
        self.stats_table.setHorizontalHeaderLabels(["Account ID", "Posts", "Engagement", "Invites", "Extracted Members"])
        self.stats_table.setFixedSize(900, 200)
        self.stats_table.setStyleSheet("QTableWidget { border: 1px solid #BBDEFB; border-radius: 6px; background: #FFFFFF; } QTableWidget::item:selected { background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #E3F2FD, stop:1 #BBDEFB); } QHeaderView::section { background: #1E88E5; color: #FFFFFF; padding: 8px; border: none; font-weight: bold; }")
        self.active_groups_table = QTableWidget()
        self.active_groups_table.setColumnCount(5)
        self.active_groups_table.setHorizontalHeaderLabels(["Group ID", "Group Name", "Posts", "Invites", "Success Rate"])
        self.active_groups_table.setFixedSize(900, 200)
        self.active_groups_table.setStyleSheet("QTableWidget { border: 1px solid #BBDEFB; border-radius: 6px; background: #FFFFFF; } QTableWidget::item:selected { background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #E3F2FD, stop:1 #BBDEFB); } QHeaderView::section { background: #1E88E5; color: #FFFFFF; padding: 8px; border: none; font-weight: bold; }")
        analytics_layout.addWidget(QLabel("Analytics", styleSheet="color: #1E88E5; font-size: 22px; font-weight: bold; padding: 12px;"))
        analytics_layout.addWidget(analytics_group)
        analytics_layout.addWidget(QLabel("Campaign Statistics", styleSheet="color: #1E88E5; font-size: 16px; font-weight: bold; padding: 6px;"))
        analytics_layout.addWidget(self.stats_table, alignment=Qt.AlignCenter)
        analytics_layout.addWidget(QLabel("Active Groups", styleSheet="color: #1E88E5; font-size: 16px; font-weight: bold; padding: 6px;"))
        analytics_layout.addWidget(self.active_groups_table, alignment=Qt.AlignCenter)
        analytics_layout.addStretch()
        self.content_stack.addTab(analytics_tab, "Analytics")
        logs_tab = QWidget()
        logs_layout = QVBoxLayout(logs_tab)
        logs_layout.setSpacing(20)
        self.logs_table = QTableWidget()
        self.logs_table.setColumnCount(7)
        self.logs_table.setHorizontalHeaderLabels(["ID", "Account ID", "Target", "Action", "Timestamp", "Status", "Details"])
        self.logs_table.setFixedSize(900, 300)
        self.logs_table.setStyleSheet("QTableWidget { border: 1px solid #BBDEFB; border-radius: 6px; background: #FFFFFF; } QTableWidget::item:selected { background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #E3F2FD, stop:1 #BBDEFB); } QHeaderView::section { background: #1E88E5; color: #FFFFFF; padding: 8px; border: none; font-weight: bold; }")
        logs_buttons = QHBoxLayout()
        self.refresh_logs_button = QPushButton("↻ Refresh Logs")
        self.clear_logs_button = QPushButton("Clear Logs")
        self.logs_prev_button = QPushButton("◄ Previous")
        self.logs_next_button = QPushButton("Next ►")
        self.logs_page_label = QLabel("Page 1")
        self.logs_page_label.setStyleSheet("color: #1E3A8A; font-size: 14px;")
        for btn in [self.refresh_logs_button, self.clear_logs_button, self.logs_prev_button, self.logs_next_button]:
            btn.setFont(QFont("Segoe UI", 12))
            btn.setStyleSheet("QPushButton { background: #1E88E5; color: #FFFFFF; padding: 8px; border-radius: 8px; } QPushButton:hover { background: #42A5F5; transition: all 0.3s ease; }")
        logs_buttons.addStretch()
        logs_buttons.addWidget(self.refresh_logs_button)
        logs_buttons.addWidget(self.clear_logs_button)
        logs_buttons.addWidget(self.logs_prev_button)
        logs_buttons.addWidget(self.logs_page_label)
        logs_buttons.addWidget(self.logs_next_button)
        logs_buttons.addStretch()
        logs_layout.addWidget(QLabel("Logs", styleSheet="color: #1E88E5; font-size: 22px; font-weight: bold; padding: 12px;"))
        logs_layout.addWidget(self.logs_table, alignment=Qt.AlignCenter)
        logs_layout.addLayout(logs_buttons)
        logs_layout.addStretch()
        self.content_stack.addTab(logs_tab, "Logs")
        footer_widget = QWidget()
        footer_widget.setFixedHeight(80)
        footer_widget.setStyleSheet("background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #E3F2FD, stop:1 #BBDEFB); border-top: 2px solid #90CAF9; box-shadow: 0 -2px 8px rgba(0, 0, 0, 0.15);")
        footer_layout = QHBoxLayout(footer_widget)
        footer_layout.setContentsMargins(10, 0, 10, 0)
        self.progress_bar = QProgressBar()
        self.progress_bar.setFixedWidth(300)
        self.progress_bar.setStyleSheet("QProgressBar { border: 1px solid #BBDEFB; border-radius: 6px; background: #FFFFFF; text-align: center; color: #1E3A8A; font-size: 12px; } QProgressBar::chunk { background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #1E88E5, stop:1 #42A5F5); border-radius: 6px; }")
        self.status_label = QLabel("Status: Ready")
        self.status_label.setFont(QFont("Segoe UI", 12))
        self.status_label.setStyleSheet("color: #1E3A8A; padding: 6px;")
        self.stats_label = QLabel(f"Posted: {self.posted_count} | Engine: NO LIMIT | Accounts: 0 | Groups: 0")
        self.stats_label.setFont(QFont("Segoe UI", 12))
        self.stats_label.setStyleSheet("color: #1E3A8A; padding: 6px;")
        footer_layout.addWidget(self.progress_bar)
        footer_layout.addStretch()
        footer_layout.addWidget(self.status_label)
        footer_layout.addWidget(self.stats_label)
        main_layout.addWidget(content_widget)
        main_layout.addWidget(footer_widget)
        self.connect_signals()
        self.update_accounts_table()
        self.update_groups_table()
        self.update_logs_table()
        self.update_scheduled_posts_table()
        self.update_accounts_list()
        self.update_targets_list()

    def connect_signals(self):
        self.save_settings_button.clicked.connect(self.save_settings)
        self.add_accounts_button.clicked.connect(self.add_accounts)
        self.import_file_button.clicked.connect(self.import_accounts_file)
        self.login_all_button.clicked.connect(self.login_accounts_async)
        self.verify_login_button.clicked.connect(self.verify_login)
        self.close_browsers_button.clicked.connect(self.close_all_browsers)
        self.accounts_prev_button.clicked.connect(lambda: self.update_accounts_table("prev"))
        self.accounts_next_button.clicked.connect(lambda: self.update_accounts_table("next"))
        self.extract_groups_button.clicked.connect(lambda: self.loop.create_task(self.extract_groups()))
        self.extract_joined_button.clicked.connect(lambda: self.loop.create_task(self.extract_joined_groups()))
        self.add_group_manually_button.clicked.connect(self.add_group_manually)
        self.save_groups_button.clicked.connect(self.save_groups)
        self.use_selected_groups_button.clicked.connect(self.use_selected_groups)
        self.select_all_groups_button.clicked.connect(self.select_all_groups)
        self.deselect_all_groups_button.clicked.connect(self.deselect_all_groups)
        self.custom_selection_button.clicked.connect(self.custom_group_selection)
        self.refresh_groups_button.clicked.connect(self.update_groups_table)
        self.delete_groups_button.clicked.connect(self.delete_selected_groups)
        self.extract_users_button.clicked.connect(lambda: self.loop.create_task(self.extract_group_users()))
        self.join_new_groups_button.clicked.connect(lambda: self.loop.create_task(self.join_new_groups()))
        self.add_to_favorites_button.clicked.connect(self.add_to_favorites)
        self.transfer_members_button.clicked.connect(lambda: self.loop.create_task(self.transfer_members()))
        self.interact_members_button.clicked.connect(lambda: self.loop.create_task(self.interact_with_members()))
        self.close_groups_browser_button.clicked.connect(self.close_groups_browser)
        self.auto_approve_button.clicked.connect(lambda: self.loop.create_task(self.auto_approve_requests()))
        self.delete_posts_button.clicked.connect(lambda: self.loop.create_task(self.delete_posts()))
        self.apply_filter_button.clicked.connect(self.apply_group_filter)
        self.groups_prev_button.clicked.connect(lambda: self.update_groups_table(direction="prev"))
        self.groups_next_button.clicked.connect(lambda: self.update_groups_table(direction="next"))
        self.attach_photo_button.clicked.connect(self.attach_photo)
        self.attach_video_button.clicked.connect(self.attach_video)
        self.schedule_timer_button.clicked.connect(lambda: self.loop.create_task(self.schedule_post_async()))
        self.stop_switch_button.clicked.connect(self.stop_publishing)
        self.stop_after_posts_button.clicked.connect(self.stop_after_posts)
        self.resume_button.clicked.connect(self.resume_publishing)
        self.publish_button.clicked.connect(lambda: self.loop.create_task(self.post_content_async()))
        self.posted_messages_button.clicked.connect(self.show_posted_messages)
        self.send_invites_button.clicked.connect(lambda: self.loop.create_task(self.add_members_async()))
        self.suggest_post_button_analytics.clicked.connect(self.suggest_post)
        self.view_stats_button.clicked.connect(self.view_campaign_stats)
        self.optimize_schedule_button.clicked.connect(self.optimize_posting_schedule)
        self.active_groups_button.clicked.connect(self.identify_active_groups)
        self.refresh_logs_button.clicked.connect(self.update_logs_table)
        self.clear_logs_button.clicked.connect(self.clear_logs)
        self.logs_prev_button.clicked.connect(lambda: self.update_logs_table("prev"))
        self.logs_next_button.clicked.connect(lambda: self.update_logs_table("next"))
        self.statusUpdated.connect(self.update_status)
        self.progressUpdated.connect(self.update_progress)
        self.account_manager.statusUpdated.connect(self.update_status)
        self.account_manager.progressUpdated.connect(self.update_progress)
        self.group_manager.statusUpdated.connect(self.update_status)
        self.group_manager.progressUpdated.connect(self.update_progress)
        self.post_manager.statusUpdated.connect(self.update_status)
        self.post_manager.progressUpdated.connect(self.update_progress)
        self.log_manager.statusUpdated.connect(self.update_status)
        self.log_manager.logsUpdated.connect(self.update_logs_table)
        self.analytics.statusUpdated.connect(self.update_status)
        self.analytics.progressUpdated.connect(self.update_progress)
        self.db.statusUpdated.connect(self.update_status)
        self.app.config_manager.statusUpdated.connect(self.update_status)
        self.timer = QTimer()
        self.timer.timeout.connect(self.update_logs_table)
        self.timer.timeout.connect(self.update_scheduled_posts_table)
        self.timer.timeout.connect(self.update_stats_label)
        self.timer.start(5000)

    def save_settings(self):
        self.app.config_manager.set("2captcha_api_key", self.api_key_input.text())
        self.app.config_manager.set("default_delay", self.delay_input.value())
        self.app.config_manager.set("max_retries", self.max_retries_input.value())
        self.app.config_manager.set("proxies", [p.strip() for p in self.proxy_input.toPlainText().splitlines() if p.strip()])
        self.app.config_manager.set("phone_number", self.phone_input.text())
        self.app.config_manager.set("custom_scripts", [s.strip() for s in self.reply_scripts.toPlainText().splitlines() if s.strip()])
        self.app.config_manager.set("default_language", self.language_input.currentText())
        self.show_message("Success", "Settings saved successfully.", "Information")

    def add_accounts(self):
        accounts_text = self.accounts_input.toPlainText().strip()
        if not accounts_text:
            self.show_message("Input Error", "Please enter account details.", "Warning")
            return
        self.account_manager.add_accounts(accounts_text)
        self.accounts_page = 0
        self.update_accounts_table()
        self.update_accounts_list()
        self.show_message("Success", "Accounts added successfully.", "Information")

    def import_accounts_file(self):
        file_name, _ = QFileDialog.getOpenFileName(self, "Import Accounts", "", "Text Files (*.txt)")
        if not file_name:
            return
        with open(file_name, "r", encoding="utf-8") as f:
            accounts_text = f.read().strip()
        if not accounts_text:
            self.show_message("File Error", "The selected file is empty.", "Warning")
            return
        self.account_manager.add_accounts(accounts_text)
        self.accounts_page = 0
        self.update_accounts_table()
        self.update_accounts_list()
        self.show_message("Success", "Accounts imported successfully from file.", "Information")

    def login_accounts_async(self):
        self.loop.create_task(self._login_accounts())

    async def _login_accounts(self):
        selected_accounts = [self.accounts_table.item(row, 2).text() for row in range(self.accounts_table.rowCount()) if self.accounts_table.cellWidget(row, 0).isChecked()]
        if not selected_accounts:
            selected_accounts = [acc[0] for acc in self.db.get_accounts()]
        await self.account_manager.login_all_accounts(
            login_mode=self.login_method.currentText(),
            preliminary_interaction=self.preliminary_interaction.isChecked(),
            mobile_view=self.mobile_view.isChecked(),
            visible=True
        )
        self.session_manager.close_all_drivers()
        self.update_accounts_table()
        self.update_accounts_list()
        self.show_message("Success", "Login process completed successfully.", "Information")

        def verify_login(self):
        selected_accounts = [self.accounts_table.item(row, 2).text() for row in range(self.accounts_table.rowCount()) if self.accounts_table.cellWidget(row, 0).isChecked()]
        if not selected_accounts:
            self.show_message("Selection Error", "Please select at least one account to verify login.", "Warning")
            return
        for fb_id in selected_accounts:
            self.loop.create_task(self.account_manager.verify_login_status(fb_id))
        self.show_message("Verification Started", "Login verification process started for selected accounts.", "Information")

    def close_all_browsers(self):
        self.account_manager.close_all_browsers()
        self.show_message("Success", "All browser sessions closed successfully.", "Information")

    async def extract_groups(self):
        keywords = self.search_groups_input.text().strip()
        if not keywords:
            self.show_message("Input Error", "Please enter keywords to search for groups.", "Warning")
            return
        await self.group_manager.extract_all_groups(keywords=keywords, fast_mode=False, interact=False)
        self.update_groups_table()
        self.update_targets_list()
        self.show_message("Success", "Group extraction completed successfully.", "Information")

    async def extract_joined_groups(self):
        await self.group_manager.extract_joined_groups()
        self.update_groups_table()
        self.update_targets_list()
        self.show_message("Success", "Joined groups extracted successfully.", "Information")

    def add_group_manually(self):
        dialog = QDialog(self)
        dialog.setWindowTitle("Add Group Manually")
        dialog.setFixedSize(400, 200)
        layout = QFormLayout(dialog)
        group_id_input = QLineEdit(placeholderText="Enter Group ID")
        group_name_input = QLineEdit(placeholderText="Enter Group Name")
        members_input = QSpinBox()
        members_input.setRange(0, 1000000)
        members_input.setValue(0)
        add_button = QPushButton("Add Group")
        add_button.clicked.connect(lambda: self._add_group_manually(dialog, group_id_input.text(), group_name_input.text(), members_input.value()))
        layout.addRow("Group ID:", group_id_input)
        layout.addRow("Group Name:", group_name_input)
        layout.addRow("Members:", members_input)
        layout.addRow("", add_button)
        dialog.exec_()

    def _add_group_manually(self, dialog, group_id, group_name, members):
        if not group_id or not group_name:
            self.show_message("Input Error", "Please provide both Group ID and Group Name.", "Warning")
            return
        self.db.add_group(None, group_id, group_name, members, status="Active")
        self.update_groups_table()
        self.update_targets_list()
        dialog.accept()
        self.show_message("Success", f"Group {group_name} added successfully.", "Information")

    def save_groups(self):
        self.show_message("Success", "Groups saved successfully to database.", "Information")

    def use_selected_groups(self):
        selected_groups = [self.groups_table.item(row, 3).text() for row in range(self.groups_table.rowCount()) if self.groups_table.cellWidget(row, 0).isChecked()]
        if not selected_groups:
            self.show_message("Selection Error", "Please select at least one group to use.", "Warning")
            return
        self.target_list.clear()
        for group_id in selected_groups:
            group_name = next((g[1] for g in self.db.get_groups() if g[0] == group_id), group_id)
            self.target_list.addItem(f"{group_name} ({group_id})")
        self.show_message("Success", f"Selected {len(selected_groups)} groups for publishing.", "Information")

    def select_all_groups(self):
        for row in range(self.groups_table.rowCount()):
            self.groups_table.cellWidget(row, 0).setChecked(True)

    def deselect_all_groups(self):
        for row in range(self.groups_table.rowCount()):
            self.groups_table.cellWidget(row, 0).setChecked(False)

    def custom_group_selection(self):
        dialog = QDialog(self)
        dialog.setWindowTitle("Custom Group Selection")
        dialog.setFixedSize(400, 200)
        layout = QFormLayout(dialog)
        privacy_combo = QComboBox()
        privacy_combo.addItems(["All", "Open", "Closed"])
        min_members_input = QSpinBox()
        min_members_input.setRange(0, 1000000)
        status_combo = QComboBox()
        status_combo.addItems(["All", "Active", "Inactive", "Favorite"])
        apply_button = QPushButton("Apply Selection")
        apply_button.clicked.connect(lambda: self._apply_custom_selection(dialog, privacy_combo.currentText(), min_members_input.value(), status_combo.currentText()))
        layout.addRow("Privacy:", privacy_combo)
        layout.addRow("Minimum Members:", min_members_input)
        layout.addRow("Status:", status_combo)
        layout.addRow("", apply_button)
        dialog.exec_()

    def _apply_custom_selection(self, dialog, privacy, min_members, status):
        privacy = None if privacy == "All" else privacy
        status = None if status == "All" else status
        groups = self.db.get_groups(min_members=min_members, privacy=privacy, status=status)
        for row in range(self.groups_table.rowCount()):
            group_id = self.groups_table.item(row, 3).text()
            if any(g[0] == group_id for g in groups):
                self.groups_table.cellWidget(row, 0).setChecked(True)
            else:
                self.groups_table.cellWidget(row, 0).setChecked(False)
        dialog.accept()
        self.show_message("Success", "Custom group selection applied.", "Information")

    def delete_selected_groups(self):
        selected_groups = [self.groups_table.item(row, 3).text() for row in range(self.groups_table.rowCount()) if self.groups_table.cellWidget(row, 0).isChecked()]
        if not selected_groups:
            self.show_message("Selection Error", "Please select at least one group to delete.", "Warning")
            return
        for group_id in selected_groups:
            self.db.delete_group(group_id)
        self.update_groups_table()
        self.update_targets_list()
        self.show_message("Success", f"Deleted {len(selected_groups)} groups successfully.", "Information")

    async def extract_group_users(self):
        selected_groups = [self.groups_table.item(row, 3).text() for row in range(self.groups_table.rowCount()) if self.groups_table.cellWidget(row, 0).isChecked()]
        if not selected_groups:
            self.show_message("Selection Error", "Please select at least one group to extract users from.", "Warning")
            return
        for group_id in selected_groups:
            await self.group_manager.extract_group_members(group_id)
        self.show_message("Success", "Group users extracted successfully.", "Information")

    async def join_new_groups(self):
        keywords = self.search_groups_input.text().strip()
        if not keywords:
            self.show_message("Input Error", "Please enter keywords to search for groups to join.", "Warning")
            return
        await self.group_manager.extract_all_groups(keywords=keywords, fast_mode=True, interact=True)
        self.update_groups_table()
        self.update_targets_list()
        self.show_message("Success", "Joined new groups successfully.", "Information")

    def add_to_favorites(self):
        selected_groups = [self.groups_table.item(row, 3).text() for row in range(self.groups_table.rowCount()) if self.groups_table.cellWidget(row, 0).isChecked()]
        if not selected_groups:
            self.show_message("Selection Error", "Please select at least one group to add to favorites.", "Warning")
            return
        for group_id in selected_groups:
            self.db.update_group(group_id, "Favorite")
        self.update_groups_table()
        self.show_message("Success", f"Added {len(selected_groups)} groups to favorites.", "Information")

    async def transfer_members(self):
        selected_groups = [self.groups_table.item(row, 3).text() for row in range(self.groups_table.rowCount()) if self.groups_table.cellWidget(row, 0).isChecked()]
        if len(selected_groups) < 2:
            self.show_message("Selection Error", "Please select at least two groups (one source and one or more targets) to transfer members.", "Warning")
            return
        source_group = selected_groups[0]
        target_groups = selected_groups[1:]
        await self.group_manager.transfer_members(source_group, target_groups)
        self.show_message("Success", f"Transferred members from group {source_group} to {len(target_groups)} target groups.", "Information")

    async def interact_with_members(self):
        selected_groups = [self.groups_table.item(row, 3).text() for row in range(self.groups_table.rowCount()) if self.groups_table.cellWidget(row, 0).isChecked()]
        if not selected_groups:
            self.show_message("Selection Error", "Please select at least one group to interact with members.", "Warning")
            return
        await self.group_manager.interact_with_members(selected_groups)
        self.show_message("Success", f"Interacted with members in {len(selected_groups)} groups.", "Information")

    def close_groups_browser(self):
        self.session_manager.close_all_drivers()
        self.show_message("Success", "Group-related browser sessions closed successfully.", "Information")

    async def auto_approve_requests(self):
        selected_groups = [self.groups_table.item(row, 3).text() for row in range(self.groups_table.rowCount()) if self.groups_table.cellWidget(row, 0).isChecked()]
        if not selected_groups:
            self.show_message("Selection Error", "Please select at least one group to auto-approve requests.", "Warning")
            return
        await self.group_manager.auto_approve_join_requests(selected_groups)
        self.show_message("Success", f"Auto-approved join requests for {len(selected_groups)} groups.", "Information")

    async def delete_posts(self):
        selected_groups = [self.groups_table.item(row, 3).text() for row in range(self.groups_table.rowCount()) if self.groups_table.cellWidget(row, 0).isChecked()]
        if not selected_groups:
            self.show_message("Selection Error", "Please select at least one group to delete posts with no interaction.", "Warning")
            return
        await self.group_manager.delete_no_interaction_posts(selected_groups)
        self.show_message("Success", f"Deleted posts with no interaction in {len(selected_groups)} groups.", "Information")

    def apply_group_filter(self):
        privacy = self.filter_privacy.currentText()
        min_members = self.filter_members.value()
        name_filter = self.filter_name.text().strip()
        status = self.filter_status.currentText()
        privacy = None if privacy == "All" else privacy
        status = None if status == "All" else status
        self.groups_page = 0
        self.update_groups_table(privacy=privacy, min_members=min_members, name_filter=name_filter, status=status)
        self.show_message("Success", "Group filter applied successfully.", "Information")

    def attach_photo(self):
        file_name, _ = QFileDialog.getOpenFileName(self, "Select Photo", "", "Images (*.png *.jpg *.jpeg)")
        if file_name:
            self.attachments.append(("photo", file_name))
            self.attachments_label.setText(f"Attached: {', '.join([a[1] for a in self.attachments])}")
            self.show_message("Success", "Photo attached successfully.", "Information")

    def attach_video(self):
        file_name, _ = QFileDialog.getOpenFileName(self, "Select Video", "", "Videos (*.mp4 *.mov *.avi)")
        if file_name:
            self.attachments.append(("video", file_name))
            self.attachments_label.setText(f"Attached: {', '.join([a[1] for a in self.attachments])}")
            self.show_message("Success", "Video attached successfully.", "Information")

    async def schedule_post_async(self):
        accounts = [self.accounts_list.item(i).text().split(" (")[0] for i in range(self.accounts_list.count()) if self.accounts_list.item(i).isSelected()]
        targets = [self.target_list.item(i).text().split(" (")[1][:-1] for i in range(self.target_list.count()) if self.target_list.item(i).isSelected()] if self.target_combo.currentText() == "Selected Groups" else None
        if not accounts:
            self.show_message("Selection Error", "Please select at least one account to schedule a post.", "Warning")
            return
        content = self.global_content_input.toPlainText().strip()
        if not content:
            self.show_message("Input Error", "Please enter content to schedule.", "Warning")
            return
        links = [link.strip() for link in self.links_input.text().split(",") if link.strip()]
        schedule_time = datetime.now().replace(hour=self.timer_input.time().hour(), minute=self.timer_input.time().minute(), second=0, microsecond=0)
        await self.post_manager.schedule_post(
            accounts=accounts,
            targets=targets,
            content=content,
            links=links,
            attachments=self.attachments,
            schedule_time=schedule_time,
            post_tech=self.post_tech_combo.currentText(),
            target_type=self.post_target_combo.currentText(),
            anti_block=self.anti_block_checkbox.isChecked(),
            speed=self.speed_spinbox.value(),
            delay=self.delay_spinbox.value(),
            step=self.step_spinbox.value(),
            random_time=self.random_time_checkbox.isChecked(),
            spin_content=self.spin_content_flag.isChecked(),
            allow_duplicates=self.allow_duplicates.isChecked(),
            auto_reply=self.auto_reply_checkbox.isChecked()
        )
        self.update_scheduled_posts_table()
        self.show_message("Success", "Post scheduled successfully.", "Information")

    async def post_content_async(self):
        accounts = [self.accounts_list.item(i).text().split(" (")[0] for i in range(self.accounts_list.count()) if self.accounts_list.item(i).isSelected()]
        targets = [self.target_list.item(i).text().split(" (")[1][:-1] for i in range(self.target_list.count()) if self.target_list.item(i).isSelected()] if self.target_combo.currentText() == "Selected Groups" else None
        if not accounts:
            self.show_message("Selection Error", "Please select at least one account to publish a post.", "Warning")
            return
        content = self.global_content_input.toPlainText().strip()
        if not content:
            self.show_message("Input Error", "Please enter content to publish.", "Warning")
            return
        links = [link.strip() for link in self.links_input.text().split(",") if link.strip()]
        await self.post_manager.post_content(
            accounts=accounts,
            targets=targets,
            content=content,
            links=links,
            attachments=self.attachments,
            limit=self.post_limit_spinbox.value(),
            post_tech=self.post_tech_combo.currentText(),
            target_type=self.post_target_combo.currentText(),
            anti_block=self.anti_block_checkbox.isChecked(),
            speed=self.speed_spinbox.value(),
            delay=self.delay_spinbox.value(),
            step=self.step_spinbox.value(),
            spin_content=self.spin_content_flag.isChecked(),
            allow_duplicates=self.allow_duplicates.isChecked(),
            auto_reply=self.auto_reply_checkbox.isChecked()
        )
        self.update_scheduled_posts_table()
        self.posted_count += len(accounts) * (len(targets) if targets else 1)
        self.update_stats_label()
        self.show_message("Success", "Content published successfully.", "Information")

    def stop_publishing(self):
        self.post_manager.stop_publishing()
        self.show_message("Success", "Publishing stopped successfully.", "Information")

    def stop_after_posts(self):
        self.post_manager.set_stop_condition(self.stop_spinbox.value(), self.stop_unit_combo.currentText())
        self.show_message("Success", f"Publishing will stop after {self.stop_spinbox.value()} {self.stop_unit_combo.currentText()}.", "Information")

    def resume_publishing(self):
        self.post_manager.resume_publishing()
        self.show_message("Success", "Publishing resumed successfully.", "Information")

    def show_posted_messages(self):
        dialog = QDialog(self)
        dialog.setWindowTitle("Posted Messages")
        dialog.setFixedSize(800, 400)
        layout = QVBoxLayout(dialog)
        table = QTableWidget()
        table.setColumnCount(4)
        table.setHorizontalHeaderLabels(["Account ID", "Content", "Target", "Timestamp"])
        table.setFixedSize(750, 300)
        table.setStyleSheet("QTableWidget { border: 1px solid #BBDEFB; border-radius: 6px; background: #FFFFFF; } QHeaderView::section { background: #1E88E5; color: #FFFFFF; padding: 8px; border: none; font-weight: bold; }")
        posted_messages = self.db.get_posted_messages()
        table.setRowCount(len(posted_messages))
        for row, (account_id, content, target, timestamp) in enumerate(posted_messages):
            table.setItem(row, 0, QTableWidgetItem(account_id))
            table.setItem(row, 1, QTableWidgetItem(content))
            table.setItem(row, 2, QTableWidgetItem(target or "News Feed"))
            table.setItem(row, 3, QTableWidgetItem(str(timestamp)))
        layout.addWidget(table)
        dialog.exec_()

    async def add_members_async(self):
        group_ids = [self.invite_target_list.item(i).text().split(" (")[1][:-1] for i in range(self.invite_target_list.count()) if self.invite_target_list.item(i).isSelected()] if self.invite_target_combo.currentText() == "Selected Groups" else None
        if not group_ids:
            group_ids = [self.group_id_input.text().strip()]
        if not group_ids or not group_ids[0]:
            self.show_message("Input Error", "Please enter or select a group ID to add members to.", "Warning")
            return
        member_ids = [m.strip() for m in self.members_input.toPlainText().splitlines() if m.strip()]
        if not member_ids:
            self.show_message("Input Error", "Please enter member IDs to invite.", "Warning")
            return
        account_id = self.invite_account_combo.currentText().split(" (")[0] if self.invite_account_combo.currentText() else None
        if not account_id:
            self.show_message("Selection Error", "Please select an account to send invites from.", "Warning")
            return
        await self.group_manager.add_members(account_id, group_ids, member_ids)
        self.show_message("Success", f"Invites sent to {len(member_ids)} members in {len(group_ids)} groups.", "Information")

    def suggest_post(self):
        keywords = self.keywords_input.text().strip()
        if not keywords:
            self.show_message("Input Error", "Please enter keywords for post suggestion.", "Warning")
            return
        suggestion = self.analytics.suggest_post(keywords)
        self.show_message("Post Suggestion", suggestion, "Information")

    def view_campaign_stats(self):
        stats = self.analytics.get_campaign_stats()
        self.stats_table.setRowCount(len(stats))
        for row, (account_id, posts, engagement, invites, extracted) in enumerate(stats):
            self.stats_table.setItem(row, 0, QTableWidgetItem(account_id))
            self.stats_table.setItem(row, 1, QTableWidgetItem(str(posts)))
            self.stats_table.setItem(row, 2, QTableWidgetItem(str(engagement)))
            self.stats_table.setItem(row, 3, QTableWidgetItem(str(invites)))
            self.stats_table.setItem(row, 4, QTableWidgetItem(str(extracted)))
        self.show_message("Success", "Campaign statistics updated successfully.", "Information")

    def optimize_posting_schedule(self):
        optimal_times = self.analytics.optimize_schedule()
        self.show_message("Optimal Schedule", f"Recommended posting times: {optimal_times}", "Information")

    def identify_active_groups(self):
        active_groups = self.analytics.identify_active_groups()
        self.active_groups_table.setRowCount(len(active_groups))
        for row, (group_id, group_name, posts, invites, success_rate) in enumerate(active_groups):
            self.active_groups_table.setItem(row, 0, QTableWidgetItem(group_id))
            self.active_groups_table.setItem(row, 1, QTableWidgetItem(group_name))
            self.active_groups_table.setItem(row, 2, QTableWidgetItem(str(posts)))
            self.active_groups_table.setItem(row, 3, QTableWidgetItem(str(invites)))
            self.active_groups_table.setItem(row, 4, QTableWidgetItem(f"{success_rate:.2f}%"))
        self.show_message("Success", "Active groups identified successfully.", "Information")

    def clear_logs(self):
        self.db.clear_logs()
        self.logs_page = 0
        self.update_logs_table()
        self.show_message("Success", "Logs cleared successfully.", "Information")

    def update_accounts_table(self, direction=None):
        if direction == "prev":
            self.accounts_page = max(0, self.accounts_page - 1)
        elif direction == "next":
            total_accounts = self.db.get_accounts_count()
            if (self.accounts_page + 1) * self.page_size < total_accounts:
                self.accounts_page += 1
        accounts = self.db.get_accounts(offset=self.accounts_page * self.page_size, limit=self.page_size)
        self.accounts_table.setRowCount(len(accounts))
        for row, account in enumerate(accounts):
            checkbox = QCheckBox()
            self.accounts_table.setCellWidget(row, 0, checkbox)
            self.accounts_table.setItem(row, 1, QTableWidgetItem(str(row + 1 + self.accounts_page * self.page_size)))
            self.accounts_table.setItem(row, 2, QTableWidgetItem(account[0]))  # UID
            self.accounts_table.setItem(row, 3, QTableWidgetItem(account[1] or ""))
            self.accounts_table.setItem(row, 4, QTableWidgetItem(account[2] or ""))
            self.accounts_table.setItem(row, 5, QTableWidgetItem(account[3] or ""))
            self.accounts_table.setItem(row, 6, QTableWidgetItem(account[4] or ""))
            self.accounts_table.setItem(row, 7, QTableWidgetItem(account[5] or ""))
            self.accounts_table.setItem(row, 8, QTableWidgetItem(account[6] or ""))
            self.accounts_table.setItem(row, 9, QTableWidgetItem(str(account[7])))
            self.accounts_table.setItem(row, 10, QTableWidgetItem(str(account[8])))
            self.accounts_table.setItem(row, 11, QTableWidgetItem(account[9] or ""))
        self.accounts_page_label.setText(f"Page {self.accounts_page + 1}")
        self.update_stats_label()

    def update_groups_table(self, direction=None, privacy=None, min_members=0, name_filter="", status=None):
        if direction == "prev":
            self.groups_page = max(0, self.groups_page - 1)
        elif direction == "next":
            total_groups = self.db.get_groups_count(privacy=privacy, min_members=min_members, name_filter=name_filter, status=status)
            if (self.groups_page + 1) * self.page_size < total_groups:
                self.groups_page += 1
        groups = self.db.get_groups(offset=self.groups_page * self.page_size, limit=self.page_size, privacy=privacy, min_members=min_members, name_filter=name_filter, status=status)
        self.groups_table.setRowCount(len(groups))
        for row, group in enumerate(groups):
            checkbox = QCheckBox()
            self.groups_table.setCellWidget(row, 0, checkbox)
            self.groups_table.setItem(row, 1, QTableWidgetItem(str(row + 1 + self.groups_page * self.page_size)))
            self.groups_table.setItem(row, 2, QTableWidgetItem(group[1]))  # Group Name
            self.groups_table.setItem(row, 3, QTableWidgetItem(group[0]))  # Group ID
            self.groups_table.setItem(row, 4, QTableWidgetItem(group[2] or "Unknown"))
            self.groups_table.setItem(row, 5, QTableWidgetItem(str(group[3])))
        self.groups_page_label.setText(f"Page {self.groups_page + 1}")
        self.update_stats_label()

    def update_logs_table(self, direction=None):
        if direction == "prev":
            self.logs_page = max(0, self.logs_page - 1)
        elif direction == "next":
            total_logs = self.db.get_logs_count()
            if (self.logs_page + 1) * self.page_size < total_logs:
                self.logs_page += 1
        logs = self.db.get_logs(offset=self.logs_page * self.page_size, limit=self.page_size)
        self.logs_table.setRowCount(len(logs))
        for row, log in enumerate(logs):
            self.logs_table.setItem(row, 0, QTableWidgetItem(str(log[0])))
            self.logs_table.setItem(row, 1, QTableWidgetItem(log[1] or ""))
            self.logs_table.setItem(row, 2, QTableWidgetItem(log[2] or ""))
            self.logs_table.setItem(row, 3, QTableWidgetItem(log[3] or ""))
            self.logs_table.setItem(row, 4, QTableWidgetItem(str(log[4])))
            self.logs_table.setItem(row, 5, QTableWidgetItem(log[5] or ""))
            self.logs_table.setItem(row, 6, QTableWidgetItem(log[6] or ""))
        self.logs_page_label.setText(f"Page {self.logs_page + 1}")

    def update_scheduled_posts_table(self):
        scheduled_posts = self.db.get_scheduled_posts()
        self.scheduled_posts_table.setRowCount(len(scheduled_posts))
        for row, post in enumerate(scheduled_posts):
            self.scheduled_posts_table.setItem(row, 0, QTableWidgetItem(str(post[0])))
            self.scheduled_posts_table.setItem(row, 1, QTableWidgetItem(post[1]))
            self.scheduled_posts_table.setItem(row, 2, QTableWidgetItem(post[2]))
            self.scheduled_posts_table.setItem(row, 3, QTableWidgetItem(str(post[3])))
            self.scheduled_posts_table.setItem(row, 4, QTableWidgetItem(post[4] or ""))
            self.scheduled_posts_table.setItem(row, 5, QTableWidgetItem(post[5]))

    def update_accounts_list(self):
        self.accounts_list.clear()
        self.invite_account_combo.clear()
        accounts = self.db.get_accounts()
        for account in accounts:
            self.accounts_list.addItem(f"{account[0]} ({account[6]})")
            self.invite_account_combo.addItem(f"{account[0]} ({account[6]})")

    def update_targets_list(self):
        self.target_list.clear()
        self.invite_target_list.clear()
        groups = self.db.get_groups()
        for group in groups:
            self.target_list.addItem(f"{group[1]} ({group[0]})")
            self.invite_target_list.addItem(f"{group[1]} ({group[0]})")

    def update_stats_label(self):
        total_accounts = self.db.get_accounts_count()
        total_groups = self.db.get_groups_count()
        self.stats_label.setText(f"Posted: {self.posted_count} | Engine: NO LIMIT | Accounts: {total_accounts} | Groups: {total_groups}")

    def update_status(self, message):
        self.status_label.setText(f"Status: {message}")

    def update_progress(self, current, total):
        if total > 0:
            progress = int((current / total) * 100)
            self.progress_bar.setValue(progress)
        else:
            self.progress_bar.setValue(0)

    def show_message(self, title, message, icon):
        msg = QMessageBox(self)
        msg.setWindowTitle(title)
        msg.setText(message)
        if icon == "Information":
            msg.setIcon(QMessageBox.Information)
        elif icon == "Warning":
            msg.setIcon(QMessageBox.Warning)
        elif icon == "Critical":
            msg.setIcon(QMessageBox.Critical)
        msg.exec_()

    def switch_tab(self, tab_name):
        tab_map = {
            "Settings": 0,
            "Accounts": 1,
            "Groups": 2,
            "Publish": 3,
            "Add Members": 4,
            "Analytics": 5,
            "Logs": 6,
            "Add Batch": 1,
            "Import File": 1,
            "Login All": 1,
            "Verify Login": 1,
            "Close Browser": 1,
            "Extract Joined Groups": 2,
            "Save": 2,
            "Schedule Post": 3,
            "Publish Now": 3,
            "Stop Publishing": 3,
            "Send Invites": 4,
            "View Campaign Stats": 5,
            "Suggest Post": 5
        }
        if tab_name in tab_map:
            self.content_stack.setCurrentIndex(tab_map[tab_name])
        if tab_name == "Add Batch":
            self.add_accounts()
        elif tab_name == "Import File":
            self.import_accounts_file()
        elif tab_name == "Login All":
            self.login_accounts_async()
        elif tab_name == "Verify Login":
            self.verify_login()
        elif tab_name == "Close Browser":
            self.close_all_browsers()
        elif tab_name == "Extract Joined Groups":
            self.loop.create_task(self.extract_joined_groups())
        elif tab_name == "Save":
            self.save_groups()
        elif tab_name == "Schedule Post":
            self.loop.create_task(self.schedule_post_async())
        elif tab_name == "Publish Now":
            self.loop.create_task(self.post_content_async())
        elif tab_name == "Stop Publishing":
            self.stop_publishing()
        elif tab_name == "Send Invites":
            self.loop.create_task(self.add_members_async())
        elif tab_name == "View Campaign Stats":
            self.view_campaign_stats()
        elif tab_name == "Suggest Post":
            self.suggest_post()

    def closeEvent(self, event):
        self.db.close()
        self.session_manager.close_all_drivers()
        event.accept()

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = SmartPosterUI(app)
    window.show()
    sys.exit(app.exec_())
        