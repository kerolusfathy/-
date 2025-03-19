# ui_design.py
import sys
import asyncio
import os
from datetime import datetime
from typing import List, Optional, Dict
from PyQt5.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QFormLayout, QGroupBox,
                             QLabel, QTextEdit, QLineEdit, QComboBox, QSpinBox, QPushButton, QTableWidget, QTableWidgetItem,
                             QProgressBar, QMessageBox, QCheckBox, QTabWidget, QFileDialog, QListWidget, QTimeEdit)
from PyQt5.QtCore import Qt, QTimer, QCoreApplication, pyqtSignal, QTime, QThreadPool, QRect
from PyQt5.QtGui import QFont, QIcon
import traceback
from database import Database
from account_manager import AccountManager
from group_manager import GroupManager
from post_manager import PostManager
from log_manager import LogManager
from ai_analytics import AIAnalytics
from utils import SessionManager, load_cookies, decrypt_data, solve_captcha, get_access_token, predictive_ban_detection, simulate_human_behavior, spin_content

class SmartPosterUI(QMainWindow):
    """واجهة المستخدم الرسومية الاحترافية لـ SmartPoster."""
    statusUpdated = pyqtSignal(str)  # إشارة لتحديث الحالة
    progressUpdated = pyqtSignal(int, int)  # إشارة لتحديث شريط التقدم

    def __init__(self, app=None):
        super().__init__()
        self.app = app or QCoreApplication.instance()
        try:
            self.db = Database(self.app, log_manager=self.app.log_manager)
            self.session_manager = SessionManager(self.app, self.app.config_manager)
            self.account_manager = AccountManager(self.app, self.app.config_manager, self.db, self.app.log_manager)
            self.group_manager = GroupManager(self.app, self.db, self.session_manager, self.app.config_manager, self.app.log_manager)
            self.post_manager = PostManager(self.app, self.db, self.session_manager, self.app.config_manager, self.app.log_manager)
            self.log_manager = LogManager(self.app, self.db)
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
            self._log("SmartPosterUI initialized successfully", "Info")
        except Exception as e:
            error_message = f"Failed to initialize SmartPosterUI: {str(e)}\n{traceback.format_exc()}"
            self._log(error_message, "Error")
            self.statusUpdated.emit(f"Error: {str(e)}")
            QMessageBox.critical(self, "Initialization Error", f"Failed to initialize UI: {str(e)}")

    def _log(self, message: str, level: str, fb_id: str = "System", action: str = "UI") -> None:
        """تسجيل الرسائل عبر log_manager مع تحديث الواجهة."""
        try:
            self.log_manager.add_log(fb_id, None, action, level, message)
            self.statusUpdated.emit(f"{level}: {message}")
        except Exception as e:
            print(f"Error logging in UI: {str(e)}\n{traceback.format_exc()}")

    def init_ui(self):
        """إعداد واجهة المستخدم الرسومية."""
        try:
            self.setStyleSheet("""
                QMainWindow { 
                    background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #E3F2FD, stop:1 #BBDEFB); 
                }
                QLabel { 
                    color: #1E3A8A; 
                    font-family: 'Segoe UI', sans-serif; 
                }
                QLineEdit, QTextEdit, QComboBox, QSpinBox, QTimeEdit { 
                    border: 1px solid #90CAF9; 
                    border-radius: 6px; 
                    padding: 6px; 
                    background: #FFFFFF; 
                    font-family: 'Segoe UI', sans-serif; 
                }
                QCheckBox { 
                    padding: 6px; 
                    font-family: 'Segoe UI', sans-serif; 
                    color: #1E3A8A; 
                }
                QListWidget { 
                    border: 1px solid #90CAF9; 
                    border-radius: 6px; 
                    background: #FFFFFF; 
                }
            """)

            central_widget = QWidget()
            self.setCentralWidget(central_widget)
            main_layout = QVBoxLayout(central_widget)
            main_layout.setContentsMargins(0, 0, 0, 0)
            main_layout.setSpacing(0)

            # Header
            header_widget = QWidget()
            header_widget.setFixedHeight(80)
            header_widget.setStyleSheet("""
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #1E88E5, stop:1 #42A5F5); 
                border-bottom: 2px solid #90CAF9; 
                box-shadow: 0 2px 8px rgba(0, 0, 0, 0.15);
            """)
            header_layout = QHBoxLayout(header_widget)
            header_layout.setContentsMargins(10, 0, 10, 0)
            logo_label = QLabel("● SmartPoster")
            logo_label.setFont(QFont("Segoe UI", 26, QFont.Bold))
            logo_label.setStyleSheet("""
                color: #FFFFFF; 
                text-shadow: 2px 2px 6px rgba(0, 0, 0, 0.3); 
                padding: 10px;
            """)
            header_layout.addWidget(logo_label)
            header_layout.addStretch()
            tabs = ["Settings", "Accounts", "Groups", "Publish", "Add Members", "Analytics", "Logs"]
            for tab in tabs:
                btn = QPushButton(tab)
                btn.setFont(QFont("Segoe UI", 12, QFont.Bold))
                btn.setStyleSheet("""
                    QPushButton { 
                        background: transparent; 
                        color: #FFFFFF; 
                        padding: 10px 20px; 
                        border: none; 
                        font-size: 15px; 
                        border-radius: 12px; 
                    }
                    QPushButton:hover { 
                        background: #64B5F6; 
                        transition: background 0.3s ease; 
                    }
                """)
                btn.clicked.connect(lambda checked, t=tab: self.switch_tab(t))
                header_layout.addWidget(btn)
            main_layout.addWidget(header_widget)

            # Main Content Area
            content_widget = QWidget()
            content_layout = QHBoxLayout(content_widget)
            content_layout.setContentsMargins(10, 10, 10, 10)
            content_layout.setSpacing(15)

            # Sidebar
            self.sidebar = QWidget()
            self.sidebar.setFixedWidth(250)
            self.sidebar.setStyleSheet("""
                background: #F5F9FC; 
                border-right: 2px solid #BBDEFB; 
                box-shadow: 4px 0 10px rgba(0, 0, 0, 0.08); 
                padding: 12px; 
                border-radius: 8px;
            """)
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
                    btn.setStyleSheet("""
                        QPushButton { 
                            background: #1E88E5; 
                            color: #FFFFFF; 
                            padding: 10px; 
                            border: none; 
                            border-radius: 8px; 
                            font-size: 14px; 
                            margin-bottom: 8px; 
                            box-shadow: 0 3px 6px rgba(0, 0, 0, 0.15); 
                        }
                        QPushButton:hover { 
                            background: #42A5F5; 
                            box-shadow: 0 5px 10px rgba(66, 165, 245, 0.3); 
                            transition: all 0.3s ease; 
                        }
                    """)
                    btn.clicked.connect(lambda checked, i=item: self.switch_tab(i))
                    sidebar_layout.addWidget(btn)
            sidebar_layout.addStretch()
            content_layout.addWidget(self.sidebar)

            # Tabbed Content
            self.content_stack = QTabWidget()
            self.content_stack.setStyleSheet("""
                QTabWidget::pane { 
                    border: 1px solid #BBDEFB; 
                    border-radius: 6px; 
                    background: #F5F9FC; 
                }
                QTabBar::tab { 
                    background: #E3F2FD; 
                    color: #1E3A8A; 
                    padding: 10px 20px; 
                    border-top-left-radius: 6px; 
                    border-top-right-radius: 6px; 
                    font-size: 14px; 
                    font-weight: bold; 
                }
                QTabBar::tab:selected { 
                    background: #1E88E5; 
                    color: #FFFFFF; 
                }
                QTabBar::tab:hover { 
                    background: #42A5F5; 
                }
            """)
            content_layout.addWidget(self.content_stack)

            # Settings Tab
            settings_tab = QWidget()
            settings_layout = QVBoxLayout(settings_tab)
            settings_layout.setSpacing(20)
            settings_group = QGroupBox("Settings")
            settings_group.setFont(QFont("Segoe UI", 16, QFont.Bold))
            settings_group.setStyleSheet("""
                QGroupBox { 
                    color: #1E3A8A; 
                    border: 1px solid #BBDEFB; 
                    border-radius: 6px; 
                    background: #FFFFFF; 
                    padding: 12px; 
                    box-shadow: 0 4px 12px rgba(0, 0, 0, 0.1); 
                }
            """)
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
            self.save_settings_button.setStyleSheet("""
                QPushButton { 
                    background: #1E88E5; 
                    color: #FFFFFF; 
                    padding: 10px; 
                    border-radius: 12px; 
                    box-shadow: 0 3px 6px rgba(0, 0, 0, 0.15); 
                }
                QPushButton:hover { 
                    background: #42A5F5; 
                    box-shadow: 0 5px 10px rgba(66, 165, 245, 0.3); 
                    transition: all 0.3s ease; 
                }
            """)
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

            # Accounts Tab
            accounts_tab = QWidget()
            accounts_layout = QVBoxLayout(accounts_tab)
            accounts_layout.setSpacing(20)
            accounts_group = QGroupBox("Accounts Control")
            accounts_group.setFont(QFont("Segoe UI", 16, QFont.Bold))
            accounts_group.setStyleSheet("""
                QGroupBox { 
                    color: #1E3A8A; 
                    border: 1px solid #BBDEFB; 
                    border-radius: 6px; 
                    background: #FFFFFF; 
                    padding: 12px; 
                    box-shadow: 0 4px 12px rgba(0, 0, 0, 0.1); 
                }
            """)
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
                btn.setStyleSheet("""
                    QPushButton { 
                        background: #1E88E5; 
                        color: #FFFFFF; 
                        padding: 10px; 
                        border-radius: 12px; 
                        box-shadow: 0 3px 6px rgba(0, 0, 0, 0.15); 
                    }
                    QPushButton:hover { 
                        background: #42A5F5; 
                        box-shadow: 0 5px 10px rgba(66, 165, 245, 0.3); 
                        transition: all 0.3s ease; 
                    }
                """)
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
            self.accounts_table.setStyleSheet("""
                QTableWidget { 
                    border: 1px solid #BBDEFB; 
                    border-radius: 6px; 
                    background: #FFFFFF; 
                } 
                QTableWidget::item:selected { 
                    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #E3F2FD, stop:1 #BBDEFB); 
                } 
                QHeaderView::section { 
                    background: #1E88E5; 
                    color: #FFFFFF; 
                    padding: 8px; 
                    border: none; 
                    font-weight: bold; 
                }
            """)
            accounts_pagination = QHBoxLayout()
            self.accounts_prev_button = QPushButton("◄ Previous")
            self.accounts_next_button = QPushButton("Next ►")
            self.accounts_page_label = QLabel("Page 1")
            self.accounts_page_label.setStyleSheet("color: #1E3A8A; font-size: 14px;")
            for btn in [self.accounts_prev_button, self.accounts_next_button]:
                btn.setFont(QFont("Segoe UI", 12))
                btn.setStyleSheet("""
                    QPushButton { 
                        background: #1E88E5; 
                        color: #FFFFFF; 
                        padding: 8px; 
                        border-radius: 8px; 
                    }
                    QPushButton:hover { 
                        background: #42A5F5; 
                        transition: all 0.3s ease; 
                    }
                """)
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

            # Groups Tab
            groups_tab = QWidget()
            groups_layout = QVBoxLayout(groups_tab)
            groups_layout.setSpacing(20)
            groups_group = QGroupBox("Groups Control")
            groups_group.setFont(QFont("Segoe UI", 16, QFont.Bold))
            groups_group.setStyleSheet("""
                QGroupBox { 
                    color: #1E3A8A; 
                    border: 1px solid #BBDEFB; 
                    border-radius: 6px; 
                    background: #FFFFFF; 
                    padding: 12px; 
                    box-shadow: 0 4px 12px rgba(0, 0, 0, 0.1); 
                }
            """)
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
            self.apply_filter_button.setStyleSheet("""
                QPushButton { 
                    background: #1E88E5; 
                    color: #FFFFFF; 
                    padding: 10px; 
                    border-radius: 12px; 
                    box-shadow: 0 3px 6px rgba(0, 0, 0, 0.15); 
                }
                QPushButton:hover { 
                    background: #42A5F5; 
                    box-shadow: 0 5px 10px rgba(66, 165, 245, 0.3); 
                    transition: all 0.3s ease; 
                }
            """)
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
            for btn in [self.extract_groups_button, self.extract_joined_button, self.add_group_manually_button, self.save_groups_button, 
                        self.close_groups_browser_button, self.auto_approve_button, self.delete_posts_button]:
                btn.setFont(QFont("Segoe UI", 12))
                btn.setStyleSheet("""
                    QPushButton { 
                        background: #1E88E5; 
                        color: #FFFFFF; 
                        padding: 10px; 
                        border-radius: 12px; 
                        box-shadow: 0 3px 6px rgba(0, 0, 0, 0.15); 
                    }
                    QPushButton:hover { 
                        background: #42A5F5; 
                        box-shadow: 0 5px 10px rgba(66, 165, 245, 0.3); 
                        transition: all 0.3s ease; 
                    }
                """)
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
            self.groups_table.setStyleSheet("""
                QTableWidget { 
                    border: 1px solid #BBDEFB; 
                    border-radius: 6px; 
                    background: #FFFFFF; 
                } 
                QTableWidget::item:selected { 
                    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #E3F2FD, stop:1 #BBDEFB); 
                } 
                QHeaderView::section { 
                    background: #1E88E5; 
                    color: #FFFFFF; 
                    padding: 8px; 
                    border: none; 
                    font-weight: bold; 
                }
            """)
            groups_pagination = QHBoxLayout()
            self.groups_prev_button = QPushButton("◄ Previous")
            self.groups_next_button = QPushButton("Next ►")
            self.groups_page_label = QLabel("Page 1")
            self.groups_page_label.setStyleSheet("color: #1E3A8A; font-size: 14px;")
            for btn in [self.groups_prev_button, self.groups_next_button]:
                btn.setFont(QFont("Segoe UI", 12))
                btn.setStyleSheet("""
                    QPushButton { 
                        background: #1E88E5; 
                        color: #FFFFFF; 
                        padding: 8px; 
                        border-radius: 8px; 
                    }
                    QPushButton:hover { 
                        background: #42A5F5; 
                        transition: all 0.3s ease; 
                    }
                """)
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
            for btn in [self.use_selected_groups_button, self.select_all_groups_button, self.deselect_all_groups_button, 
                        self.custom_selection_button, self.refresh_groups_button, self.delete_groups_button, 
                        self.extract_users_button, self.join_new_groups_button, self.add_to_favorites_button, 
                        self.transfer_members_button, self.interact_members_button]:
                btn.setFont(QFont("Segoe UI", 12))
                btn.setStyleSheet("""
                    QPushButton { 
                        background: #1E88E5; 
                        color: #FFFFFF; 
                        padding: 8px 12px; 
                        border-radius: 10px; 
                        box-shadow: 0 3px 6px rgba(0, 0, 0, 0.15); 
                        margin-right: 5px; 
                    }
                    QPushButton:hover { 
                        background: #42A5F5; 
                        box-shadow: 0 5px 10px rgba(66, 165, 245, 0.3); 
                        transition: all 0.3s ease; 
                    }
                """)
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

            # Publish Tab
            publish_tab = QWidget()
            publish_layout = QVBoxLayout(publish_tab)
            publish_layout.setSpacing(20)
            publish_group = QGroupBox("Publish Control")
            publish_group.setFont(QFont("Segoe UI", 16, QFont.Bold))
            publish_group.setStyleSheet("""
                QGroupBox { 
                    color: #1E3A8A; 
                    border: 1px solid #BBDEFB; 
                    border-radius: 6px; 
                    background: #FFFFFF; 
                    padding: 12px; 
                    box-shadow: 0 4px 12px rgba(0, 0, 0, 0.1); 
                }
            """)
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
            for btn in [self.attach_photo_button, self.attach_video_button, self.schedule_timer_button, self.stop_switch_button, 
                        self.stop_after_posts_button, self.resume_button, self.publish_button, self.posted_messages_button]:
                btn.setFont(QFont("Segoe UI", 12))
                btn.setStyleSheet("""
                    QPushButton { 
                        background: #1E88E5; 
                        color: #FFFFFF; 
                        padding: 10px; 
                        border-radius: 12px; 
                        box-shadow: 0 3px 6px rgba(0, 0, 0, 0.15); 
                    }
                    QPushButton:hover { 
                        background: #42A5F5; 
                        box-shadow: 0 5px 10px rgba(66, 165, 245, 0.3); 
                        transition: all 0.3s ease; 
                    }
                """)
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
            self.scheduled_posts_table.setStyleSheet("""
                QTableWidget { 
                    border: 1px solid #BBDEFB; 
                    border-radius: 6px; 
                    background: #FFFFFF; 
                } 
                QTableWidget::item:selected { 
                    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #E3F2FD, stop:1 #BBDEFB); 
                } 
                QHeaderView::section { 
                    background: #1E88E5; 
                    color: #FFFFFF; 
                    padding: 8px; 
                    border: none; 
                    font-weight: bold; 
                }
            """)
            publish_layout.addWidget(QLabel("Publish", styleSheet="color: #1E88E5; font-size: 22px; font-weight: bold; padding: 12px;"))
            publish_layout.addWidget(publish_group)
            publish_layout.addWidget(QLabel("Scheduled Posts", styleSheet="color: #1E88E5; font-size: 16px; font-weight: bold; padding: 6px;"))
            publish_layout.addWidget(self.scheduled_posts_table, alignment=Qt.AlignCenter)
            publish_layout.addStretch()
            self.content_stack.addTab(publish_tab, "Publish")

            # Add Members Tab
            add_members_tab = QWidget()
            add_members_layout = QVBoxLayout(add_members_tab)
            add_members_layout.setSpacing(20)
            add_members_group = QGroupBox("Add Members Control")
            add_members_group.setFont(QFont("Segoe UI", 16, QFont.Bold))
            add_members_group.setStyleSheet("""
                QGroupBox { 
                    color: #1E3A8A; 
                    border: 1px solid #BBDEFB; 
                    border-radius: 6px; 
                    background: #FFFFFF; 
                    padding: 12px; 
                    box-shadow: 0 4px 12px rgba(0, 0, 0, 0.1); 
                }
            """)
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
            self.send_invites_button.setStyleSheet("""
                QPushButton { 
                    background: #1E88E5; 
                    color: #FFFFFF; 
                    padding: 10px; 
                    border-radius: 12px; 
                    box-shadow: 0 3px 6px rgba(0, 0, 0, 0.15); 
                }
                QPushButton:hover { 
                    background: #42A5F5; 
                    box-shadow: 0 5px 10px rgba(66, 165, 245, 0.3); 
                    transition: all 0.3s ease; 
                }
            """)
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

            # Analytics Tab
            analytics_tab = QWidget()
            analytics_layout = QVBoxLayout(analytics_tab)
            analytics_layout.setSpacing(20)
            analytics_group = QGroupBox("Analytics Dashboard")
            analytics_group.setFont(QFont("Segoe UI", 16, QFont.Bold))
            analytics_group.setStyleSheet("""
                QGroupBox { 
                    color: #1E3A8A; 
                    border: 1px solid #BBDEFB; 
                    border-radius: 6px; 
                    background: #FFFFFF; 
                    padding: 12px; 
                    box-shadow: 0 4px 12px rgba(0, 0, 0, 0.1); 
                }
            """)
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
                btn.setStyleSheet("""
                    QPushButton { 
                        background: #1E88E5; 
                        color: #FFFFFF; 
                        padding: 10px; 
                        border-radius: 12px; 
                        box-shadow: 0 3px 6px rgba(0, 0, 0, 0.15); 
                    }
                    QPushButton:hover { 
                        background: #42A5F5; 
                        box-shadow: 0 5px 10px rgba(66, 165, 245, 0.3); 
                        transition: all 0.3s ease; 
                    }
                """)
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
            self.stats_table.setStyleSheet("""
                QTableWidget { 
                    border: 1px solid #BBDEFB; 
                    border-radius: 6px; 
                    background: #FFFFFF; 
                } 
                QTableWidget::item:selected { 
                    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #E3F2FD, stop:1 #BBDEFB); 
                } 
                QHeaderView::section { 
                    background: #1E88E5; 
                    color: #FFFFFF; 
                    padding: 8px; 
                    border: none; 
                    font-weight: bold; 
                }
            """)
            self.active_groups_table = QTableWidget()
            self.active_groups_table.setColumnCount(5)
            self.active_groups_table.setHorizontalHeaderLabels(["Group ID", "Group Name", "Posts", "Invites", "Success Rate"])
            self.active_groups_table.setFixedSize(900, 200)
            self.active_groups_table.setStyleSheet("""
                QTableWidget { 
                    border: 1px solid #BBDEFB; 
                    border-radius: 6px; 
                    background: #FFFFFF; 
                } 
                QTableWidget::item:selected { 
                    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #E3F2FD, stop:1 #BBDEFB); 
                } 
                QHeaderView::section { 
                    background: #1E88E5; 
                    color: #FFFFFF; 
                    padding: 8px; 
                    border: none; 
                    font-weight: bold; 
                }
            """)
            analytics_layout.addWidget(QLabel("Analytics", styleSheet="color: #1E88E5; font-size: 22px; font-weight: bold; padding: 12px;"))
            analytics_layout.addWidget(analytics_group)
            analytics_layout.addWidget(QLabel("Campaign Statistics", styleSheet="color: #1E88E5; font-size: 16px; font-weight: bold; padding: 6px;"))
            analytics_layout.addWidget(self.stats_table, alignment=Qt.AlignCenter)
            analytics_layout.addWidget(QLabel("Active Groups", styleSheet="color: #1E88E5; font-size: 16px; font-weight: bold; padding: 6px;"))
            analytics_layout.addWidget(self.active_groups_table, alignment=Qt.AlignCenter)
            analytics_layout.addStretch()
            self.content_stack.addTab(analytics_tab, "Analytics")

            # Logs Tab
            logs_tab = QWidget()
            logs_layout = QVBoxLayout(logs_tab)
            logs_layout.setSpacing(20)
            self.logs_table = QTableWidget()
            self.logs_table.setColumnCount(7)
            self.logs_table.setHorizontalHeaderLabels(["ID", "Account ID", "Target", "Action", "Timestamp", "Status", "Details"])
            self.logs_table.setFixedSize(900, 300)
            self.logs_table.setStyleSheet("""
                QTableWidget { 
                    border: 1px solid #BBDEFB; 
                    border-radius: 6px; 
                    background: #FFFFFF; 
                } 
                QTableWidget::item:selected { 
                    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #E3F2FD, stop:1 #BBDEFB); 
                } 
                QHeaderView::section { 
                    background: #1E88E5; 
                    color: #FFFFFF; 
                    padding: 8px; 
                    border: none; 
                    font-weight: bold; 
                }
            """)
            logs_buttons = QHBoxLayout()
            self.refresh_logs_button = QPushButton("↻ Refresh Logs")
            self.clear_logs_button = QPushButton("Clear Logs")
            self.logs_prev_button = QPushButton("◄ Previous")
            self.logs_next_button = QPushButton("Next ►")
            self.logs_page_label = QLabel("Page 1")
            self.logs_page_label.setStyleSheet("color: #1E3A8A; font-size: 14px;")
            for btn in [self.refresh_logs_button, self.clear_logs_button, self.logs_prev_button, self.logs_next_button]:
                btn.setFont(QFont("Segoe UI", 12))
                btn.setStyleSheet("""
                    QPushButton { 
                        background: #1E88E5; 
                        color: #FFFFFF; 
                        padding: 8px; 
                        border-radius: 8px; 
                    }
                    QPushButton:hover { 
                        background: #42A5F5; 
                        transition: all 0.3s ease; 
                    }
                """)
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

            # Footer
            footer_widget = QWidget()
            footer_widget.setFixedHeight(80)
            footer_widget.setStyleSheet("""
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #E3F2FD, stop:1 #BBDEFB); 
                border-top: 2px solid #90CAF9; 
                box-shadow: 0 -2px 8px rgba(0, 0, 0, 0.15);
            """)
            footer_layout = QHBoxLayout(footer_widget)
            footer_layout.setContentsMargins(10, 0, 10, 0)
            self.progress_bar = QProgressBar()
            self.progress_bar.setFixedWidth(300)
            self.progress_bar.setStyleSheet("""
                QProgressBar { 
                    border: 1px solid #BBDEFB; 
                    border-radius: 6px; 
                    background: #FFFFFF; 
                    text-align: center; 
                    color: #1E3A8A; 
                    font-size: 12px;
                }
                QProgressBar::chunk { 
                    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #1E88E5, stop:1 #42A5F5); 
                    border-radius: 6px; 
                }
            """)
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

            # Signals Connections
            self.connect_signals()

            # Initial Updates
            self.update_accounts_table()
            self.update_groups_table()
            self.update_logs_table()
            self.update_scheduled_posts_table()
            self.update_accounts_list()
            self.update_targets_list()

            self._log("UI initialization completed", "Info")
        except Exception as e:
            error_message = f"Error initializing UI: {str(e)}\n{traceback.format_exc()}"
            self._log(error_message, "Error")
            QMessageBox.critical(self, "UI Error", f"Error initializing UI: {str(e)}")

        def connect_signals(self):
        """ربط الإشارات بالوظائف."""
        try:
            self.save_settings_button.clicked.connect(self.save_settings)
            self.add_accounts_button.clicked.connect(self.add_accounts)
            self.import_file_button.clicked.connect(self.import_accounts_file)
            self.login_all_button.clicked.connect(self.login_accounts_async)
            self.verify_login_button.clicked.connect(self.verify_login)
            self.close_browsers_button.clicked.connect(self.close_all_browsers)
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
            self.attach_photo_button.clicked.connect(self.attach_photo)
            self.attach_video_button.clicked.connect(self.attach_video)
            self.schedule_timer_button.clicked.connect(lambda: self.loop.create_task(self.schedule_post_async()))
            self.stop_switch_button.clicked.connect(self.stop_publishing)
            self.stop_after_posts_button.clicked.connect(self.stop_after_posts)
            self.resume_button.clicked.connect(self.resume_publishing)
            self.publish_button.clicked.connect(lambda: self.loop.create_task(self.post_content_async()))
            self.posted_messages_button.clicked.connect(self.show_posted_messages)
            self.send_invites_button.clicked.connect(lambda: self.loop.create_task(self.add_members_async()))
            self.refresh_logs_button.clicked.connect(self.update_logs_table)
            self.clear_logs_button.clicked.connect(self.clear_logs)
            self.suggest_post_button_analytics.clicked.connect(self.suggest_post)
            self.view_stats_button.clicked.connect(self.view_campaign_stats)
            self.optimize_schedule_button.clicked.connect(self.optimize_posting_schedule)
            self.active_groups_button.clicked.connect(self.identify_active_groups)
            self.accounts_prev_button.clicked.connect(lambda: self.update_accounts_table(direction="prev"))
            self.accounts_next_button.clicked.connect(lambda: self.update_accounts_table(direction="next"))
            self.groups_prev_button.clicked.connect(lambda: self.update_groups_table(direction="prev"))
            self.groups_next_button.clicked.connect(lambda: self.update_groups_table(direction="next"))
            self.logs_prev_button.clicked.connect(lambda: self.update_logs_table(direction="prev"))
            self.logs_next_button.clicked.connect(lambda: self.update_logs_table(direction="next"))

            # Connect Signals from Components
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

            # Timer for Periodic Updates
            self.timer = QTimer()
            self.timer.timeout.connect(self.update_logs_table)
            self.timer.timeout.connect(self.update_scheduled_posts_table)
            self.timer.timeout.connect(self.update_stats_label)
            self.timer.start(5000)  # تحديث كل 5 ثوانٍ

            self._log("Signals connected successfully", "Info")
        except Exception as e:
            error_message = f"Error connecting signals: {str(e)}\n{traceback.format_exc()}"
            self._log(error_message, "Error")
            QMessageBox.critical(self, "Signal Error", f"Error connecting signals: {str(e)}")

    def save_settings(self):
        """حفظ إعدادات المستخدم."""
        try:
            self.app.config_manager.set("2captcha_api_key", self.api_key_input.text())
            self.app.config_manager.set("default_delay", self.delay_input.value())
            self.app.config_manager.set("max_retries", self.max_retries_input.value())
            self.app.config_manager.set("proxies", [p.strip() for p in self.proxy_input.toPlainText().splitlines() if p.strip()])
            self.app.config_manager.set("phone_number", self.phone_input.text())
            self.app.config_manager.set("custom_scripts", [s.strip() for s in self.reply_scripts.toPlainText().splitlines() if s.strip()])
            self.app.config_manager.set("default_language", self.language_input.currentText())
            self._log("Settings saved successfully", "Info")
            self.show_message("Success", "Settings saved successfully.", "Information")
        except Exception as e:
            error_message = f"Error saving settings: {str(e)}\n{traceback.format_exc()}"
            self._log(error_message, "Error")
            self.show_message("Error", f"Error saving settings: {str(e)}", "Warning")

    def add_accounts(self):
        """إضافة حسابات جديدة."""
        try:
            accounts_text = self.accounts_input.toPlainText().strip()
            if not accounts_text:
                self.show_message("Input Error", "Please enter account details.", "Warning")
                return
            self.account_manager.add_accounts(accounts_text)
            self.accounts_page = 0
            self.update_accounts_table()
            self.update_accounts_list()
            self._log("Accounts added successfully", "Info")
            self.show_message("Success", "Accounts added successfully.", "Information")
        except Exception as e:
            error_message = f"Error adding accounts: {str(e)}\n{traceback.format_exc()}"
            self._log(error_message, "Error")
            self.show_message("Error", f"Error adding accounts: {str(e)}", "Warning")

    def import_accounts_file(self):
        """استيراد حسابات من ملف."""
        try:
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
            self._log("Accounts imported successfully from file", "Info")
            self.show_message("Success", "Accounts imported successfully from file.", "Information")
        except Exception as e:
            error_message = f"Error importing accounts: {str(e)}\n{traceback.format_exc()}"
            self._log(error_message, "Error")
            self.show_message("Error", f"Error importing accounts: {str(e)}", "Warning")

    def login_accounts_async(self):
        """بدء تسجيل الدخول بشكل غير متزامن."""
        try:
            self.loop.create_task(self._login_accounts())
            self._log("Login process started asynchronously", "Info")
        except Exception as e:
            error_message = f"Error starting login process: {str(e)}\n{traceback.format_exc()}"
            self._log(error_message, "Error")
            self.show_message("Error", f"Error starting login: {str(e)}", "Warning")

    async def _login_accounts(self):
        """تسجيل الدخول لجميع الحسابات."""
        try:
            selected_accounts = [self.accounts_table.item(row, 2).text() for row in range(self.accounts_table.rowCount()) if self.accounts_table.cellWidget(row, 0).isChecked()]
            if not selected_accounts:
                selected_accounts = [acc[0] for acc in self.db.get_accounts()]
            self._log(f"Logging in {len(selected_accounts)} accounts", "Info")
            await self.account_manager.login_all_accounts(
                login_mode=self.login_method.currentText(),
                preliminary_interaction=self.preliminary_interaction.isChecked(),
                mobile_view=self.mobile_view.isChecked(),
                visible=True
            )
            self.session_manager.close_all_drivers()
            self.update_accounts_table()
            self.update_accounts_list()
            self._log("Login process completed successfully", "Info")
            self.show_message("Success", "Login process completed successfully.", "Information")
        except Exception as e:
            error_message = f"Error during login: {str(e)}\n{traceback.format_exc()}"
            self._log(error_message, "Error")
            self.show_message("Error", f"Error during login: {str(e)}", "Warning")

    def verify_login(self):
        """التحقق من حالة تسجيل الدخول."""
        try:
            selected_accounts = [self.accounts_table.item(row, 2).text() for row in range(self.accounts_table.rowCount()) if self.accounts_table.cellWidget(row, 0).isChecked()]
            if not selected_accounts:
                self.show_message("Selection Error", "Please select accounts to verify.", "Warning")
                return
            for fb_id in selected_accounts:
                self.loop.create_task(self.account_manager.verify_login_status(fb_id))
            self.update_accounts_table()
            self._log("Login verification completed", "Info")
            self.show_message("Success", "Login verification completed.", "Information")
        except Exception as e:
            error_message = f"Error verifying login: {str(e)}\n{traceback.format_exc()}"
            self._log(error_message, "Error")
            self.show_message("Error", f"Error verifying login: {str(e)}", "Warning")

    def close_all_browsers(self):
        """إغلاق جميع المتصفحات."""
        try:
            self.account_manager.close_all_browsers()
            self._log("All browsers closed successfully", "Info")
            self.show_message("Success", "All browsers closed successfully.", "Information")
        except Exception as e:
            error_message = f"Error closing browsers: {str(e)}\n{traceback.format_exc()}"
            self._log(error_message, "Error")
            self.show_message("Error", f"Error closing browsers: {str(e)}", "Warning")

    async def extract_groups(self):
        """استخراج المجموعات."""
        try:
            keywords = self.search_groups_input.text().strip()
            self.statusUpdated.emit(f"Extracting groups with keywords: {keywords}...")
            await self.group_manager.extract_all_groups(keywords=keywords, fast_mode=False, interact=False)
            self.update_groups_table()
            self.update_targets_list()
            self._log("Groups extracted successfully", "Info")
            self.show_message("Success", "Groups extracted successfully.", "Information")
        except Exception as e:
            error_message = f"Error extracting groups: {str(e)}\n{traceback.format_exc()}"
            self._log(error_message, "Error")
            self.show_message("Error", f"Error extracting groups: {str(e)}", "Warning")

    async def extract_joined_groups(self):
        """استخراج المجموعات المنضم إليها."""
        try:
            self.statusUpdated.emit("Extracting joined groups...")
            await self.group_manager.extract_joined_groups()
            self.update_groups_table()
            self.update_targets_list()
            self._log("Joined groups extracted successfully", "Info")
            self.show_message("Success", "Joined groups extracted successfully.", "Information")
        except Exception as e:
            error_message = f"Error extracting joined groups: {str(e)}\n{traceback.format_exc()}"
            self._log(error_message, "Error")
            self.show_message("Error", f"Error extracting joined groups: {str(e)}", "Warning")

    def add_group_manually(self):
        """إضافة مجموعة يدويًا."""
        try:
            group_id = self.search_groups_input.text().strip()
            if not group_id:
                self.show_message("Input Error", "Please enter a group ID.", "Warning")
                return
            account_id = self.db.get_accounts()[0][0] if self.db.get_accounts() else None
            if not account_id:
                self.show_message("Error", "No accounts available.", "Warning")
                return
            self.db.add_group(account_id, group_id, "Manual Group", 0)
            self.update_groups_table()
            self.update_targets_list()
            self._log(f"Manually added group {group_id}", "Info")
            self.show_message("Success", f"Group {group_id} added successfully.", "Information")
        except Exception as e:
            error_message = f"Error adding group manually: {str(e)}\n{traceback.format_exc()}"
            self._log(error_message, "Error")
            self.show_message("Error", f"Error adding group manually: {str(e)}", "Warning")

    def save_groups(self):
        """حفظ المجموعات المحددة."""
        try:
            selected_groups = [self.groups_table.item(row, 3).text() for row in range(self.groups_table.rowCount()) if self.groups_table.cellWidget(row, 0).isChecked()]
            if not selected_groups:
                self.show_message("Selection Error", "Please select groups to save.", "Warning")
                return
            with open("groups_list.txt", "w", encoding="utf-8") as f:
                for group in selected_groups:
                    f.write(f"{group}\n")
            self._log(f"Saved {len(selected_groups)} groups to groups_list.txt", "Info")
            self.show_message("Success", f"Saved {len(selected_groups)} groups successfully.", "Information")
        except Exception as e:
            error_message = f"Error saving groups: {str(e)}\n{traceback.format_exc()}"
            self._log(error_message, "Error")
            self.show_message("Error", f"Error saving groups: {str(e)}", "Warning")

    def use_selected_groups(self):
        """استخدام المجموعات المحددة."""
        try:
            selected_groups = [self.groups_table.item(row, 3).text() for row in range(self.groups_table.rowCount()) if self.groups_table.cellWidget(row, 0).isChecked()]
            if not selected_groups:
                self.show_message("Selection Error", "Please select groups to use.", "Warning")
                return
            self.target_list.clear()
            for group_id in selected_groups:
                self.target_list.addItem(group_id)
            self._log(f"Selected {len(selected_groups)} groups for publishing", "Info")
            self.show_message("Success", f"Selected {len(selected_groups)} groups for publishing.", "Information")
        except Exception as e:
            error_message = f"Error using selected groups: {str(e)}\n{traceback.format_exc()}"
            self._log(error_message, "Error")
            self.show_message("Error", f"Error using selected groups: {str(e)}", "Warning")

    def select_all_groups(self):
        """تحديد كل المجموعات."""
        try:
            for row in range(self.groups_table.rowCount()):
                self.groups_table.cellWidget(row, 0).setChecked(True)
            self._log("All groups selected", "Info")
            self.statusUpdated.emit("All groups selected")
        except Exception as e:
            error_message = f"Error selecting all groups: {str(e)}\n{traceback.format_exc()}"
            self._log(error_message, "Error")
            self.show_message("Error", f"Error selecting all groups: {str(e)}", "Warning")

    def deselect_all_groups(self):
        """إلغاء تحديد كل المجموعات."""
        try:
            for row in range(self.groups_table.rowCount()):
                self.groups_table.cellWidget(row, 0).setChecked(False)
            self._log("All groups deselected", "Info")
            self.statusUpdated.emit("All groups deselected")
        except Exception as e:
            error_message = f"Error deselecting all groups: {str(e)}\n{traceback.format_exc()}"
            self._log(error_message, "Error")
            self.show_message("Error", f"Error deselecting all groups: {str(e)}", "Warning")

    def custom_group_selection(self):
        """تحديد مخصص للمجموعات."""
        try:
            self.show_message("Custom Selection", "Please manually check/uncheck groups in the table.", "Information")
            self._log("Custom group selection activated", "Info")
            self.statusUpdated.emit("Custom group selection activated")
        except Exception as e:
            error_message = f"Error in custom group selection: {str(e)}\n{traceback.format_exc()}"
            self._log(error_message, "Error")
            self.show_message("Error", f"Error in custom group selection: {str(e)}", "Warning")

    async def extract_group_users(self):
        """استخراج أعضاء المجموعة."""
        try:
            if self.groups_table.currentRow() == -1:
                self.show_message("Selection Error", "Please select a group to extract users from.", "Warning")
                return
            group_id = self.groups_table.item(self.groups_table.currentRow(), 3).text()
            self.statusUpdated.emit(f"Extracting users from group {group_id}...")
            member_ids = await self.group_manager.extract_group_members(group_id)
            self._log(f"Extracted {len(member_ids)} users from group {group_id}", "Info")
            self.show_message("Success", f"Extracted {len(member_ids)} users from group {group_id}.", "Information")
        except Exception as e:
            error_message = f"Error extracting group users: {str(e)}\n{traceback.format_exc()}"
            self._log(error_message, "Error")
            self.show_message("Error", f"Error extracting group users: {str(e)}", "Warning")

    async def join_new_groups(self):
        """الانضمام لمجموعات جديدة."""
        try:
            selected_groups = [self.groups_table.item(row, 3).text() for row in range(self.groups_table.rowCount()) if self.groups_table.cellWidget(row, 0).isChecked()]
            if not selected_groups:
                self.show_message("Selection Error", "Please select groups to join.", "Warning")
                return
            self.statusUpdated.emit(f"Joining {len(selected_groups)} new groups...")
            await self.group_manager.extract_all_groups(keywords=",".join(selected_groups), fast_mode=False, interact=True)
            self.groups_page = 0
            self.update_groups_table()
            self.update_targets_list()
            self._log(f"Finished joining {len(selected_groups)} groups", "Info")
            self.show_message("Success", f"Joined {len(selected_groups)} groups successfully.", "Information")
        except Exception as e:
            error_message = f"Error joining new groups: {str(e)}\n{traceback.format_exc()}"
            self._log(error_message, "Error")
            self.show_message("Error", f"Error joining new groups: {str(e)}", "Warning")

    def add_to_favorites(self):
        """إضافة المجموعات للمفضلة."""
        try:
            selected_groups = [self.groups_table.item(row, 3).text() for row in range(self.groups_table.rowCount()) if self.groups_table.cellWidget(row, 0).isChecked()]
            if not selected_groups:
                self.show_message("Selection Error", "Please select groups to add to favorites.", "Warning")
                return
            for group_id in selected_groups:
                self.db.update_group(group_id=group_id, status="Favorite")
            self.update_groups_table()
            self._log(f"Added {len(selected_groups)} groups to favorites", "Info")
            self.show_message("Success", f"Added {len(selected_groups)} groups to favorites.", "Information")
        except Exception as e:
            error_message = f"Error adding groups to favorites: {str(e)}\n{traceback.format_exc()}"
            self._log(error_message, "Error")
            self.show_message("Error", f"Error adding groups to favorites: {str(e)}", "Warning")

    def delete_selected_groups(self):
        """حذف المجموعات المحددة."""
        try:
            selected_groups = [self.groups_table.item(row, 3).text() for row in range(self.groups_table.rowCount()) if self.groups_table.cellWidget(row, 0).isChecked()]
            if not selected_groups:
                self.show_message("Selection Error", "Please select groups to delete.", "Warning")
                return
            reply = QMessageBox.question(self, "Confirm Delete", f"Are you sure you want to delete {len(selected_groups)} groups?", QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if reply == QMessageBox.Yes:
                for group_id in selected_groups:
                    self.db.delete_group(group_id)
                self.groups_page = 0
                self.update_groups_table()
                self.update_targets_list()
                self._log(f"Deleted {len(selected_groups)} selected groups", "Info")
                self.show_message("Success", "Selected groups deleted successfully.", "Information")
        except Exception as e:
            error_message = f"Error deleting selected groups: {str(e)}\n{traceback.format_exc()}"
            self._log(error_message, "Error")
            self.show_message("Error", f"Error deleting selected groups: {str(e)}", "Warning")

    def close_groups_browser(self):
        """إغلاق متصفحات المجموعات."""
        try:
            self.group_manager.session_manager.close_all_drivers()
            self._log("Groups browsers closed successfully", "Info")
            self.show_message("Success", "Groups browsers closed successfully.", "Information")
        except Exception as e:
            error_message = f"Error closing groups browsers: {str(e)}\n{traceback.format_exc()}"
            self._log(error_message, "Error")
            self.show_message("Error", f"Error closing groups browsers: {str(e)}", "Warning")

    async def auto_approve_requests(self):
        """الموافقة التلقائية على طلبات الانضمام."""
        try:
            if self.groups_table.currentRow() == -1:
                self.show_message("Selection Error", "Please select a group to auto-approve requests.", "Warning")
                return
            group_id = self.groups_table.item(self.groups_table.currentRow(), 3).text()
            self.statusUpdated.emit(f"Auto-approving requests for group {group_id}...")
            await self.group_manager.auto_approve_requests(group_id)
            self._log(f"Finished auto-approving requests for group {group_id}", "Info")
            self.show_message("Success", f"Auto-approval completed for group {group_id}.", "Information")
        except Exception as e:
            error_message = f"Error auto-approving requests: {str(e)}\n{traceback.format_exc()}"
            self._log(error_message, "Error")
            self.show_message("Error", f"Error auto-approving requests: {str(e)}", "Warning")

    async def delete_posts(self):
        """حذف المنشورات بدون تفاعل."""
        try:
            if self.groups_table.currentRow() == -1:
                self.show_message("Selection Error", "Please select a group to delete posts from.", "Warning")
                return
            group_id = self.groups_table.item(self.groups_table.currentRow(), 3).text()
            self.statusUpdated.emit(f"Deleting posts without interaction for group {group_id}...")
            await self.group_manager.delete_posts(group_id, criteria="no_interaction")
            self._log(f"Finished deleting posts for group {group_id}", "Info")
            self.show_message("Success", f"Posts without interaction deleted for group {group_id}.", "Information")
        except Exception as e:
            error_message = f"Error deleting posts: {str(e)}\n{traceback.format_exc()}"
            self._log(error_message, "Error")
            self.show_message("Error", f"Error deleting posts: {str(e)}", "Warning")

    async def transfer_members(self):
        """نقل الأعضاء بين مجموعتين."""
        try:
            selected_groups = [self.groups_table.item(row, 3).text() for row in range(self.groups_table.rowCount()) if self.groups_table.cellWidget(row, 0).isChecked()]
            if len(selected_groups) != 2:
                self.show_message("Selection Error", "Please select exactly two groups to transfer members between.", "Warning")
                return
            source_group, target_group = selected_groups
            self.statusUpdated.emit(f"Transferring members from {source_group} to {target_group}...")
            await self.group_manager.transfer_members_between_groups(source_group, target_group)
            self._log(f"Finished transferring members from {source_group} to {target_group}", "Info")
            self.show_message("Success", f"Members transferred from {source_group} to {target_group}.", "Information")
        except Exception as e:
            error_message = f"Error transferring members: {str(e)}\n{traceback.format_exc()}"
            self._log(error_message, "Error")
            self.show_message("Error", f"Error transferring members: {str(e)}", "Warning")

    async def interact_with_members(self):
        """التفاعل مع أعضاء المجموعة."""
        try:
            if self.groups_table.currentRow() == -1:
                self.show_message("Selection Error", "Please select a group to interact with its members.", "Warning")
                return
            group_id = self.groups_table.item(self.groups_table.currentRow(), 3).text()
            self.statusUpdated.emit(f"Interacting with members of group {group_id}...")
            await self.group_manager.interact_with_members(group_id)
            self._log(f"Finished interacting with members of group {group_id}", "Info")
            self.show_message("Success", f"Interaction completed for group {group_id}.", "Information")
        except Exception as e:
            error_message = f"Error interacting with members: {str(e)}\n{traceback.format_exc()}"
            self._log(error_message, "Error")
            self.show_message("Error", f"Error interacting with members: {str(e)}", "Warning")

    def apply_group_filter(self):
        """تطبيق فلتر على المجموعات."""
        try:
            privacy_filter = self.filter_privacy.currentText()
            members_filter = self.filter_members.value()
            name_filter = self.filter_name.text().lower()
            status_filter = self.filter_status.currentText()
            filtered_groups = []
            account_id = self.db.get_accounts()[0][0] if self.db.get_accounts() else "default"
            for group in self.db.get_groups(account_id):
                group_id, account_id, group_name, privacy, _, _, _, member_count, status = group[1], group[2], group[3], group[4], group[5], group[6], group[7], group[8], group[9]
                privacy_text = "Closed" if privacy == 1 else "Open"
                if (privacy_filter == "All" or privacy_text == privacy_filter) and \
                   (members_filter == 0 or member_count <= members_filter) and \
                   (not name_filter or name_filter in group_name.lower()) and \
                   (status_filter == "All" or status == status_filter):
                    filtered_groups.append(group)
            self.groups_page = 0
            self.update_groups_table(filtered_groups)
            self._log("Group filter applied successfully", "Info")
            self.statusUpdated.emit("Group filter applied successfully")
        except Exception as e:
            error_message = f"Error applying group filter: {str(e)}\n{traceback.format_exc()}"
            self._log(error_message, "Error")
            self.show_message("Error", f"Error applying group filter: {str(e)}", "Warning")

    def attach_photo(self):
        """إرفاق صورة."""
        try:
            file_name, _ = QFileDialog.getOpenFileName(self, "Select Photo", "", "Image Files (*.jpg *.png *.jpeg)")
            if file_name:
                self.attachments.append(file_name)
                self.attachments_label.setText(f"Attached: {', '.join([os.path.basename(att) for att in self.attachments])}")
                self._log(f"Attached photo: {os.path.basename(file_name)}", "Info")
                self.statusUpdated.emit(f"Attached photo: {os.path.basename(file_name)}")
        except Exception as e:
            error_message = f"Error attaching photo: {str(e)}\n{traceback.format_exc()}"
            self._log(error_message, "Error")
            self.show_message("Error", f"Error attaching photo: {str(e)}", "Warning")

    def attach_video(self):
        """إرفاق فيديو."""
        try:
            file_name, _ = QFileDialog.getOpenFileName(self, "Select Video", "", "Video Files (*.mp4 *.avi *.mov)")
            if file_name:
                self.attachments.append(file_name)
                self.attachments_label.setText(f"Attached: {', '.join([os.path.basename(att) for att in self.attachments])}")
                self._log(f"Attached video: {os.path.basename(file_name)}", "Info")
                self.statusUpdated.emit(f"Attached video: {os.path.basename(file_name)}")
        except Exception as e:
            error_message = f"Error attaching video: {str(e)}\n{traceback.format_exc()}"
            self._log(error_message, "Error")
            self.show_message("Error", f"Error attaching video: {str(e)}", "Warning")

    async def post_content_async(self):
        """نشر المحتوى بشكل غير متزامن."""
        try:
            selected_accounts = [self.accounts_list.item(i).text() for i in range(self.accounts_list.count()) if self.accounts_list.item(i).isSelected()]
            selected_groups = [self.target_list.item(i).text() for i in range(self.target_list.count()) if self.target_list.item(i).isSelected()]
            if not selected_accounts:
                self.show_message("Selection Error", "Please select accounts to publish.", "Warning")
                return
            if not selected_groups and self.post_target_combo.currentText() == "Groups":
                self.show_message("Selection Error", "Please select groups to publish to.", "Warning")
                return
            timer = self.timer_input.time().toString("HH:mm")
            self.statusUpdated.emit("Starting publishing process...")
            self.progressUpdated.emit(0, len(selected_accounts) * (len(selected_groups) if selected_groups else 1))
            await self.post_manager.post_all_content(
                target=self.post_target_combo.currentText(),
                tech=self.post_tech_combo.currentText(),
                content=self.global_content_input.toPlainText(),
                per_account_content=None,
                global_content=self.global_content_input.toPlainText(),
                schedule_times=timer if self.timer_input.isEnabled() else None,
                allow_duplicates=self.allow_duplicates.isChecked(),
                spin_content_flag=self.spin_content_flag.isChecked(),
                delay=self.delay_spinbox.value(),
                timer=self.speed_spinbox.value() if self.random_time_checkbox.isChecked() else None,
                random_time=self.random_time_checkbox.isChecked(),
                stop_after_posts=self.stop_spinbox.value() if self.stop_unit_combo.currentText() == "Posts" else None,
                stop_unit=self.stop_unit_combo.currentText(),
                stop_every=self.every_spinbox.value(),
                resume_after=self.stop_spinbox.value() if self.stop_unit_combo.currentText() in ["Minutes", "Hours"] else None,
                resume_unit=self.stop_unit_combo.currentText(),
                silent_mode=False,
                selected_groups=selected_groups,
                selected_accounts=selected_accounts,
                attachments=self.attachments,
                auto_reply_enabled=self.auto_reply_checkbox.isChecked()
            )
            self.posted_count += len(selected_accounts) * (len(selected_groups) if selected_groups else 1)
            self.update_stats_label()
            self.attachments = []
            self.attachments_label.setText("No attachments selected")
            self._log("Publishing completed successfully", "Info")
            self.show_message("Success", "Publishing completed successfully.", "Information")
        except Exception as e:
            error_message = f"Error during publishing: {str(e)}\n{traceback.format_exc()}"
            self._log(error_message, "Error")
            self.show_message("Error", f"Error during publishing: {str(e)}", "Warning")

    async def schedule_post_async(self):
        """جدولة النشر بشكل غير متزامن."""
        try:
            selected_accounts = [self.accounts_list.item(i).text() for i in range(self.accounts_list.count()) if self.accounts_list.item(i).isSelected()]
            selected_groups = [self.target_list.item(i).text() for i in range(self.target_list.count()) if self.target_list.item(i).isSelected()]
            if not selected_accounts:
                self.show_message("Selection Error", "Please select accounts to schedule posts for.", "Warning")
                return
            if not selected_groups and self.post_target_combo.currentText() == "Groups":
                self.show_message("Selection Error", "Please select groups to schedule posts in.", "Warning")
                return
            content = self.global_content_input.toPlainText().strip()
            schedule_time = self.timer_input.time().toString("HH:mm")
            if not content or not schedule_time:
                self.show_message("Input Error", "Please provide content and schedule time.", "Warning")
                return
            self.statusUpdated.emit("Scheduling posts...")
            self.progressUpdated.emit(0, len(selected_accounts) * len(selected_groups))
            for fb_id in selected_accounts:
                for group_id in selected_groups:
                    await self.post_manager.schedule_post(fb_id, content, schedule_time, group_id=group_id, attachments=self.attachments)
            self.attachments = []
            self.attachments_label.setText("No attachments selected")
            self.update_scheduled_posts_table()
            self._log("Posts scheduled successfully", "Info")
            self.show_message("Success", "Posts scheduled successfully.", "Information")
        except Exception as e:
            error_message = f"Error scheduling posts: {str(e)}\n{traceback.format_exc()}"
            self._log(error_message, "Error")
            self.show_message("Error", f"Error scheduling posts: {str(e)}", "Warning")

    def stop_publishing(self):
        """إيقاف النشر."""
        try:
            self.post_manager.stop_posting()
            self._log("Publishing stopped successfully", "Info")
            self.show_message("Success", "Publishing stopped successfully.", "Information")
        except Exception as e:
            error_message = f"Error stopping publishing: {str(e)}\n{traceback.format_exc()}"
            self._log(error_message, "Error")
            self.show_message("Error", f"Error stopping publishing: {str(e)}", "Warning")

    def stop_after_posts(self):
        """إيقاف النشر بعد عدد محدد من المنشورات."""
        try:
            self.post_manager.stop_after_posts = self.stop_spinbox.value()
            self._log(f"Set stop after {self.stop_spinbox.value()} posts", "Info")
            self.show_message("Success", f"Publishing will stop after {self.stop_spinbox.value()} posts.", "Information")
        except Exception as e:
            error_message = f"Error setting stop after posts: {str(e)}\n{traceback.format_exc()}"
            self._log(error_message, "Error")
            self.show_message("Error", f"Error setting stop after posts: {str(e)}", "Warning")

    def resume_publishing(self):
        """استئناف النشر."""
        try:
            self.post_manager.stop_flag = False
            self._log("Publishing resumed", "Info")
            self.show_message("Success", "Publishing resumed successfully.", "Information")
        except Exception as e:
            error_message = f"Error resuming publishing: {str(e)}\n{traceback.format_exc()}"
            self._log(error_message, "Error")
            self.show_message("Error", f"Error resuming publishing: {str(e)}", "Warning")

    def show_posted_messages(self):
        """عرض الرسائل المنشورة."""
        try:
            posted_items = self.db.get_scheduled_posts()  # Assuming this method exists in Database to fetch recent posts
            self.scheduled_posts_table.setRowCount(len(posted_items))
            for row, item in enumerate(posted_items):
                post_id, fb_id, content, time, account_id, group_id, post_type, status = item
                if status == "Posted":
                    self.scheduled_posts_table.setItem(row, 0, QTableWidgetItem(str(post_id)))
                    self.scheduled_posts_table.setItem(row, 1, QTableWidgetItem(fb_id))
                    self.scheduled_posts_table.setItem(row, 2, QTableWidgetItem(content))
                    self.scheduled_posts_table.setItem(row, 3, QTableWidgetItem(time))
                    self.scheduled_posts_table.setItem(row, 4, QTableWidgetItem(group_id or ""))
                    self.scheduled_posts_table.setItem(row, 5, QTableWidgetItem(status))
            self.scheduled_posts_table.resizeColumnsToContents()
            self._log("Displayed posted messages", "Info")
            self.statusUpdated.emit("Displayed posted messages")
        except Exception as e:
            error_message = f"Error showing posted messages: {str(e)}\n{traceback.format_exc()}"
            self._log(error_message, "Error")
            self.show_message("Error", f"Error showing posted messages: {str(e)}", "Warning")

    async def add_members_async(self):
        """إرسال دعوات للأعضاء بشكل غير متزامن."""
        try:
            group_id = self.group_id_input.text().strip()
            member_ids = self.members_input.toPlainText().strip()
            selected_account = self.invite_account_combo.currentText()
            selected_targets = [self.invite_target_list.item(i).text() for i in range(self.invite_target_list.count()) if self.invite_target_list.item(i).isSelected()]
            if not group_id or not member_ids or not selected_account:
                self.show_message("Input Error", "Please enter Group ID, Member IDs, and select an account.", "Warning")
                return
            if not selected_targets:
                selected_targets = [group_id]
            self.statusUpdated.emit(f"Sending invites to group {group_id} from {selected_account}...")
            self.progressUpdated.emit(0, len(member_ids.splitlines()))
            await self.group_manager.add_members_to_group(group_id, member_ids)
            self._log("Invites sent successfully", "Info")
            self.show_message("Success", "Invites sent successfully.", "Information")
        except Exception as e:
            error_message = f"Error sending invites: {str(e)}\n{traceback.format_exc()}"
            self._log(error_message, "Error")
            self.show_message("Error", f"Error sending invites: {str(e)}", "Warning")

    def suggest_post(self):
        """اقتراح منشور."""
        try:
            keywords = self.keywords_input.text() if self.keywords_input.text() else "default"
            suggested_post = asyncio.run(self.analytics.suggest_post(keywords))
            self.global_content_input.setText(suggested_post)
            self.content_list.addItem(suggested_post)
            self._log(f"Suggested post: {suggested_post}", "Info")
            self.show_message("Success", f"Suggested post: {suggested_post}", "Information")
        except Exception as e:
            error_message = f"Error suggesting post: {str(e)}\n{traceback.format_exc()}"
            self._log(error_message, "Error")
            self.show_message("Error", f"Error suggesting post: {str(e)}", "Warning")

    def view_campaign_stats(self):
        """عرض إحصائيات الحملات."""
        try:
            stats = asyncio.run(self.analytics.get_campaign_stats())
            self.stats_table.setRowCount(len(stats))
            for row, stat in enumerate(stats):
                fb_id, posts, engagement, invites, extracted_members = stat
                self.stats_table.setItem(row, 0, QTableWidgetItem(fb_id))
                self.stats_table.setItem(row, 1, QTableWidgetItem(str(posts)))
                self.stats_table.setItem(row, 2, QTableWidgetItem(str(engagement)))
                self.stats_table.setItem(row, 3, QTableWidgetItem(str(invites)))
                self.stats_table.setItem(row, 4, QTableWidgetItem(str(extracted_members)))
            self.stats_table.resizeColumnsToContents()
            self._log("Campaign statistics updated", "Info")
            self.statusUpdated.emit("Campaign statistics updated")
        except Exception as e:
            error_message = f"Error viewing campaign stats: {str(e)}\n{traceback.format_exc()}"
            self._log(error_message, "Error")
            self.show_message("Error", f"Error viewing campaign stats: {str(e)}", "Warning")

    def optimize_posting_schedule(self):
        """تحسين جدولة النشر."""
        try:
            best_times = asyncio.run(self.analytics.optimize_posting_schedule())
            self.timer_input.setTime(QTime.fromString(best_times[0], "HH:mm"))
            self._log(f"Optimized posting schedule: {', '.join(best_times)}", "Info")
            self.show_message("Success", f"Optimized posting schedule: {', '.join(best_times)}", "Information")
        except Exception as e:
            error_message = f"Error optimizing posting schedule: {str(e)}\n{traceback.format_exc()}"
            self._log(error_message, "Error")
            self.show_message("Error", f"Error optimizing posting schedule: {str(e)}", "Warning")

    def identify_active_groups(self):
        """تحديد المجموعات النشطة."""
        try:
            active_groups = asyncio.run(self.analytics.identify_active_groups())
            self.active_groups_table.setRowCount(len(active_groups))
            for row, group in enumerate(active_groups):
                self.active_groups_table.setItem(row, 0, QTableWidgetItem(group["group_id"]))
                self.active_groups_table.setItem(row, 1, QTableWidgetItem(group["group_name"]))
                self.active_groups_table.setItem(row, 2, QTableWidgetItem(str(group["posts"])))
                self.active_groups_table.setItem(row, 3, QTableWidgetItem(str(group["invites"])))
                self.active_groups_table.setItem(row, 4, QTableWidgetItem(f"{group['success_rate']}%"))
            self.active_groups_table.resizeColumnsToContents()
            self._log(f"Identified {len(active_groups)} active groups", "Info")
            self.show_message("Success", f"Identified {len(active_groups)} active groups.", "Information")
        except Exception as e:
            error_message = f"Error identifying active groups: {str(e)}\n{traceback.format_exc()}"
            self._log(error_message, "Error")
            self.show_message("Error", f"Error identifying active groups: {str(e)}", "Warning")

    def update_status(self, message: str):
        """تحديث شريط الحالة."""
        try:
            self.status_label.setText(f"Status: {message}")
            QApplication.processEvents()
        except Exception as e:
            error_message = f"Error updating status: {str(e)}\n{traceback.format_exc()}"
            self._log(error_message, "Error")

    def update_progress(self, current: int, total: int):
        """تحديث شريط التقدم."""
        try:
            self.progress_bar.setMaximum(total)
            self.progress_bar.setValue(current)
            QApplication.processEvents()
        except Exception as e:
            error_message = f"Error updating progress: {str(e)}\n{traceback.format_exc()}"
            self._log(error_message, "Error")

    def update_stats_label(self):
        """تحديث ملصق الإحصائيات."""
        try:
            stats = asyncio.run(self.analytics.get_campaign_stats())
            total_posts = sum(stat[1] for stat in stats)
            total_accounts = len(self.db.get_accounts())
            total_groups = len(self.db.get_groups(self.db.get_accounts()[0][0] if self.db.get_accounts() else "default"))
            self.posted_count = total_posts
            self.stats_label.setText(f"Posted: {self.posted_count} | Engine: NO LIMIT | Accounts: {total_accounts} | Groups: {total_groups}")
            QApplication.processEvents()
        except Exception as e:
            error_message = f"Error updating stats label: {str(e)}\n{traceback.format_exc()}"
            self._log(error_message, "Error")

    def update_accounts_table(self, direction: Optional[str] = None):
        """تحديث جدول الحسابات."""
        try:
            accounts = self.db.get_accounts()
            total_accounts = len(accounts)
            if direction == "prev":
                self.accounts_page = max(0, self.accounts_page - 1)
            elif direction == "next":
                self.accounts_page = min((total_accounts - 1) // self.page_size, self.accounts_page + 1)
            start = self.accounts_page * self.page_size
            end = min(start + self.page_size, total_accounts)
            page_accounts = accounts[start:end]
            self.accounts_table.setRowCount(len(page_accounts))
            for row, account in enumerate(page_accounts):
                fb_id, password, email, proxy, access_token, cookies, status, last_login, login_attempts, is_developer = account
                self.accounts_table.setItem(row, 0, QTableWidgetItem())
                self.accounts_table.setItem(row, 1, QTableWidgetItem(str(start + row + 1)))
                self.accounts_table.setItem(row, 2, QTableWidgetItem(fb_id))
                self.accounts_table.setItem(row, 3, QTableWidgetItem(""))
                self.accounts_table.setItem(row, 4, QTableWidgetItem(password))
                self.accounts_table.setItem(row, 5, QTableWidgetItem(email))
                self.accounts_table.setItem(row, 6, QTableWidgetItem(""))
                self.accounts_table.setItem(row, 7, QTableWidgetItem(access_token or ""))
                self.accounts_table.setItem(row, 8, QTableWidgetItem(status))
                self.accounts_table.setItem(row, 9, QTableWidgetItem(""))
                self.accounts_table.setItem(row, 10, QTableWidgetItem(""))
                self.accounts_table.setItem(row, 11, QTableWidgetItem(proxy or ""))
                checkbox = QCheckBox()
                self.accounts_table.setCellWidget(row, 0, checkbox)
            self.accounts_table.resizeColumnsToContents()
            self.accounts_page_label.setText(f"Page {self.accounts_page + 1}")
            self._log("Accounts table updated", "Info")
        except Exception as e:
            error_message = f"Error updating accounts table: {str(e)}\n{traceback.format_exc()}"
            self._log(error_message, "Error")
            self.show_message("Error", f"Error updating accounts table: {str(e)}", "Warning")

    def update_groups_table(self, groups: Optional[List] = None, direction: Optional[str] = None):
        """تحديث جدول المجموعات."""
        try:
            if groups is None:
                account_id = self.db.get_accounts()[0][0] if self.db.get_accounts() else "default"
                groups = self.db.get_groups(account_id)
            total_groups = len(groups)
            if direction == "prev":
                self.groups_page = max(0, self.groups_page - 1)
            elif direction == "next":
                self.groups_page = min((total_groups - 1) // self.page_size, self.groups_page + 1)
            start = self.groups_page * self.page_size
            end = min(start + self.page_size, total_groups)
            page_groups = groups[start:end]
            self.groups_table.setRowCount(len(page_groups))
            for row, group in enumerate(page_groups):
                _, group_id, account_id, group_name, privacy, _, _, member_count, _ = group[1], group[2], group[3], group[4], group[5], group[6], group[7], group[8], group[9]
                self.groups_table.setItem(row, 0, QTableWidgetItem())
                self.groups_table.setItem(row, 1, QTableWidgetItem(str(start + row + 1)))
                self.groups_table.setItem(row, 2, QTableWidgetItem(group_name))
                self.groups_table.setItem(row, 3, QTableWidgetItem(group_id))
                self.groups_table.setItem(row, 4, QTableWidgetItem("Closed" if privacy == 1 else "Open"))
                self.groups_table.setItem(row, 5, QTableWidgetItem(str(member_count)))
                checkbox = QCheckBox()
                self.groups_table.setCellWidget(row, 0, checkbox)
            self.groups_table.resizeColumnsToContents()
            self.groups_page_label.setText(f"Page {self.groups_page + 1}")
            self._log("Groups table updated", "Info")
        except Exception as e:
            error_message = f"Error updating groups table: {str(e)}\n{traceback.format_exc()}"
            self._log(error_message, "Error")
            self.show_message("Error", f"Error updating groups table: {str(e)}", "Warning")

    def delete_group(self, group_id):
        """حذف مجموعة."""
        try:
            self.db.delete_group(group_id)
            self.update_groups_table()
            self.update_targets_list()
            self._log(f"Deleted group {group_id}", "Info")
            self.statusUpdated.emit(f"Deleted group {group_id}")
        except Exception as e:
            error_message = f"Error deleting group {group_id}: {str(e)}\n{traceback.format_exc()}"
            self._log(error_message, "Error")
            self.show_message("Error", f"Error deleting group {group_id}: {str(e)}", "Warning")

    def update_logs_table(self, direction: Optional[str] = None):
        """تحديث جدول السجلات."""
        try:
            logs = self.db.get_logs(limit=100)
            total_logs = len(logs)
            if direction == "prev":
                self.logs_page = max(0, self.logs_page - 1)
            elif direction == "next":
                self.logs_page = min((total_logs - 1) // self.page_size, self.logs_page + 1)
            start = self.logs_page * self.page_size
            end = min(start + self.page_size, total_logs)
            page_logs = logs[start:end]
            self.logs_table.setRowCount(len(page_logs))
            for row, log in enumerate(page_logs):
                log_id, fb_id, target, action, timestamp, status, details = log
                self.logs_table.setItem(row, 0, QTableWidgetItem(str(log_id)))
                self.logs_table.setItem(row, 1, QTableWidgetItem(fb_id or ""))
                self.logs_table.setItem(row, 2, QTableWidgetItem(target or ""))
                self.logs_table.setItem(row, 3, QTableWidgetItem(action or ""))
                self.logs_table.setItem(row, 4, QTableWidgetItem(str(timestamp or "")))
                self.logs_table.setItem(row, 5, QTableWidgetItem(status or ""))
                self.logs_table.setItem(row, 6, QTableWidgetItem(details or ""))
            self.logs_table.resizeColumnsToContents()
            self.logs_page_label.setText(f"Page {self.logs_page + 1}")
            self._log("Logs table updated", "Info")
        except Exception as e:
            error_message = f"Error updating logs table: {str(e)}\n{traceback.format_exc()}"
            self._log(error_message, "Error")
            self.show_message("Error", f"Error updating logs table: {str(e)}", "Warning")

    def clear_logs(self):
        """مسح السجلات."""
        try:
            reply = QMessageBox.question(self, "Confirm Clear", "Are you sure you want to clear all logs?", QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if reply == QMessageBox.Yes:
                self.log_manager.clear_logs()
                self.logs_page = 0
                self.update_logs_table()
                self._log("Logs cleared successfully", "Info")
                self.show_message("Success", "Logs cleared successfully.", "Information")
        except Exception as e:
            error_message = f"Error clearing logs: {str(e)}\n{traceback.format_exc()}"
            self._log(error_message, "Error")
            self.show_message("Error", f"Error clearing logs: {str(e)}", "Warning")

    def update_scheduled_posts_table(self):
        """تحديث جدول المنشورات المجدولة."""
        try:
            posts = self.db.get_scheduled_posts()
            self.scheduled_posts_table.setRowCount(len(posts))
            for row, post in enumerate(posts):
                post_id, fb_id, content, time, account_id, group_id, post_type, status = post
                self.scheduled_posts_table.setItem(row, 0, QTableWidgetItem(str(post_id)))
                self.scheduled_posts_table.setItem(row, 1, QTableWidgetItem(fb_id))
                self.scheduled_posts_table.setItem(row, 2, QTableWidgetItem(content))
                self.scheduled_posts_table.setItem(row, 3, QTableWidgetItem(time))
                self.scheduled_posts_table.setItem(row, 4, QTableWidgetItem(group_id or ""))
                self.scheduled_posts_table.setItem(row, 5, QTableWidgetItem(status))
            self.scheduled_posts_table.resizeColumnsToContents()
            self._log("Scheduled posts table updated", "Info")
        except Exception as e:
            error_message = f"Error updating scheduled posts table: {str(e)}\n{traceback.format_exc()}"
            self._log(error_message, "Error")
            self.show_message("Error", f"Error updating scheduled posts table: {str(e)}", "Warning")

    def update_accounts_list(self):
        """تحديث قائمة الحسابات."""
        try:
            self.accounts_list.clear()
            self.invite_account_combo.clear()
            for account in self.db.get_accounts():
                self.accounts_list.addItem(account[0])
                self.invite_account_combo.addItem(account[0])
            self._log("Accounts list updated", "Info")
        except Exception as e:
            error_message = f"Error updating accounts list: {str(e)}\n{traceback.format_exc()}"
            self._log(error_message, "Error")
            self.show_message("Error", f"Error updating accounts list: {str(e)}", "Warning")

    def update_targets_list(self):
        """تحديث قائمة الأهداف."""
        try:
            self.target_list.clear()
            self.invite_target_list.clear()
            account_id = self.db.get_accounts()[0][0] if self.db.get_accounts() else "default"
            for group in self.db.get_groups(account_id):
                group_id = group[2]
                self.target_list.addItem(group_id)
                self.invite_target_list.addItem(group_id)
            self._log("Targets list updated", "Info")
        except Exception as e:
            error_message = f"Error updating targets list: {str(e)}\n{traceback.format_exc()}"
            self._log(error_message, "Error")
            self.show_message("Error", f"Error updating targets list: {str(e)}", "Warning")

    def switch_tab(self, tab_name: str):
        """التبديل بين علامات التبويب."""
        try:
            tab_mapping = {
                "Settings": "Settings",
                "Accounts": "Accounts",
                "Groups": "Groups",
                "Publish": "Publish",
                "Add Members": "Add Members",
                "Analytics": "Analytics",
                "Logs": "Logs",
                "Add Batch": "Accounts",
                "Import File": "Accounts",
                "Login All": "Accounts",
                "Verify Login": "Accounts",
                "Close Browser": "Accounts",
                "Extract Joined Groups": "Groups",
                "Save": "Groups",
                "Schedule Post": "Publish",
                "Publish Now": "Publish",
                "Stop Publishing": "Publish",
                "Send Invites": "Add Members",
                "View Campaign Stats": "Analytics",
                "Suggest Post": "Analytics"
            }
            tab = tab_mapping.get(tab_name, tab_name)
            index = self.content_stack.indexOf(self.content_stack.findChild(QWidget, tab))
            if index != -1:
                self.content_stack.setCurrentIndex(index)
            if tab_name == "Login All":
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
            self._log(f"Switched to tab: {tab_name}", "Info")
        except Exception as e:
            error_message = f"Error switching tab: {str(e)}\n{traceback.format_exc()}"
            self._log(error_message, "Error")
            self.show_message("Error", f"Error switching tab: {str(e)}", "Warning")

    def show_message(self, title: str, message: str, icon: str):
        """عرض رسالة في واجهة المستخدم."""
        try:
            if icon == "Information":
                QMessageBox.information(self, title, message)
            elif icon == "Warning":
                QMessageBox.warning(self, title, message)
            elif icon == "Critical":
                QMessageBox.critical(self, title, message)
        except Exception as e:
            error_message = f"Error showing message: {str(e)}\n{traceback.format_exc()}"
            self._log(error_message, "Error")
            print(error_message)  # Fallback in case QMessageBox fails

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = SmartPosterUI()
    window.show()
    sys.exit(app.exec_())
