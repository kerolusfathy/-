import os
import shutil
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any
from PyQt5.QtWidgets import QTableWidget, QTableWidgetItem, QPushButton, QMessageBox, QHBoxLayout, QApplication
from PyQt5.QtCore import pyqtSignal, QObject, Qt, QMetaObject, Q_ARG, QThreadPool, QRunnable
from PyQt5.QtCore import QCryptographicHash
import traceback
import logging
from logging.handlers import RotatingFileHandler

class LogUpdateWorker(QRunnable):
    """Worker لتحديث السجلات في خلفية باستخدام QThreadPool."""
    def __init__(self, log_manager, table, fb_id, action):
        super().__init__()
        self.log_manager = log_manager
        self.table = table
        self.fb_id = fb_id
        self.action = action

    def run(self):
        self.log_manager.update_logs_table(self.table, self.fb_id, self.action)

class LogManager(QObject):
    logsUpdated = pyqtSignal()
    statusUpdated = pyqtSignal(str)

    def __init__(self, app, db):
        super().__init__()
        try:
            self.app = app
            self.db = db
            self.base_dir = os.path.dirname(os.path.abspath(__file__))
            self.logs_dir = os.path.join(self.base_dir, "logs")
            os.makedirs(self.logs_dir, exist_ok=True)
            self.last_log_id = 0
            self.thread_pool = QThreadPool()  # لتحسين الأداء مع المهام المتعددة
            self.thread_pool.setMaxThreadCount(4)  # تحديد عدد الخيوط
            # إعداد log rotation
            self.logger = logging.getLogger("LogManager")
            handler = RotatingFileHandler(
                os.path.join(self.logs_dir, "log_manager.log"),
                maxBytes=10*1024*1024,  # 10 MB
                backupCount=5
            )
            handler.setFormatter(logging.Formatter("%(asctime)s - %(levelname)s - %(message)s"))
            self.logger.addHandler(handler)
            self.logger.setLevel(logging.INFO)
            self._log("LogManager initialized successfully", "Info")
        except Exception as e:
            error_message = f"Error initializing LogManager: {str(e)}\n{traceback.format_exc()}"
            self._log(error_message, "Error")
            raise

    def _sanitize_input(self, value: Any) -> str:
        """تنظيف المدخلات لمنع SQL Injection."""
        if value is None:
            return ""
        return str(value).replace("'", "''").replace(";", "").strip()

    def _log(self, message: str, level: str, fb_id: str = "System", action: str = "LogManager") -> None:
        try:
            sanitized_message = self._sanitize_input(message)
            sanitized_fb_id = self._sanitize_input(fb_id)
            sanitized_action = self._sanitize_input(action)
            self.db.add_log(sanitized_fb_id, None, sanitized_action, level, sanitized_message)
            self.logger.log(getattr(logging, level.upper()), f"{sanitized_fb_id} - {sanitized_action}: {sanitized_message}")
            self.statusUpdated.emit(f"{level}: {sanitized_message}")
        except Exception as e:
            error_message = f"Error logging internally: {str(e)}\n{traceback.format_exc()}"
            with open(os.path.join(self.logs_dir, "fallback.log"), "a", encoding="utf-8") as f:
                f.write(f"[{datetime.now()}] {error_message}\n")
            print(error_message)

    def add_log(self, fb_id: str, target: Optional[str], action: str, level: str, message: str) -> None:
        try:
            sanitized_fb_id = self._sanitize_input(fb_id)
            sanitized_target = self._sanitize_input(target)
            sanitized_action = self._sanitize_input(action)
            sanitized_message = self._sanitize_input(message)
            # تشفير الرسالة لو كانت حساسة
            hashed_message = QCryptographicHash.hash(sanitized_message.encode(), QCryptographicHash.Sha256).hex() if "password" in sanitized_message.lower() else sanitized_message
            self.db.add_log(sanitized_fb_id, sanitized_target, sanitized_action, level, hashed_message)
            log_file = os.path.join(self.logs_dir, f"{datetime.now().strftime('%Y-%m-%d')}.log")
            if os.path.isfile(log_file) and os.path.getsize(log_file) > 5*1024*1024:  # 5 MB حد
                self._log("Log file size exceeds limit, rotating...", "Warning")
                os.rename(log_file, f"{log_file}.old")
            # التحقق من مساحة التخزين
            usage = shutil.disk_usage(self.logs_dir)
            if usage.free < 1024*1024:  # أقل من 1 MB متاح
                self._log("Low disk space detected", "Warning")
                raise RuntimeError("Insufficient disk space")
            with open(log_file, "a", encoding="utf-8") as f:
                f.write(f"[{datetime.now()}] {level} - {sanitized_fb_id} - {sanitized_action}: {hashed_message}\n")
            self.logsUpdated.emit()
            self.statusUpdated.emit(f"{level}: {hashed_message}")
            self._log(f"Added log: {hashed_message}", "Info", sanitized_fb_id, sanitized_action)
        except Exception as e:
            error_message = f"Error adding log: {str(e)}\n{traceback.format_exc()}"
            self._log(error_message, "Error", fb_id, action)
            raise

    def update_logs_table(self, table: QTableWidget, fb_id: Optional[str] = None, action: Optional[str] = None, offset: int = 0, limit: int = 100) -> None:
        try:
            table.setSortingEnabled(False)  # تعطيل الفرز لتحسين الأداء
            sanitized_fb_id = self._sanitize_input(fb_id)
            sanitized_action = self._sanitize_input(action)
            if not hasattr(self, 'last_log_id') or self.last_log_id == 0:
                logs = []
                try:
                    logs = self.db.get_logs(limit=limit, offset=offset, fb_id=sanitized_fb_id, action=sanitized_action)
                except Exception as e:
                    self._log(f"Error fetching logs: {str(e)}\n{traceback.format_exc()}", "Error")
                    if QApplication.instance():
                        QMessageBox.critical(None, "Error", f"Failed to fetch logs: {str(e)}")
                    return
                table.setRowCount(0)
            else:
                logs = []
                try:
                    logs = self.db.get_new_logs(self.last_log_id)
                except Exception as e:
                    self._log(f"Error fetching new logs: {str(e)}\n{traceback.format_exc()}", "Error")
                    if QApplication.instance():
                        QMessageBox.critical(None, "Error", f"Failed to fetch new logs: {str(e)}")
                    return

            current_rows = table.rowCount()
            table.setRowCount(current_rows + len(logs))
            if logs:
                table.setColumnCount(len(logs[0]))  # ديناميكي بناءً على البيانات
            else:
                table.setColumnCount(7)
            table.setHorizontalHeaderLabels(["ID", "Account ID", "Target", "Action", "Timestamp", "Status", "Details"])
            table.setStyleSheet("...")
            for i, log in enumerate(logs):
                row = current_rows + i
                for col, value in enumerate(log):
                    table.setItem(row, col, QTableWidgetItem(str(value or "")))
            table.resizeColumnsToContents()
            if logs and all(isinstance(log[0], (int, str)) for log in logs):
                self.last_log_id = max(int(log[0]) for log in logs)
            table.setSortingEnabled(True)  # إعادة تفعيل الفرز
            self.logsUpdated.emit()
            self._log(f"Updated logs table with {len(logs)} entries", "Info")
        except Exception as e:
            error_message = f"Error updating logs table: {str(e)}\n{traceback.format_exc()}"
            self._log(error_message, "Error")
            if QApplication.instance():
                QMessageBox.critical(None, "Error", f"Failed to update logs table: {str(e)}")

    def clear_logs(self) -> None:
        try:
            if QApplication.instance():
                reply = QMessageBox.question(
                    None, "Confirm Clear Logs", "Are you sure you want to clear all logs?",
                    QMessageBox.Yes | QMessageBox.No, QMessageBox.No
                )
                if reply != QMessageBox.Yes:
                    return
            self.db.clear_logs()
            for log_file in os.listdir(self.logs_dir):
                try:
                    os.remove(os.path.join(self.logs_dir, log_file))
                except PermissionError as e:
                    self._log(f"Permission denied while deleting {log_file}: {str(e)}", "Warning")
            self.last_log_id = 0
            self.logsUpdated.emit()
            self._log("Logs cleared successfully", "Info")
            if QApplication.instance():
                QMetaObject.invokeMethod(self.app.ui if hasattr(self.app, 'ui') else None,
                                        "show_message", Qt.QueuedConnection,
                                        Q_ARG(str, "Success"), Q_ARG(str, "Logs cleared"),
                                        Q_ARG(str, "Information"))
        except Exception as e:
            error_message = f"Error clearing logs: {str(e)}\n{traceback.format_exc()}"
            self._log(error_message, "Error")
            if QApplication.instance():
                QMessageBox.critical(None, "Error", f"Failed to clear logs: {str(e)}")

    def add_refresh_button(self, layout: QHBoxLayout, table: QTableWidget) -> None:
        try:
            refresh_button = QPushButton("Refresh Logs")
            refresh_button.setStyleSheet("...")
            refresh_button.clicked.connect(lambda: self.thread_pool.start(LogUpdateWorker(self, table, None, None)))
            layout.addWidget(refresh_button)
            self._log("Refresh button added to logs", "Info")
        except Exception as e:
            error_message = f"Error adding refresh button: {str(e)}\n{traceback.format_exc()}"
            self._log(error_message, "Error")
            raise

    def get_log_summary(self) -> Dict[str, Any]:
        try:
            logs = self.db.get_logs(limit=1000)
            summary = {
                "total_logs": len(logs),
                "success_count": len([log for log in logs if log[5] == "Success"]),
                "error_count": len([log for log in logs if log[5] == "Error"]),
                "warning_count": len([log for log in logs if log[5] == "Warning"]),
                "last_log_time": max((log[4] for log in logs), default="N/A") if logs else "N/A"
            }
            self._log(f"Generated log summary: {summary}", "Info")
            return summary
        except Exception as e:
            error_message = f"Error generating log summary: {str(e)}\n{traceback.format_exc()}"
            self._log(error_message, "Error")
            return {"total_logs": 0, "success_count": 0, "error_count": 0, "warning_count": 0, "last_log_time": "N/A"}

    def cleanup_old_logs(self, days: int = 30) -> None:
        """حذف السجلات القديمة تلقائيًا."""
        try:
            cutoff = datetime.now() - timedelta(days=days)
            for log_file in os.listdir(self.logs_dir):
                file_path = os.path.join(self.logs_dir, log_file)
                if os.path.isfile(file_path) and datetime.fromtimestamp(os.path.getmtime(file_path)) < cutoff:
                    os.remove(file_path)
                    self._log(f"Deleted old log file: {log_file}", "Info")
            self.db.cleanup_old_logs(days)  # يفترض أن Database لديه هذه الوظيفة
            self._log(f"Cleaned up logs older than {days} days", "Info")
        except Exception as e:
            self._log(f"Error cleaning up old logs: {str(e)}\n{traceback.format_exc()}", "Error")

