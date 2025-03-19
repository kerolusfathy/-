import sys
import asyncio
import os
import shutil
from PyQt5.QtWidgets import QApplication, QMessageBox
from PyQt5.QtCore import QThreadPool, QTimer, Qt
import traceback
from ui_design import SmartPosterUI
from database import Database
from account_manager import AccountManager
from group_manager import GroupManager
from post_manager import PostManager
from log_manager import LogManager
from config_manager import ConfigManager
from ai_analytics import AIAnalytics
from utils import SessionManager

class SmartPosterApp:
    """التطبيق الرئيسي لـ SmartPoster."""
    def __init__(self):
        try:
            if QApplication.instance() is None:
                self.app = QApplication(sys.argv)
            else:
                self.app = QApplication.instance()
            self.config_manager = ConfigManager()
            self.db = Database(self)
            self.db.init_db()  # إضافة تهيئة قاعدة البيانات
            self.log_manager = LogManager(self, self.db)
            self.session_manager = SessionManager(self, self.config_manager)
            self.account_manager = AccountManager(self, self.config_manager, self.db, self.log_manager)
            self.group_manager = GroupManager(self, self.db, self.session_manager, self.config_manager, self.log_manager)
            self.post_manager = PostManager(self, self.db, self.session_manager, self.config_manager, self.log_manager)
            self.ai_analytics = AIAnalytics(self, self.config_manager, self.db, self.log_manager)
            self.ui = SmartPosterUI(self)
            self.config_manager.load_config("config.json")  # تحميل الإعدادات
            self.loop = asyncio.get_event_loop() if asyncio.get_event_loop().is_running() else asyncio.new_event_loop()
            asyncio.set_event_loop(self.loop)
            self.threadpool = QThreadPool()
            self.threadpool.setMaxThreadCount(self.config_manager.get("max_sessions", 3))
            self.proxy_index = {}
            self.running_tasks = []
            self._log("SmartPosterApp initialized successfully", "Info")
            self.ui.connect_signals()  # ربط الـ Signals مع الـ UI
        except Exception as e:
            error_message = f"Failed to initialize SmartPosterApp: {str(e)}\n{traceback.format_exc()}"
            self._log(error_message, "Error")
            if QApplication.instance():
                QMessageBox.critical(None, "Initialization Error", error_message)
            raise

    def _log(self, message: str, level: str, fb_id: str = "System", action: str = "App") -> None:
        """تسجيل الرسائل باستخدام log_manager."""
        try:
            sanitized_message = self._sanitize_input(message)
            sanitized_fb_id = self._sanitize_input(fb_id)
            sanitized_action = self._sanitize_input(action)
            if hasattr(self, 'log_manager') and self.log_manager:
                self.log_manager.add_log(sanitized_fb_id, None, sanitized_action, level, sanitized_message)
            else:
                with open("fallback.log", "a", encoding="utf-8") as f:
                    f.write(f"[{level}] {sanitized_action}: {sanitized_message}\n")
        except Exception as e:
            with open("fallback.log", "a", encoding="utf-8") as f:
                f.write(f"Error logging in SmartPosterApp: {str(e)}\n{traceback.format_exc()}\n")

    def _sanitize_input(self, value: str) -> str:
        """تنظيف المدخلات لمنع SQL Injection."""
        if value is None:
            return ""
        return str(value).replace("'", "''").replace(";", "").strip()

    async def rotate_proxy(self, session_id: str) -> str | None:
        """تدوير البروكسيات بناءً على السجلات."""
        try:
            proxies = self.config_manager.get("proxies", [])
            if not proxies:
                self._log("No proxies available", "Warning", session_id)
                return None
            if session_id not in self.proxy_index:
                self.proxy_index[session_id] = 0
            else:
                logs = self.db.get_logs(action="Login Failed", limit=10)
                if len([log for log in logs if log[2] == session_id]) > 2:
                    self.proxy_index[session_id] = (self.proxy_index[session_id] + 1) % len(proxies)
            proxy = proxies[self.proxy_index[session_id]]
            self._log(f"Rotated proxy for {session_id}: {proxy}", "Info", session_id)
            return proxy
        except Exception as e:
            error_message = f"Error rotating proxy for {session_id}: {str(e)}\n{traceback.format_exc()}"
            self._log(error_message, "Error", session_id)
            return None

    def start_task(self, coro):
        """تشغيل مهمة متزامنة بشكل آمن مع PyQt."""
        try:
            if self.loop.is_closed():
                self.loop = asyncio.new_event_loop()
                asyncio.set_event_loop(self.loop)
            task = self.loop.create_task(coro)
            self.running_tasks.append(task)
            task.add_done_callback(lambda t: self._task_finished(t))
            self._log(f"Started task: {coro.__name__}", "Info")
            return task
        except Exception as e:
            error_message = f"Error starting task: {str(e)}\n{traceback.format_exc()}"
            self._log(error_message, "Error")
            if QApplication.instance():
                QMessageBox.critical(None, "Task Error", error_message)
            return None

    def _task_finished(self, task):
        """معالجة انتهاء المهمة."""
        try:
            if task in self.running_tasks:
                self.running_tasks.remove(task)
            if task.exception() is not None:
                error_message = f"Task failed: {str(task.exception())}\n{traceback.format_exc()}"
                self._log(error_message, "Error")
                if QApplication.instance():
                    QMessageBox.critical(None, "Task Failed", f"Task failed: {str(task.exception())}")
            else:
                self._log(f"Task completed: {task.get_coro().__name__}", "Info")
        except Exception as e:
            error_message = f"Error handling task finish: {str(e)}\n{traceback.format_exc()}"
            self._log(error_message, "Error")

    async def initial_setup(self):
        """تهيئة أولية للبرنامج، تشمل استخراج المجموعات المنضم إليها."""
        try:
            self._backup_database()
            self._log("Starting initial setup: Extracting joined groups", "Info")
            await self.group_manager.extract_joined_groups()
            self._log("Initial setup completed successfully", "Info")
            self.ui.statusUpdated.emit("Initial setup completed!")
            if QApplication.instance():
                QMessageBox.information(None, "Success", "Initial setup completed!")
        except Exception as e:
            error_message = f"Initial setup failed: {str(e)}\n{traceback.format_exc()}"
            self._log(error_message, "Error")
            self.ui.statusUpdated.emit(f"Initial setup failed: {str(e)}")
            if QApplication.instance():
                QMessageBox.critical(None, "Error", f"Initial setup failed: {str(e)}")

    def _backup_database(self):
        """إنشاء نسخة احتياطية من قاعدة البيانات."""
        try:
            db_path = 'smart_poster.db'
            usage = shutil.disk_usage(os.path.dirname(os.path.abspath(__file__)))
            if usage.free < 10 * 1024 * 1024:  # 10 MB
                self._log("Insufficient disk space for database backup", "Warning")
                return
            backup_path = f"{db_path}.backup"
            shutil.copy2(db_path, backup_path)
            self._log(f"Database backed up to {backup_path}", "Info")
        except Exception as e:
            self._log(f"Error backing up database: {str(e)}\n{traceback.format_exc()}", "Error")

    def cleanup(self):
        """تنظيف الموارد عند إغلاق التطبيق."""
        try:
            for task in self.running_tasks:
                if not task.done():
                    task.cancel()
                    try:
                        self.loop.run_until_complete(asyncio.wait_for(task, timeout=5))
                    except asyncio.TimeoutError:
                        self._log(f"Task {task.get_coro().__name__} cancellation timed out", "Warning")
            self.threadpool.waitForDone(5000)
            self.session_manager.close_all_drivers()
            self.db.close()
            if not self.loop.is_closed():
                self.loop.close()
            self._log("Application resources cleaned up", "Info")
            self.ui.statusUpdated.emit("Application resources cleaned up")
        except Exception as e:
            error_message = f"Error during cleanup: {str(e)}\n{traceback.format_exc()}"
            self._log(error_message, "Error")
            self.ui.statusUpdated.emit(f"Error during cleanup: {str(e)}")

    def run(self):
        """تشغيل التطبيق."""
        try:
            self.ui.show()
            self.start_task(self.initial_setup())
            self.loop_timer = QTimer()
            self.loop_timer.timeout.connect(self._run_loop)
            self.loop_timer.start(10)
            self.app.aboutToQuit.connect(self.cleanup)
            sys.exit(self.app.exec_())
        except Exception as e:
            error_message = f"Error running SmartPosterApp: {str(e)}\n{traceback.format_exc()}"
            self._log(error_message, "Error")
            if QApplication.instance():
                QMessageBox.critical(None, "Run Error", error_message)
            raise

    def _run_loop(self):
        """تشغيل حلقة الأحداث بشكل آمن."""
        try:
            if not self.loop.is_running() and not self.loop.is_closed():
                self.loop.run_until_complete(asyncio.sleep(0))  # حلقة خفيفة
        except Exception as e:
            self._log(f"Error in loop timer: {str(e)}\n{traceback.format_exc()}", "Error")

if __name__ == "__main__":
    try:
        app = SmartPosterApp()
        app.run()
    except Exception as e:
        with open("fallback.log", "a", encoding="utf-8") as f:
            f.write(f"Application crashed: {str(e)}\n{traceback.format_exc()}\n")
        sys.exit(1)