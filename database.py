import sqlite3
import os
import hashlib
import traceback
from datetime import datetime, timedelta
from PyQt5.QtCore import pyqtSignal, QObject
from pathlib import Path
import shutil
import logging
import logging.handlers
from threading import Lock

class Database(QObject):
    dbUpdated = pyqtSignal()
    statusUpdated = pyqtSignal(str)

    def __init__(self, app, db_file="smart_poster.db", log_manager=None):
        super().__init__()
        self.app = app
        self.base_dir = Path(os.path.dirname(os.path.abspath(__file__)))
        self.db_file = self.base_dir / db_file
        self.backup_dir = self.base_dir / "backups"
        self.log_manager = log_manager
        self.lock = Lock()
        self.conn = None
        self.cursor = None
        self.last_log_id = 0

        if not self.log_manager:
            raise ValueError("LogManager is required for Database")

        self.setup_logging()
        self.connect()
        self.optimize_settings()
        self.create_tables()
        self.create_indexes()
        self.create_auto_backup()

    def setup_logging(self):
        logging.basicConfig(
            filename=self.base_dir / "database.log",
            level=logging.INFO,
            format="%(asctime)s - %(levelname)s - %(message)s",
            handlers=[logging.handlers.RotatingFileHandler(
                self.base_dir / "database.log",
                maxBytes=10*1024*1024,
                backupCount=5
            )]
        )
        self.logger = logging.getLogger(__name__)

    def _log(self, message, level, fb_id="System", action="Database"):
        try:
            timestamp = datetime.now().isoformat()
            full_message = f"{timestamp} | {message} | Trace: {traceback.format_stack()[-2]}"
            if self.log_manager:
                self.log_manager.add_log(fb_id, None, action, level, full_message)
            self.logger.log(getattr(logging, level.upper()), full_message)
            self.statusUpdated.emit(f"{level}: {message}")
        except Exception as e:
            print(f"Error logging in Database: {str(e)}\n{traceback.format_exc()}")

    def connect(self):
        try:
            self.conn = sqlite3.connect(self.db_file, check_same_thread=False)
            self.conn.row_factory = sqlite3.Row
            self.cursor = self.conn.cursor()
        except sqlite3.DatabaseError as e:
            self._log(f"Database error connecting to {self.db_file}: {str(e)}\n{traceback.format_exc()}", "ERROR")
            raise
        except Exception as e:
            self._log(f"Unexpected error connecting to database: {str(e)}\n{traceback.format_exc()}", "ERROR")
            raise

    def reconnect(self):
        with self.lock:
            try:
                if self.conn:
                    self.conn.close()
                self.connect()
                self.optimize_settings()
            except sqlite3.DatabaseError as e:
                self._log(f"Database error reconnecting: {str(e)}\n{traceback.format_exc()}", "ERROR")
                raise
            except Exception as e:
                self._log(f"Unexpected error reconnecting: {str(e)}\n{traceback.format_exc()}", "ERROR")
                raise

    def optimize_settings(self):
        try:
            if not self.conn or not self.cursor:
                raise ValueError("Database connection not established")
            self.cursor.execute("PRAGMA foreign_keys = ON;")
            self.cursor.execute("PRAGMA journal_mode = WAL;")
            self.cursor.execute("PRAGMA synchronous = NORMAL;")
            self.cursor.execute("PRAGMA temp_store = MEMORY;")
            self.conn.commit()
        except sqlite3.OperationalError as e:
            self._log(f"Operational error optimizing settings: {str(e)}\n{traceback.format_exc()}", "ERROR")
            self.reconnect()
            raise
        except Exception as e:
            self._log(f"Unexpected error optimizing settings: {str(e)}\n{traceback.format_exc()}", "ERROR")
            raise

    def create_tables(self):
        try:
            if not self.conn or not self.cursor:
                raise ValueError("Database connection not established")

            self.cursor.execute("""
                CREATE TABLE IF NOT EXISTS accounts (
                    fb_id TEXT PRIMARY KEY CHECK(fb_id != ''),
                    password TEXT NOT NULL CHECK(password != ''),
                    email TEXT NOT NULL CHECK(email != ''),
                    proxy TEXT,
                    access_token TEXT,
                    cookies TEXT,
                    status TEXT DEFAULT 'Not Logged In' CHECK(status IN ('Not Logged In', 'Logged In', 'Banned')),
                    last_login TEXT DEFAULT CURRENT_TIMESTAMP,
                    login_attempts INTEGER DEFAULT 0 CHECK(login_attempts >= 0),
                    is_developer INTEGER DEFAULT 0 CHECK(is_developer IN (0, 1))
                )
            """)

            self.cursor.execute("""
                CREATE TABLE IF NOT EXISTS groups (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    account_id TEXT NOT NULL,
                    group_id TEXT NOT NULL CHECK(group_id != ''),
                    group_name TEXT NOT NULL CHECK(group_name != ''),
                    privacy INTEGER DEFAULT 0 CHECK(privacy IN (0, 1)),
                    created_time TEXT DEFAULT CURRENT_TIMESTAMP,
                    description TEXT,
                    administrator TEXT DEFAULT 'false' CHECK(administrator IN ('true', 'false')),
                    member_count INTEGER DEFAULT 0 CHECK(member_count >= 0),
                    status TEXT DEFAULT 'Active' CHECK(status IN ('Active', 'Inactive')),
                    last_interaction TEXT DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(account_id, group_id),
                    FOREIGN KEY (account_id) REFERENCES accounts(fb_id) ON DELETE CASCADE
                )
            """)

            self.cursor.execute("""
                CREATE TABLE IF NOT EXISTS logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    fb_id TEXT,
                    target TEXT,
                    action TEXT NOT NULL CHECK(action != ''),
                    timestamp TEXT DEFAULT CURRENT_TIMESTAMP,
                    status TEXT NOT NULL CHECK(status IN ('Success', 'Failed', 'Warning')),
                    details TEXT,
                    FOREIGN KEY (fb_id) REFERENCES accounts(fb_id) ON DELETE SET NULL
                )
            """)

            self.cursor.execute("""
                CREATE TABLE IF NOT EXISTS scheduled_posts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    fb_id TEXT NOT NULL,
                    content TEXT NOT NULL CHECK(content != ''),
                    time TEXT NOT NULL CHECK(time != ''),
                    account_id TEXT,
                    group_id TEXT,
                    post_type TEXT DEFAULT 'Text' CHECK(post_type IN ('Text', 'Media')),
                    status TEXT DEFAULT 'Pending' CHECK(status IN ('Pending', 'Posted')),
                    FOREIGN KEY (fb_id) REFERENCES accounts(fb_id) ON DELETE CASCADE,
                    FOREIGN KEY (account_id, group_id) REFERENCES groups(account_id, group_id) ON DELETE SET NULL
                )
            """)

            self.cursor.execute("""
                CREATE TABLE IF NOT EXISTS saved_posts (
                    post_id TEXT PRIMARY KEY CHECK(post_id != ''),
                    fb_id TEXT,
                    content TEXT NOT NULL CHECK(content != ''),
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    status TEXT DEFAULT 'Saved' CHECK(status IN ('Saved', 'Posted')),
                    FOREIGN KEY (fb_id) REFERENCES accounts(fb_id) ON DELETE SET NULL
                )
            """)

            self.cursor.execute("""
                CREATE TABLE IF NOT EXISTS analytics (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    fb_id TEXT NOT NULL,
                    group_id TEXT NOT NULL,
                    posts_count INTEGER DEFAULT 0 CHECK(posts_count >= 0),
                    engagement_score INTEGER DEFAULT 0 CHECK(engagement_score >= 0),
                    invites_count INTEGER DEFAULT 0 CHECK(invites_count >= 0),
                    last_updated TEXT DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(fb_id, group_id),
                    FOREIGN KEY (fb_id, group_id) REFERENCES groups(account_id, group_id) ON DELETE CASCADE
                )
            """)

            self.conn.commit()
            self.dbUpdated.emit()
        except sqlite3.OperationalError as e:
            self._log(f"Operational error creating tables: {str(e)}\n{traceback.format_exc()}", "ERROR")
            self.reconnect()
            raise
        except Exception as e:
            self._log(f"Unexpected error creating tables: {str(e)}\n{traceback.format_exc()}", "ERROR")
            raise

    def create_indexes(self):
        try:
            if not self.conn or not self.cursor:
                raise ValueError("Database connection not established")
            self.cursor.execute("CREATE INDEX IF NOT EXISTS idx_accounts_status ON accounts(status)")
            self.cursor.execute("CREATE INDEX IF NOT EXISTS idx_groups_account_id ON groups(account_id)")
            self.cursor.execute("CREATE INDEX IF NOT EXISTS idx_groups_status ON groups(status)")
            self.cursor.execute("CREATE INDEX IF NOT EXISTS idx_logs_timestamp ON logs(timestamp)")
            self.cursor.execute("CREATE INDEX IF NOT EXISTS idx_logs_fb_id ON logs(fb_id)")
            self.cursor.execute("CREATE INDEX IF NOT EXISTS idx_scheduled_posts_time ON scheduled_posts(time)")
            self.cursor.execute("CREATE INDEX IF NOT EXISTS idx_saved_posts_created_at ON saved_posts(created_at)")
            self.cursor.execute("CREATE INDEX IF NOT EXISTS idx_analytics_fb_id ON analytics(fb_id)")
            self.conn.commit()
            self.dbUpdated.emit()
        except sqlite3.OperationalError as e:
            self._log(f"Operational error creating indexes: {str(e)}\n{traceback.format_exc()}", "ERROR")
            self.reconnect()
            raise
        except Exception as e:
            self._log(f"Unexpected error creating indexes: {str(e)}\n{traceback.format_exc()}", "ERROR")
            raise

    def close(self):
        with self.lock:
            try:
                if self.conn:
                    self.conn.commit()
                    self.conn.close()
                    self.conn = None
                    self.cursor = None
            except sqlite3.OperationalError as e:
                self._log(f"Operational error closing connection: {str(e)}\n{traceback.format_exc()}", "ERROR")
                raise
            except Exception as e:
                self._log(f"Unexpected error closing connection: {str(e)}\n{traceback.format_exc()}", "ERROR")
                raise

    def vacuum(self):
        with self.lock:
            try:
                if not self.conn or not self.cursor:
                    raise ValueError("Database connection not established")
                self.cursor.execute("VACUUM;")
                self.conn.commit()
            except sqlite3.OperationalError as e:
                self._log(f"Operational error during vacuum: {str(e)}\n{traceback.format_exc()}", "ERROR")
                self.reconnect()
                raise
            except Exception as e:
                self._log(f"Unexpected error during vacuum: {str(e)}\n{traceback.format_exc()}", "ERROR")
                raise

    def create_auto_backup(self):
        with self.lock:
            try:
                self.backup_dir.mkdir(exist_ok=True)
                backup_file = self.backup_dir / f"smart_poster_{datetime.now().strftime('%Y%m%d_%H%M%S')}.db"
                shutil.copy2(self.db_file, backup_file)
                self.cleanup_old_backups(max_backups=5)
            except Exception as e:
                self._log(f"Error creating auto-backup: {str(e)}\n{traceback.format_exc()}", "ERROR")
                raise

    def cleanup_old_backups(self, max_backups):
        try:
            backups = sorted(self.backup_dir.glob("smart_poster_*.db"), key=os.path.getmtime)
            if len(backups) > max_backups:
                for old_backup in backups[:-max_backups]:
                    old_backup.unlink()
        except Exception as e:
            self._log(f"Error cleaning up backups: {str(e)}\n{traceback.format_exc()}", "ERROR")

    def sanitize_input(self, value):
        if value is None:
            return ""
        return str(value).replace("'", "''").replace(";", "")

    def add_account(self, fb_id, password, email, proxy=None, access_token=None, is_developer=0):
        with self.lock:
            try:
                if not self.conn or not self.cursor:
                    raise ValueError("Database connection not established")
                fb_id = self.sanitize_input(fb_id)
                password = hashlib.sha256(self.sanitize_input(password).encode()).hexdigest()
                email = self.sanitize_input(email)
                proxy = self.sanitize_input(proxy) if proxy else None
                access_token = self.sanitize_input(access_token) if access_token else None
                if not fb_id or not password or not email:
                    raise ValueError("fb_id, password, and email are required")
                self.cursor.execute(
                    "INSERT INTO accounts (fb_id, password, email, proxy, access_token, is_developer, status) "
                    "VALUES (?, ?, ?, ?, ?, ?, 'Not Logged In') "
                    "ON CONFLICT(fb_id) DO NOTHING",
                    (fb_id, password, email, proxy, access_token, is_developer)
                )
                self.conn.commit()
                self.dbUpdated.emit()
            except sqlite3.IntegrityError as e:
                self._log(f"Integrity error adding account {fb_id}: {str(e)}\n{traceback.format_exc()}", "ERROR", fb_id)
                raise
            except sqlite3.OperationalError as e:
                self._log(f"Operational error adding account {fb_id}: {str(e)}\n{traceback.format_exc()}", "ERROR", fb_id)
                self.reconnect()
                raise
            except Exception as e:
                self._log(f"Unexpected error adding account {fb_id}: {str(e)}\n{traceback.format_exc()}", "ERROR", fb_id)
                raise

    def update_account(self, fb_id, password=None, email=None, proxy=None, cookies=None, access_token=None, status=None, last_login=None, login_attempts=None, is_developer=None):
        with self.lock:
            try:
                if not self.conn or not self.cursor:
                    raise ValueError("Database connection not established")
                fb_id = self.sanitize_input(fb_id)
                updates = []
                params = []
                if password is not None:
                    updates.append("password = ?")
                    params.append(hashlib.sha256(self.sanitize_input(password).encode()).hexdigest())
                if email is not None:
                    updates.append("email = ?")
                    params.append(self.sanitize_input(email))
                if proxy is not None:
                    updates.append("proxy = ?")
                    params.append(self.sanitize_input(proxy))
                if cookies is not None:
                    updates.append("cookies = ?")
                    params.append(self.sanitize_input(cookies))
                if access_token is not None:
                    updates.append("access_token = ?")
                    params.append(self.sanitize_input(access_token))
                if status is not None:
                    updates.append("status = ?")
                    params.append(self.sanitize_input(status))
                if last_login is not None:
                    updates.append("last_login = ?")
                    params.append(self.sanitize_input(last_login))
                if login_attempts is not None:
                    updates.append("login_attempts = ?")
                    params.append(login_attempts)
                if is_developer is not None:
                    updates.append("is_developer = ?")
                    params.append(is_developer)
                if updates:
                    query = "UPDATE accounts SET " + ", ".join(updates) + " WHERE fb_id = ?"
                    params.append(fb_id)
                    self.cursor.execute(query, params)
                    self.conn.commit()
                    self.dbUpdated.emit()
            except sqlite3.OperationalError as e:
                self._log(f"Operational error updating account {fb_id}: {str(e)}\n{traceback.format_exc()}", "ERROR", fb_id)
                self.reconnect()
                raise
            except Exception as e:
                self._log(f"Unexpected error updating account {fb_id}: {str(e)}\n{traceback.format_exc()}", "ERROR", fb_id)
                raise

    def delete_account(self, fb_id):
        with self.lock:
            try:
                if not self.conn or not self.cursor:
                    raise ValueError("Database connection not established")
                fb_id = self.sanitize_input(fb_id)
                self.cursor.execute("DELETE FROM accounts WHERE fb_id = ?", (fb_id,))
                self.conn.commit()
                self.vacuum()
                self.dbUpdated.emit()
            except sqlite3.OperationalError as e:
                self._log(f"Operational error deleting account {fb_id}: {str(e)}\n{traceback.format_exc()}", "ERROR", fb_id)
                self.reconnect()
                raise
            except Exception as e:
                self._log(f"Unexpected error deleting account {fb_id}: {str(e)}\n{traceback.format_exc()}", "ERROR", fb_id)
                raise

    def get_accounts(self):
        with self.lock:
            try:
                if not self.conn or not self.cursor:
                    raise ValueError("Database connection not established")
                self.cursor.execute("SELECT fb_id, email, proxy, access_token, status, last_login, login_attempts, is_developer FROM accounts")
                return [tuple(row) for row in self.cursor.fetchall()]
            except sqlite3.OperationalError as e:
                self._log(f"Operational error getting accounts: {str(e)}\n{traceback.format_exc()}", "ERROR")
                self.reconnect()
                raise
            except Exception as e:
                self._log(f"Unexpected error getting accounts: {str(e)}\n{traceback.format_exc()}", "ERROR")
                raise

    def get_account(self, fb_id):
        with self.lock:
            try:
                if not self.conn or not self.cursor:
                    raise ValueError("Database connection not established")
                fb_id = self.sanitize_input(fb_id)
                self.cursor.execute(
                    "SELECT fb_id, email, proxy, access_token, status, last_login, login_attempts, is_developer "
                    "FROM accounts WHERE fb_id = ?", (fb_id,))
                result = self.cursor.fetchone()
                return tuple(result) if result else None
            except sqlite3.OperationalError as e:
                self._log(f"Operational error getting account {fb_id}: {str(e)}\n{traceback.format_exc()}", "ERROR", fb_id)
                self.reconnect()
                raise
            except Exception as e:
                self._log(f"Unexpected error getting account {fb_id}: {str(e)}\n{traceback.format_exc()}", "ERROR", fb_id)
                raise

    def add_group(self, account_id, group_id, group_name, privacy=0, created_time=None, description="", administrator="false", member_count=0, status="Active", last_interaction=None):
        with self.lock:
            try:
                if not self.conn or not self.cursor:
                    raise ValueError("Database connection not established")
                account_id = self.sanitize_input(account_id)
                group_id = self.sanitize_input(group_id)
                group_name = self.sanitize_input(group_name)
                description = self.sanitize_input(description)
                administrator = self.sanitize_input(administrator)
                created_time = created_time or datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                last_interaction = last_interaction or datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                self.cursor.execute(
                    "INSERT OR REPLACE INTO groups "
                    "(account_id, group_id, group_name, privacy, created_time, description, administrator, member_count, status, last_interaction) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (account_id, group_id, group_name, privacy, created_time, description, administrator, member_count, status, last_interaction)
                )
                self.conn.commit()
                self.dbUpdated.emit()
            except sqlite3.IntegrityError as e:
                self._log(f"Integrity error adding group {group_id}: {str(e)}\n{traceback.format_exc()}", "ERROR", account_id)
                raise
            except sqlite3.OperationalError as e:
                self._log(f"Operational error adding group {group_id}: {str(e)}\n{traceback.format_exc()}", "ERROR", account_id)
                self.reconnect()
                raise
            except Exception as e:
                self._log(f"Unexpected error adding group {group_id}: {str(e)}\n{traceback.format_exc()}", "ERROR", account_id)
                raise

    def get_groups(self, account_id=None):
        with self.lock:
            try:
                if not self.conn or not self.cursor:
                    raise ValueError("Database connection not established")
                query = "SELECT id, account_id, group_id, group_name, privacy, created_time, description, administrator, member_count, status, last_interaction FROM groups"
                params = []
                if account_id:
                    query += " WHERE account_id = ?"
                    params.append(self.sanitize_input(account_id))
                self.cursor.execute(query, params)
                return [tuple(row) for row in self.cursor.fetchall()]
            except sqlite3.OperationalError as e:
                self._log(f"Operational error getting groups: {str(e)}\n{traceback.format_exc()}", "ERROR", account_id or "System")
                self.reconnect()
                raise
            except Exception as e:
                self._log(f"Unexpected error getting groups: {str(e)}\n{traceback.format_exc()}", "ERROR", account_id or "System")
                raise

    def add_log(self, fb_id, target, action, status, details=""):
        with self.lock:
            try:
                if not self.conn or not self.cursor:
                    raise ValueError("Database connection not established")
                fb_id = self.sanitize_input(fb_id)
                target = self.sanitize_input(target)
                action = self.sanitize_input(action)
                status = self.sanitize_input(status)
                details = self.sanitize_input(details)
                self.cursor.execute(
                    "INSERT INTO logs (fb_id, target, action, status, details) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (fb_id, target, action, status, details)
                )
                self.conn.commit()
                self.dbUpdated.emit()
            except sqlite3.OperationalError as e:
                self._log(f"Operational error adding log: {str(e)}\n{traceback.format_exc()}", "ERROR", fb_id)
                self.reconnect()
                raise
            except Exception as e:
                self._log(f"Unexpected error adding log: {str(e)}\n{traceback.format_exc()}", "ERROR", fb_id)
                raise

    def get_logs(self, limit=100, fb_id=None, action=None):
        with self.lock:
            try:
                if not self.conn or not self.cursor:
                    raise ValueError("Database connection not established")
                query = "SELECT id, fb_id, target, action, timestamp, status, details FROM logs"
                params = []
                conditions = []
                if fb_id:
                    conditions.append("fb_id = ?")
                    params.append(self.sanitize_input(fb_id))
                if action:
                    conditions.append("action = ?")
                    params.append(self.sanitize_input(action))
                if conditions:
                    query += " WHERE " + " AND ".join(conditions)
                query += " ORDER BY timestamp DESC LIMIT ?"
                params.append(limit)
                self.cursor.execute(query, params)
                logs = [tuple(row) for row in self.cursor.fetchall()]
                if logs and len(logs) > 0:
                    self.last_log_id = max(row[0] for row in logs)
                return logs
            except sqlite3.OperationalError as e:
                self._log(f"Operational error getting logs: {str(e)}\n{traceback.format_exc()}", "ERROR")
                self.reconnect()
                raise
            except Exception as e:
                self._log(f"Unexpected error getting logs: {str(e)}\n{traceback.format_exc()}", "ERROR")
                raise

    def get_new_logs(self, last_log_id):
        with self.lock:
            try:
                if not self.conn or not self.cursor:
                    raise ValueError("Database connection not established")
                self.cursor.execute(
                    "SELECT id, fb_id, target, action, timestamp, status, details "
                    "FROM logs WHERE id > ? ORDER BY timestamp DESC",
                    (last_log_id,)
                )
                new_logs = [tuple(row) for row in self.cursor.fetchall()]
                if new_logs and len(new_logs) > 0:
                    self.last_log_id = max(row[0] for row in new_logs)
                return new_logs
            except sqlite3.OperationalError as e:
                self._log(f"Operational error getting new logs: {str(e)}\n{traceback.format_exc()}", "ERROR")
                self.reconnect()
                raise
            except Exception as e:
                self._log(f"Unexpected error getting new logs: {str(e)}\n{traceback.format_exc()}", "ERROR")
                raise

    def add_scheduled_post(self, fb_id, content, time, group_id=None, post_type="Text", status="Pending"):
        with self.lock:
            try:
                if not self.conn or not self.cursor:
                    raise ValueError("Database connection not established")
                fb_id = self.sanitize_input(fb_id)
                content = self.sanitize_input(content)
                time = self.sanitize_input(time)
                group_id = self.sanitize_input(group_id) if group_id else None
                post_type = self.sanitize_input(post_type)
                status = self.sanitize_input(status)
                self.cursor.execute(
                    "INSERT INTO scheduled_posts (fb_id, content, time, account_id, group_id, post_type, status) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (fb_id, content, time, fb_id, group_id, post_type, status)
                )
                post_id = self.cursor.lastrowid
                self.conn.commit()
                self.dbUpdated.emit()
                return post_id
            except sqlite3.OperationalError as e:
                self._log(f"Operational error adding scheduled post: {str(e)}\n{traceback.format_exc()}", "ERROR", fb_id)
                self.reconnect()
                raise
            except Exception as e:
                self._log(f"Unexpected error adding scheduled post: {str(e)}\n{traceback.format_exc()}", "ERROR", fb_id)
                raise

    def get_scheduled_posts(self):
        with self.lock:
            try:
                if not self.conn or not self.cursor:
                    raise ValueError("Database connection not established")
                self.cursor.execute(
                    "SELECT id, fb_id, content, time, account_id, group_id, post_type, status "
                    "FROM scheduled_posts ORDER BY time ASC"
                )
                return [tuple(row) for row in self.cursor.fetchall()]
            except sqlite3.OperationalError as e:
                self._log(f"Operational error getting scheduled posts: {str(e)}\n{traceback.format_exc()}", "ERROR")
                self.reconnect()
                raise
            except Exception as e:
                self._log(f"Unexpected error getting scheduled posts: {str(e)}\n{traceback.format_exc()}", "ERROR")
                raise

    def update_scheduled_post_status(self, post_id, status):
        with self.lock:
            try:
                if not self.conn or not self.cursor:
                    raise ValueError("Database connection not established")
                status = self.sanitize_input(status)
                self.cursor.execute(
                    "UPDATE scheduled_posts SET status = ? WHERE id = ?",
                    (status, post_id)
                )
                self.conn.commit()
                self.dbUpdated.emit()
            except sqlite3.OperationalError as e:
                self._log(f"Operational error updating scheduled post {post_id}: {str(e)}\n{traceback.format_exc()}", "ERROR")
                self.reconnect()
                raise
            except Exception as e:
                self._log(f"Unexpected error updating scheduled post {post_id}: {str(e)}\n{traceback.format_exc()}", "ERROR")
                raise

    def add_saved_post(self, post_id, fb_id, content, created_at=None, status="Saved"):
        with self.lock:
            try:
                if not self.conn or not self.cursor:
                    raise ValueError("Database connection not established")
                post_id = hashlib.sha256(self.sanitize_input(post_id).encode()).hexdigest()
                fb_id = self.sanitize_input(fb_id)
                content = self.sanitize_input(content)
                created_at = created_at or datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                status = self.sanitize_input(status)
                self.cursor.execute(
                    "INSERT OR REPLACE INTO saved_posts (post_id, fb_id, content, created_at, status) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (post_id, fb_id, content, created_at, status)
                )
                self.conn.commit()
                self.dbUpdated.emit()
            except sqlite3.OperationalError as e:
                self._log(f"Operational error adding saved post {post_id}: {str(e)}\n{traceback.format_exc()}", "ERROR", fb_id)
                self.reconnect()
                raise
            except Exception as e:
                self._log(f"Unexpected error adding saved post {post_id}: {str(e)}\n{traceback.format_exc()}", "ERROR", fb_id)
                raise

    def get_recent_posts(self, limit=100):
        with self.lock:
            try:
                if not self.conn or not self.cursor:
                    raise ValueError("Database connection not established")
                self.cursor.execute(
                    "SELECT post_id, fb_id, content, created_at, status "
                    "FROM saved_posts ORDER BY created_at DESC LIMIT ?",
                    (limit,)
                )
                return [tuple(row) for row in self.cursor.fetchall()]
            except sqlite3.OperationalError as e:
                self._log(f"Operational error getting recent posts: {str(e)}\n{traceback.format_exc()}", "ERROR")
                self.reconnect()
                raise
            except Exception as e:
                self._log(f"Unexpected error getting recent posts: {str(e)}\n{traceback.format_exc()}", "ERROR")
                raise

    def update_analytics(self, fb_id, group_id, posts_count, engagement_score, invites_count):
        with self.lock:
            try:
                if not self.conn or not self.cursor:
                    raise ValueError("Database connection not established")
                fb_id = self.sanitize_input(fb_id)
                group_id = self.sanitize_input(group_id)
                self.cursor.execute(
                    "INSERT OR REPLACE INTO analytics "
                    "(fb_id, group_id, posts_count, engagement_score, invites_count, last_updated) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (fb_id, group_id, posts_count, engagement_score, invites_count, datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
                )
                self.conn.commit()
                self.dbUpdated.emit()
            except sqlite3.OperationalError as e:
                self._log(f"Operational error updating analytics: {str(e)}\n{traceback.format_exc()}", "ERROR", fb_id)
                self.reconnect()
                raise
            except Exception as e:
                self._log(f"Unexpected error updating analytics: {str(e)}\n{traceback.format_exc()}", "ERROR", fb_id)
                raise

    def get_analytics(self, fb_id=None, group_id=None):
        with self.lock:
            try:
                if not self.conn or not self.cursor:
                    raise ValueError("Database connection not established")
                query = "SELECT id, fb_id, group_id, posts_count, engagement_score, invites_count, last_updated FROM analytics"
                params = []
                conditions = []
                if fb_id:
                    conditions.append("fb_id = ?")
                    params.append(self.sanitize_input(fb_id))
                if group_id:
                    conditions.append("group_id = ?")
                    params.append(self.sanitize_input(group_id))
                if conditions:
                    query += " WHERE " + " AND ".join(conditions)
                self.cursor.execute(query, params)
                return [tuple(row) for row in self.cursor.fetchall()]
            except sqlite3.OperationalError as e:
                self._log(f"Operational error getting analytics: {str(e)}\n{traceback.format_exc()}", "ERROR")
                self.reconnect()
                raise
            except Exception as e:
                self._log(f"Unexpected error getting analytics: {str(e)}\n{traceback.format_exc()}", "ERROR")
                raise

    def cleanup_old_logs(self, days=30):
        with self.lock:
            try:
                if not self.conn or not self.cursor:
                    raise ValueError("Database connection not established")
                cutoff_date = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
                self.cursor.execute("DELETE FROM logs WHERE timestamp < ?", (cutoff_date,))
                self.conn.commit()
                self.vacuum()
                self.dbUpdated.emit()
            except sqlite3.OperationalError as e:
                self._log(f"Operational error cleaning up logs: {str(e)}\n{traceback.format_exc()}", "ERROR")
                self.reconnect()
                raise
            except Exception as e:
                self._log(f"Unexpected error cleaning up logs: {str(e)}\n{traceback.format_exc()}", "ERROR")
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
    db = Database(DummyApp(), log_manager=DummyLogManager())
    db.add_account("fb1", "pass1", "email1@example.com")
    db.add_group("fb1", "group1", "Test Group")
    db.add_log("fb1", "group1", "Test Action", "Success")
    print("Accounts:", db.get_accounts())
    print("Groups:", db.get_groups("fb1"))
    print("Logs:", db.get_logs(limit=10))
    db.close()