if __name__ == "__main__":
    from PyQt5.QtWidgets import QApplication, QHBoxLayout, QWidget
    import sys
    app = QApplication(sys.argv)
    class DummyApp:
        class DummyUI:
            def show_message(self, title, message, icon):
                print(f"[{title}] {message}")
        ui = DummyUI()
    class DummyDatabase:
        def add_log(self, fb_id, target, action, level, message):
            print(f"DB Log: {fb_id} - {action} - {level}: {message}")
        def get_logs(self, limit=100, offset=0, fb_id=None, action=None):
            return [(i, "fb1", "target1", "Test", f"2023-01-01 00:00:{i:02d}", "Success", "Details") for i in range(1, min(limit, 10) + 1)]
        def get_new_logs(self, last_log_id):
            return [(last_log_id + 1, "fb1", "target1", "Test", "2023-01-01 00:00:01", "Success", "New Details")]
        def clear_logs(self):
            print("DB Logs cleared")
        def cleanup_old_logs(self, days):
            print(f"DB cleaned logs older than {days} days")
    log_manager = LogManager(DummyApp(), DummyDatabase())
    widget = QWidget()
    layout = QHBoxLayout(widget)
    table = QTableWidget()
    log_manager.add_log("fb1", "target1", "Test Action", "Success", "Test message")
    log_manager.update_logs_table(table)
    log_manager.add_refresh_button(layout, table)
    log_manager.cleanup_old_logs(30)
    widget.show()
    sys.exit(app.exec_())