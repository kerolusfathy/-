# ai_analytics.py
import asyncio
import random
from datetime import datetime
import requests
from typing import List, Dict, Tuple, Optional, Any
from PyQt5.QtWidgets import QApplication, QMessageBox
from PyQt5.QtCore import pyqtSignal, QObject, Qt, QMetaObject, Q_ARG, QThreadPool
import traceback
import orjson
import bleach
import ssl
import shutil
from concurrent.futures import ThreadPoolExecutor
from tenacity import retry, wait_fixed, stop_after_attempt

class AIAnalytics(QObject):
    statusUpdated = pyqtSignal(str)
    progressUpdated = pyqtSignal(int, int)

    def __init__(self, app, config: Optional[dict], db, log_manager):
        super().__init__()
        self.app = app
        self.config = config or {}
        self.db = db
        self.log_manager = log_manager
        self.thread_pool = QThreadPool.globalInstance()
        self.thread_pool.setMaxThreadCount(4)
        if not self.log_manager:
            raise ValueError("LogManager is required")
        self._log("AIAnalytics initialized successfully", "Info")

    def _log(self, message: str, level: str, fb_id: str = "System", action: str = "Analytics") -> None:
        try:
            if self.log_manager:
                self.log_manager.add_log(fb_id, None, action, level, f"{message}\n{traceback.format_exc() if level == 'Error' else ''}")
                if os.path.getsize("analytics_log.txt") > 1024 * 1024:
                    os.rename("analytics_log.txt", f"analytics_log_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt")
                    open("analytics_log.txt", "w", encoding="utf-8").close()
            self.statusUpdated.emit(f"{level}: {message}")
        except Exception as e:
            print(f"Error logging in AIAnalytics: {str(e)}\n{traceback.format_exc()}")

    async def suggest_post(self, keywords: str) -> str:
        try:
            if not keywords or not isinstance(keywords, str):
                self._log("No keywords provided for post suggestion", "Warning")
                return "Please provide valid keywords to suggest a post."
            sanitized_keywords = bleach.clean(keywords)
            templates = [
                f"Check out this amazing {sanitized_keywords}!",
                f"Love {sanitized_keywords}? Here's something for you!",
                f"Discover the best {sanitized_keywords} today!",
                f"Excited about {sanitized_keywords}? Join us now!",
                f"Get the latest on {sanitized_keywords} right here!",
                f"Don't miss out on {sanitized_keywords} – see what's new!",
                f"Join the {sanitized_keywords} community today!",
                f"Explore {sanitized_keywords} with us – let's get started!",
                f"Everything you need to know about {sanitized_keywords}!",
                f"Unlock the secrets of {sanitized_keywords} now!"
            ]
            suggested_post = random.choice(templates)
            best_keywords = await self.predict_best_keywords()
            if self.config.get("add_hashtags", False):
                hashtags = " ".join([f"#{word}" for word in sanitized_keywords.split() if word] + [f"#{kw}" for kw in best_keywords[:2]])
                suggested_post += f" {hashtags} #SmartPoster"
            if self.config.get("add_call_to_action", False):
                suggested_post += " Click the link to learn more! 🔗"
            if self.config.get("custom_scripts"):
                suggested_post += f" {random.choice(self.config['custom_scripts'])}"
            self._log(f"Suggested post: {suggested_post}", "Info")
            self.statusUpdated.emit(f"Suggested post: {suggested_post}")
            return suggested_post
        except Exception as e:
            error_message = f"Error suggesting post: {str(e)}"
            self._log(error_message, "Error")
            return f"Error generating post suggestion: {str(e)}"

    async def get_campaign_stats(self) -> List[Tuple[str, int, int, int, int]]:
        try:
            accounts = []
            try:
                accounts = self.db.get_accounts()
            except Exception as e:
                self._log(f"DB Error fetching accounts: {str(e)}", "Error")
                return []
            if not accounts:
                self._log("No accounts available for stats", "Warning")
                self.statusUpdated.emit("No accounts available for stats")
                return []
            stats = []
            total = len(accounts)
            tasks = []
            for i, acc in enumerate(accounts):
                fb_id = acc[0]
                tasks.append(asyncio.create_task(self._get_account_stats(fb_id, acc[4], acc[9])))
                self.progressUpdated.emit(i + 1, total)
            results = await asyncio.gather(*tasks, return_exceptions=True)
            for i, result in enumerate(results):
                if isinstance(result, Exception):
                    self._log(f"Error retrieving stats for {accounts[i][0]}: {str(result)}", "Error", accounts[i][0])
                    stats.append((accounts[i][0], 0, 0, 0, 0))
                else:
                    stats.append(result)
            self._log(f"Retrieved campaign stats for {len(stats)} accounts", "Info")
            self.statusUpdated.emit(f"Retrieved campaign stats for {len(stats)} accounts")
            return stats
        except Exception as e:
            error_message = f"Error retrieving campaign stats: {str(e)}"
            self._log(error_message, "Error")
            self.statusUpdated.emit(f"Error retrieving campaign stats: {str(e)}")
            return []

    async def _get_account_stats(self, fb_id: str, access_token: Optional[str], is_developer: int) -> Tuple[str, int, int, int, int]:
        try:
            async def fetch_logs():
                return await asyncio.to_thread(self.db.get_logs, fb_id=fb_id)
            logs = await fetch_logs()
            posts = len([log for log in logs if "Posted" in log["action"] and "Success" in log["status"]])
            engagement = await self.get_real_engagement(fb_id) if is_developer and access_token and self.config.get("use_access_token", False) else 0
            invites = len([log for log in logs if "Invited" in log["action"] and "Success" in log["status"]])
            extracted_members = len([log for log in logs if "Extracted member" in log["action"] and "Success" in log["status"]])
            return (fb_id, posts, engagement, invites, extracted_members)
        except Exception as e:
            error_message = f"Error retrieving stats for {fb_id}: {str(e)}"
            self._log(error_message, "Error", fb_id)
            return (fb_id, 0, 0, 0, 0)

    @retry(wait=wait_fixed(2), stop=stop_after_attempt(3))
    async def get_real_engagement(self, fb_id: str) -> int:
        try:
            account = self.db.get_account(fb_id)
            if not account or not account[4] or not account[9]:
                self._log(f"No valid access token or developer status for {fb_id}", "Warning", fb_id)
                return 0
            access_token = account[4]
            url = f"https://graph.facebook.com/v20.0/me/feed?fields=likes.summary(true),comments.summary(true)"
            headers = {'Authorization': f'Bearer {access_token}'}
            ssl_context = ssl.create_default_context()
            async def fetch():
                return await asyncio.get_event_loop().run_in_executor(None, lambda: requests.get(url, headers=headers, timeout=10, verify=ssl_context).content)
            response = orjson.loads(await asyncio.wait_for(fetch(), timeout=15))
            if "error" in response:
                self._log(f"Graph API error for {fb_id}: {response['error']['message']}, Status: {response.status_code}", "Warning", fb_id)
                return 0
            engagement = 0
            for post in response.get("data", []):
                likes = post.get("likes", {}).get("summary", {}).get("total_count", 0)
                comments = post.get("comments", {}).get("summary", {}).get("total_count", 0)
                engagement += likes + comments
            self._log(f"Retrieved real engagement for {fb_id}: {engagement}", "Info", fb_id)
            return engagement
        except Exception as e:
            error_message = f"Error retrieving real engagement for {fb_id}: {str(e)}"
            self._log(error_message, "Error", fb_id)
            return 0

    async def analyze_group_engagement(self, group_id: str) -> Dict[str, float]:
        try:
            async def fetch_logs():
                return await asyncio.to_thread(self.db.get_logs)
            logs = await fetch_logs()
            group_logs = [log for log in logs if log[2] == group_id]
            if not group_logs:
                self._log(f"No logs available for group {group_id}", "Warning", group_id)
                return {"posts": 0, "invites": 0, "success_rate": 0.0}
            posts = len([log for log in group_logs if "Posted" in log[3] and "Success" in log[5]])
            invites = len([log for log in group_logs if "Invited" in log[3] and "Success" in log[5]])
            total_actions = len(group_logs)
            successful_actions = len([log for log in group_logs if "Success" in log[5]])
            success_rate = (successful_actions / total_actions * 100) if total_actions > 0 else 0.0
            engagement_data = {
                "posts": posts,
                "invites": invites,
                "success_rate": round(success_rate, 2)
            }
            self._log(f"Group engagement analyzed: {engagement_data}", "Info", group_id)
            self.statusUpdated.emit(f"Analyzed group {group_id}: {engagement_data}")
            return engagement_data
        except Exception as e:
            error_message = f"Error analyzing group engagement: {str(e)}"
            self._log(error_message, "Error", group_id)
            return {"posts": 0, "invites": 0, "success_rate": 0.0}

    async def optimize_posting_schedule(self) -> List[str]:
        try:
            start_time = datetime.now()
            async def fetch_logs():
                return await asyncio.to_thread(self.db.get_logs)
            logs = await fetch_logs()
            if not logs:
                self._log("No logs available for scheduling optimization", "Warning")
                self.statusUpdated.emit("No logs available, using default times")
                return ["10:00", "14:00", "20:00"]
            hours = {}
            for log in logs:
                if "Posted" in log[3] and "Success" in log[5]:
                    timestamp = datetime.strptime(log[4], "%Y-%m-%d %H:%M:%S")
                    hour = timestamp.hour
                    hours[hour] = hours.get(hour, 0) + 1
            best_hours = sorted(hours.items(), key=lambda x: x[1], reverse=True)[:3]
            suggested_times = [f"{hour:02d}:00" for hour, _ in best_hours] or ["10:00", "14:00", "20:00"]
            execution_time = (datetime.now() - start_time).total_seconds()
            self._log(f"Suggested posting schedule: {', '.join(suggested_times)}, took {execution_time}s", "Info")
            self.statusUpdated.emit(f"Optimized schedule: {', '.join(suggested_times)}")
            return suggested_times
        except Exception as e:
            error_message = f"Error optimizing schedule: {str(e)}"
            self._log(error_message, "Error")
            self.statusUpdated.emit(f"Error optimizing schedule: {str(e)}")
            return ["10:00", "14:00", "20:00"]

    async def identify_active_groups(self) -> List[Dict[str, Any]]:
        try:
            async def fetch_groups():
                return await asyncio.to_thread(self.db.get_groups)
            groups = await fetch_groups()
            if not groups:
                self._log("No groups available for active group analysis", "Warning")
                self.statusUpdated.emit("No groups available for analysis")
                return []
            active_groups = []
            total = len(groups)
            tasks = []
            for i, group in enumerate(groups):
                group_id = group[2]
                tasks.append(asyncio.create_task(self.analyze_group_engagement(group_id)))
                self.progressUpdated.emit(i + 1, total)
            results = await asyncio.gather(*tasks, return_exceptions=True)
            for i, result in enumerate(results):
                group_id, group_name = groups[i][2], groups[i][3]
                if isinstance(result, Exception):
                    self._log(f"Error analyzing group {group_id}: {str(result)}", "Error", group_id)
                    active_groups.append({"group_id": group_id, "group_name": group_name, "posts": 0, "invites": 0, "success_rate": 0.0})
                elif result["posts"] > 0 or result["invites"] > 0:
                    active_groups.append({
                        "group_id": group_id,
                        "group_name": group_name,
                        "posts": result["posts"],
                        "invites": result["invites"],
                        "success_rate": result["success_rate"]
                    })
            active_groups = sorted(active_groups, key=lambda x: (x["posts"] + x["invites"]), reverse=True)
            self._log(f"Identified {len(active_groups)} active groups", "Info")
            self.statusUpdated.emit(f"Identified {len(active_groups)} active groups")
            return active_groups
        except Exception as e:
            error_message = f"Error identifying active groups: {str(e)}"
            self._log(error_message, "Error")
            self.statusUpdated.emit(f"Error identifying active groups: {str(e)}")
            return []

    async def predict_best_keywords(self) -> List[str]:
        try:
            if shutil.disk_usage("/").free < 1024 * 1024:
                self._log("Insufficient disk space for keyword prediction", "Error")
                return ["marketing", "technology", "socialmedia"]
            async def fetch_logs():
                return await asyncio.to_thread(self.db.get_logs)
            logs = await fetch_logs()
            if not logs:
                self._log("No logs available for keyword prediction", "Warning")
                self.statusUpdated.emit("No logs available, using default keywords")
                return ["marketing", "technology", "socialmedia", "business", "trending"]
            keywords = {}
            for log in logs:
                if "Posted" in log[3] and "Success" in log[5]:
                    content = log[6].split("Posted: ")[1] if "Posted: " in log[6] else ""
                    for word in content.split():
                        word = bleach.clean(word.strip("#").lower())
                        if len(word) > 3 and not word.isdigit():
                            keywords[word] = keywords.get(word, 0) + 1
            best_keywords = [keyword for keyword, count in sorted(keywords.items(), key=lambda x: x[1], reverse=True)[:5]]
            if not best_keywords:
                best_keywords = ["marketing", "technology", "socialmedia", "business", "trending"]
            self.db.update_last_successful_prediction(fb_id="System", keywords=best_keywords, timestamp=datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
            self._log(f"Predicted best keywords: {', '.join(best_keywords)}", "Info")
            self.statusUpdated.emit(f"Predicted best keywords: {', '.join(best_keywords)}")
            return best_keywords
        except Exception as e:
            error_message = f"Error predicting keywords: {str(e)}"
            self._log(error_message, "Error")
            self.statusUpdated.emit(f"Error predicting keywords: {str(e)}")
            return ["marketing", "technology", "socialmedia", "business", "trending"]

    def cleanup_old_logs(self) -> None:
        try:
            logs = self.db.get_logs()
            for log in logs:
                timestamp = datetime.strptime(log[4], "%Y-%m-%d %H:%M:%S")
                if (datetime.now() - timestamp).days > 90:
                    self.db.delete_log(log[0])
                    self._log(f"Deleted old log ID {log[0]}", "Info")
        except Exception as e:
            self._log(f"Error cleaning old logs: {str(e)}", "Error")

if __name__ == "__main__":
    from PyQt5.QtWidgets import QApplication
    import sys
    import os
    app = QApplication.instance() or QApplication(sys.argv)
    class DummyApp:
        class DummyUI:
            def show_message(self, title, message, icon):
                print(f"[{title}] {message}")
        ui = DummyUI()
    class DummyConfig:
        def get(self, key, default=None):
            defaults = {
                "add_hashtags": True,
                "add_call_to_action": True,
                "custom_scripts": ["Contact us!"],
                "use_access_token": True
            }
            return defaults.get(key, default)
    class DummyDatabase:
        def __init__(self):
            self.accounts = [("fb1", "pass", "email@example.com", None, "token", None, "Logged In", None, 0, 1)]
            self.logs = [
                (1, "fb1", "group1", "Posted", "2023-01-01 10:00:00", "Success", "Posted: Test marketing post"),
                (2, "fb1", "group1", "Invited", "2023-01-01 10:05:00", "Success", "Invited member")
            ]
            self.groups = [(1, "fb1", "group1", "Test Group", 0, "", "", "false", 100, "Active", "")]
        def get_accounts(self):
            return self.accounts
        def get_account(self, fb_id):
            return next((acc for acc in self.accounts if acc[0] == fb_id), None)
        def get_logs(self, fb_id=None, action=None):
            return self.logs if not fb_id else [log for log in self.logs if log[1] == fb_id]
        def get_groups(self):
            return self.groups
        def delete_log(self, log_id):
            self.logs = [log for log in self.logs if log[0] != log_id]
        def update_last_successful_prediction(self, fb_id, keywords, timestamp):
            pass
    class DummyLogManager:
        def add_log(self, fb_id, target, action, level, message):
            try:
                with open("analytics_log.txt", "a", encoding="utf-8") as f:
                    f.write(f"[{level}] {action}: {message}\n")
            except Exception as e:
                print(f"Log error: {str(e)}")
    dummy_app = DummyApp()
    ai_analytics = AIAnalytics(dummy_app, DummyConfig(), DummyDatabase(), DummyLogManager())
    try:
        asyncio.run(ai_analytics.suggest_post("test"))
        ai_analytics.cleanup_old_logs()
    except Exception as e:
        print(f"Main error: {str(e)}\n{traceback.format_exc()}")
    sys.exit(app.exec_())