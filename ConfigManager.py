# config_manager.py
import os
import json
import re
import traceback
import hashlib
from datetime import datetime
from typing import Dict, Any, Optional
from PyQt5.QtCore import pyqtSignal, QObject
import orjson  # لتحسين أداء JSON Parsing
from pathlib import Path
import logging
import logging.handlers
import shutil
from threading import Lock  # لدعم multi-threading

class ConfigManager(QObject):
    """
    كلاس لإدارة إعدادات التطبيق باستخدام ملف JSON.
    يدعم تحميل، حفظ، وتحديث الإعدادات مع التحقق من الصحة، النسخ الاحتياطي، والتكامل مع الواجهة.
    يضمن الاستقرار، الأمان، والأداء العالي لجميع وظائف البرنامج.
    """
    configUpdated = pyqtSignal()  # إشارة لإعلام المكونات بتحديث الإعدادات
    statusUpdated = pyqtSignal(str)  # إشارة لتحديث حالة الواجهة

    def __init__(self, app, config_file: str = "config.json", log_manager=None):
        """
        تهيئة ConfigManager مع التكامل مع التطبيق الرئيسي.

        Args:
            app: كائن SmartPosterApp للوصول إلى وظائف التطبيق.
            config_file (str): مسار ملف الإعدادات (افتراضي: config.json).
            log_manager: كائن LogManager لتسجيل الأحداث.
        """
        super().__init__()
        self.app = app
        self.base_dir = Path(os.path.dirname(os.path.abspath(__file__)))
        self.config_file = self.base_dir / config_file
        self.backup_dir = self.base_dir / "backups"
        self.log_manager = log_manager
        self.lock = Lock()  # لضمان عمليات كتابة آمنة في بيئة multi-threaded

        if not self.log_manager:
            raise ValueError("LogManager is required for ConfigManager")

        # الإعدادات الافتراضية مع تحسينات
        self.default_config: Dict[str, Any] = {
            "2captcha_api_key": "",                  # مفتاح API مشفر
            "default_delay": 5,                      # تأخير افتراضي (5-60 ثانية)
            "max_retries": 3,                        # أقصى محاولات (1-10)
            "proxies": [],                           # قائمة وكلاء
            "custom_scripts": [
                "Thanks for your comment! Contact us at 01225398839",
                "For more info, call 01225398839",
                "Great post! Reach out for details."
            ],
            "max_sessions": 5,                       # أقصى جلسات (1-10)
            "add_hashtags": True,
            "add_call_to_action": True,
            "default_language": "en",
            "max_group_members": 10000,              # أقصى أعضاء (100-1000000)
            "use_access_token": False,
            "app_id": "123456789012345",             # معرف تطبيق فيسبوك
            "backup_config": True,
            "chrome_path": "drivers/chrome.exe",
            "chromedriver_path": "drivers/chromedriver.exe",
            "mobile_size": "360x640",
            "chrome_version": "133",
            "post_delay": 10,                        # تأخير النشر (5-300 ثانية)
            "stop_after_posts": 10,                  # إيقاف بعد (1-1000)
            "predictive_ban_detection": True,
            "proxy_rotation_enabled": True,
            "auto_reply_enabled": True,
            "auto_reply_interval": 120,              # فاصل رد (5-300 ثانية)
            "phone_number": "01225398839",
            "last_modified": None                    # تتبع آخر تعديل
        }

        # إعداد التسجيل مع log rotation
        self.setup_logging()

        try:
            self.config = self.load_config()
            self._log("ConfigManager initialized successfully", "Info")
        except Exception as e:
            error_message = f"Failed to initialize ConfigManager: {str(e)}\n{traceback.format_exc()}"
            self._log(error_message, "Error")
            self.config = self.default_config.copy()
            self.save_config()

    def setup_logging(self):
        """إعداد التسجيل مع log rotation."""
        logging.basicConfig(
            filename=self.base_dir / "config_manager.log",
            level=logging.INFO,
            format="%(asctime)s - %(levelname)s - %(message)s",
            handlers=[logging.handlers.RotatingFileHandler(
                self.base_dir / "config_manager.log",
                maxBytes=10*1024*1024,  # 10 MB
                backupCount=5
            )]
        )
        self.logger = logging.getLogger(__name__)

    def _log(self, message: str, level: str, fb_id: str = "System", action: str = "Config") -> None:
        """تسجيل الرسائل مع معالجة الأخطاء وتحديث الواجهة."""
        try:
            full_message = f"{message} | Trace: {traceback.format_stack()[-2]}"
            self.log_manager.add_log(fb_id, None, action, level, full_message)
            self.logger.log(getattr(logging, level.upper()), full_message)
            self.statusUpdated.emit(f"{level}: {message}")
        except Exception as e:
            print(f"Error logging in ConfigManager: {str(e)}\n{traceback.format_exc()}")

    def load_config(self) -> Dict[str, Any]:
        """تحميل الإعدادات مع Lazy Loading ومعالجة الأخطاء."""
        try:
            # تحميل من environment variables للبيانات الحساسة
            self.default_config["2captcha_api_key"] = os.getenv("2CAPTCHA_API_KEY", self.default_config["2captcha_api_key"])
            self.default_config["app_id"] = os.getenv("APP_ID", self.default_config["app_id"])

            if not self.config_file.exists():
                self._log(f"No config file found at {self.config_file}, creating with defaults", "Warning")
                config = self.default_config.copy()
                self.save_config(config)
                return config

            with self.config_file.open("rb") as f:
                loaded_config = orjson.loads(f.read())  # استخدام orjson للأداء
            config = self.default_config.copy()
            config.update({k: v for k, v in loaded_config.items() if k in config})
            self.validate_config(config)
            self._log(f"Config loaded successfully from {self.config_file}", "Info")
            return config
        except json.JSONDecodeError as e:
            error_message = f"JSON decode error in {self.config_file}: {str(e)}\n{traceback.format_exc()}"
            self._log(error_message, "Error")
            return self.default_config.copy()
        except FileNotFoundError:
            self._log(f"Config file not found at {self.config_file}, using defaults", "Warning")
            config = self.default_config.copy()
            self.save_config(config)
            return config
        except Exception as e:
            error_message = f"Unexpected error loading config: {str(e)}\n{traceback.format_exc()}"
            self._log(error_message, "Error")
            return self.default_config.copy()

    def save_config(self, config: Optional[Dict[str, Any]] = None) -> None:
        """حفظ الإعدادات مع نسخة احتياطية وأمان."""
        with self.lock:
            try:
                config_to_save = config or self.config
                self.validate_config(config_to_save)
                config_to_save["last_modified"] = datetime.now().isoformat()

                # تشفير البيانات الحساسة
                if config_to_save["2captcha_api_key"]:
                    config_to_save["2captcha_api_key"] = hashlib.sha256(
                        config_to_save["2captcha_api_key"].encode()).hexdigest()

                # نسخة احتياطية
                if config_to_save.get("backup_config", True) and self.config_file.exists():
                    self.backup_dir.mkdir(exist_ok=True)
                    backup_file = self.backup_dir / f"config_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
                    shutil.copy2(self.config_file, backup_file)
                    self._log(f"Created config backup: {backup_file}", "Info")
                    self.cleanup_old_backups(max_backups=5)

                # حفظ باستخدام orjson
                start_time = datetime.now()
                with self.config_file.open("wb") as f:
                    f.write(orjson.dumps(config_to_save, option=orjson.OPT_INDENT_2))
                duration = (datetime.now() - start_time).total_seconds()
                self._log(f"Config saved successfully in {duration:.3f} seconds", "Info")
                self.configUpdated.emit()
            except PermissionError as e:
                error_message = f"Permission denied saving config: {str(e)}\n{traceback.format_exc()}"
                self._log(error_message, "Error")
                raise
            except Exception as e:
                error_message = f"Error saving config: {str(e)}\n{traceback.format_exc()}"
                self._log(error_message, "Error")
                raise

    def cleanup_old_backups(self, max_backups: int):
        """تنظيف النسخ الاحتياطية القديمة."""
        try:
            backups = sorted(self.backup_dir.glob("config_*.json"), key=os.path.getmtime)
            if len(backups) > max_backups:
                for old_backup in backups[:-max_backups]:
                    old_backup.unlink()
                    self._log(f"Removed old backup: {old_backup}", "Info")
        except Exception as e:
            self._log(f"Error cleaning up backups: {str(e)}\n{traceback.format_exc()}", "Error")

    def validate_config(self, config: Dict[str, Any]) -> None:
        """التحقق من صحة الإعدادات."""
        try:
            for key, default_value in self.default_config.items():
                value = config.get(key, default_value)
                # الأعداد الصحيحة الموجبة
                if key in ["default_delay", "post_delay", "auto_reply_interval"]:
                    if not isinstance(value, int) or not (5 <= value <= 300):
                        config[key] = default_value
                        self._log(f"Invalid {key}: {value}, must be 5-300, reset to {default_value}", "Warning")
                elif key in ["max_retries", "max_sessions"]:
                    if not isinstance(value, int) or not (1 <= value <= 10):
                        config[key] = default_value
                        self._log(f"Invalid {key}: {value}, must be 1-10, reset to {default_value}", "Warning")
                elif key == "max_group_members":
                    if not isinstance(value, int) or not (100 <= value <= 1000000):
                        config[key] = default_value
                        self._log(f"Invalid {key}: {value}, must be 100-1000000, reset to {default_value}", "Warning")
                elif key == "stop_after_posts":
                    if not isinstance(value, int) or not (1 <= value <= 1000):
                        config[key] = default_value
                        self._log(f"Invalid {key}: {value}, must be 1-1000, reset to {default_value}", "Warning")
                # القوائم
                elif key in ["proxies", "custom_scripts"]:
                    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
                        config[key] = default_value
                        self._log(f"Invalid {key}: {value}, must be list[str], reset to default", "Warning")
                # القيم المنطقية
                elif key in ["add_hashtags", "add_call_to_action", "use_access_token", "backup_config", 
                             "predictive_ban_detection", "proxy_rotation_enabled", "auto_reply_enabled"]:
                    if not isinstance(value, bool):
                        config[key] = default_value
                        self._log(f"Invalid {key}: {value}, must be bool, reset to {default_value}", "Warning")
                # السلاسل النصية
                elif key in ["2captcha_api_key", "default_language", "phone_number"]:
                    if not isinstance(value, str):
                        config[key] = default_value
                        self._log(f"Invalid {key}: {value}, must be str, reset to {default_value}", "Warning")
                elif key == "app_id":
                    if not isinstance(value, str) or not value.isdigit():
                        config[key] = default_value
                        self._log(f"Invalid {key}: {value}, must be numeric str, reset to {default_value}", "Warning")
                elif key in ["chrome_path", "chromedriver_path"]:
                    if not isinstance(value, str) or (value and not Path(self.base_dir / value).exists()):
                        self._log(f"Path for {key} invalid or not found: {value}, keeping but warning", "Warning")
                elif key == "mobile_size":
                    if not isinstance(value, str) or not re.match(r"^\d+x\d+$", value):
                        config[key] = default_value
                        self._log(f"Invalid {key}: {value}, must be WxH format, reset to {default_value}", "Warning")
                    else:
                        w, h = map(int, value.split("x"))
                        if not (100 <= w <= 2000 and 100 <= h <= 2000):
                            config[key] = default_value
                            self._log(f"Invalid {key} dimensions: {value}, must be 100-2000, reset to {default_value}", "Warning")
                elif key == "chrome_version":
                    if not isinstance(value, str) or not value.isdigit():
                        config[key] = default_value
                        self._log(f"Invalid {key}: {value}, must be numeric str, reset to {default_value}", "Warning")
        except Exception as e:
            self._log(f"Validation error: {str(e)}\n{traceback.format_exc()}", "Error")

    def get(self, key: str, default: Optional[Any] = None) -> Any:
        """جلب قيمة إعداد."""
        try:
            return self.config.get(key, default if default is not None else self.default_config.get(key))
        except Exception as e:
            self._log(f"Error getting {key}: {str(e)}\n{traceback.format_exc()}", "Error")
            return default if default is not None else self.default_config.get(key)

    def set(self, key: str, value: Any) -> None:
        """تحديث قيمة إعداد."""
        try:
            if key not in self.default_config:
                self._log(f"Unknown config key: {key}, ignoring", "Warning")
                return
            self.config[key] = value
            self.validate_config(self.config)
            self.save_config()
            self._log(f"Updated {key} to {value}", "Info")
            self.configUpdated.emit()
        except Exception as e:
            self._log(f"Error setting {key}: {str(e)}\n{traceback.format_exc()}", "Error")
            raise

    def reset_to_default(self) -> None:
        """إعادة تعيين الإعدادات إلى الافتراضي."""
        try:
            self.config = self.default_config.copy()
            self.save_config()
            self._log("Config reset to defaults", "Info")
            self.statusUpdated.emit("Config reset to default settings")
        except Exception as e:
            self._log(f"Error resetting config: {str(e)}\n{traceback.format_exc()}", "Error")
            raise

if __name__ == "__main__":
    from PyQt5.QtWidgets import QApplication
    import sys
    app = QApplication(sys.argv)
    class DummyApp:
        pass
    class DummyLogManager:
        def add_log(self, fb_id, target, action, level, message):
            print(f"[{level}] {action}: {message}")
    config = ConfigManager(DummyApp(), log_manager=DummyLogManager())
    print("Loaded config:", config.config)
    config.set("default_delay", 15)
    config.set("proxies", ["http://proxy1:port"])
    print("Updated config:", config.config)
    config.reset_to_default()
    print("Reset config:", config.config)