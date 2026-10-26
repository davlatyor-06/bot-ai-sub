import sqlite3
import logging
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path
from config import Config

logger = logging.getLogger("DBService")


class DBService:
    def __init__(self, db_path: Path | str | None = None):
        self.db_path = str(db_path or Config.DB_PATH)
        self._init_db()

    @contextmanager
    def _get_connection(self):
        conn = sqlite3.connect(self.db_path, timeout=15)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()

    def _init_db(self):
        """Ma'lumotlar bazasi jadvallarini yaratish"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            
            # 1. Foydalanuvchilar jadvali
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                full_name TEXT,
                free_uses INTEGER DEFAULT 0,
                is_subscribed INTEGER DEFAULT 0,
                subscription_end TEXT,
                is_admin INTEGER DEFAULT 0,
                state TEXT DEFAULT NULL,
                state_data TEXT DEFAULT NULL,
                created_at TEXT
            )
            """)

            # 2. To'lovlar (cheklar) jadvali
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS payments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                username TEXT,
                full_name TEXT,
                amount INTEGER DEFAULT 15000,
                receipt_message_id INTEGER,
                status TEXT DEFAULT 'pending',
                created_at TEXT
            )
            """)

            # 3. Fikr va takliflar jadvali
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS feedbacks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                username TEXT,
                full_name TEXT,
                message TEXT,
                created_at TEXT
            )
            """)
            conn.commit()
            logger.info("Ma'lumotlar bazasi muvaffaqiyatli ishga tushirildi.")

    def get_or_create_user(self, user_id: int, username: str = "", full_name: str = "") -> dict:
        """Foydalanuvchini olish yoki yangi bo'lsa yaratish"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
            row = cursor.fetchone()
            
            is_env_admin = 1 if user_id in Config.get_admin_ids() else 0

            if row:
                # Agar username yoki full_name o'zgargan bo'lsa yangilash
                cursor.execute(
                    "UPDATE users SET username = ?, full_name = ? WHERE user_id = ?",
                    (username or row["username"], full_name or row["full_name"], user_id)
                )
                conn.commit()
                return dict(row)
            else:
                now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                cursor.execute("""
                INSERT INTO users (user_id, username, full_name, free_uses, is_subscribed, subscription_end, is_admin, created_at)
                VALUES (?, ?, ?, 0, 0, NULL, ?, ?)
                """, (user_id, username, full_name, is_env_admin, now_str))
                conn.commit()

                cursor.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
                return dict(cursor.fetchone())

    def get_user(self, user_id: int) -> dict | None:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
            row = cursor.fetchone()
            return dict(row) if row else None

    def is_admin(self, user_id: int) -> bool:
        if user_id in Config.get_admin_ids():
            return True
        user = self.get_user(user_id)
        return bool(user and user.get("is_admin"))

    def set_admin(self, user_id: int, is_admin: bool = True):
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("UPDATE users SET is_admin = ? WHERE user_id = ?", (1 if is_admin else 0, user_id))
            conn.commit()

    def get_all_admins(self) -> list[int]:
        """Barcha adminlar ro'yxatini olish (.env + db)"""
        admins = set(Config.get_admin_ids())
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT user_id FROM users WHERE is_admin = 1")
            for r in cursor.fetchall():
                admins.add(r["user_id"])
        return list(admins)

    def is_user_subscribed(self, user_id: int) -> bool:
        """Foydalanuvchida faol oylik obuna bor-yo'qligini tekshirish"""
        if self.is_admin(user_id):
            return True

        user = self.get_user(user_id)
        if not user or not user.get("is_subscribed"):
            return False

        sub_end_str = user.get("subscription_end")
        if not sub_end_str:
            return False

        try:
            sub_end = datetime.strptime(sub_end_str, "%Y-%m-%d %H:%M:%S")
            if sub_end > datetime.now():
                return True
            else:
                # Obuna muddati tugagan bo'lsa yangilash
                with self._get_connection() as conn:
                    cursor = conn.cursor()
                    cursor.execute("UPDATE users SET is_subscribed = 0 WHERE user_id = ?", (user_id,))
                    conn.commit()
                return False
        except Exception as e:
            logger.error(f"Sana tekshirishda xato: {e}")
            return False

    def can_process_media(self, user_id: int) -> tuple[bool, str, int]:
        """
        Foydalanuvchi video yoki audio jo'nata oladimi?
        Qaytaradi: (mumkinmi, sababi, qolgan bepul urinishlar)
        sababi: 'admin' | 'subscribed' | 'free' | 'limit_reached'
        """
        if self.is_admin(user_id):
            return True, "admin", -1

        if self.is_user_subscribed(user_id):
            return True, "subscribed", -1

        user = self.get_user(user_id)
        free_uses = user.get("free_uses", 0) if user else 0
        free_limit = Config.FREE_LIMIT

        if free_uses < free_limit:
            remaining = free_limit - free_uses
            return True, "free", remaining
        else:
            return False, "limit_reached", 0

    def increment_free_uses(self, user_id: int) -> int:
        """Bepul urinishlar sonini bittaga oshirish"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("UPDATE users SET free_uses = free_uses + 1 WHERE user_id = ?", (user_id,))
            conn.commit()
            cursor.execute("SELECT free_uses FROM users WHERE user_id = ?", (user_id,))
            row = cursor.fetchone()
            return row["free_uses"] if row else 1

    def activate_subscription(self, user_id: int, days: int = 30) -> str:
        """Foydalanuvchiga belgilangan kunlik obuna berish"""
        now = datetime.now()
        user = self.get_user(user_id)
        current_end_str = user.get("subscription_end") if user else None

        base_date = now
        if current_end_str:
            try:
                curr_end = datetime.strptime(current_end_str, "%Y-%m-%d %H:%M:%S")
                if curr_end > now:
                    base_date = curr_end
            except Exception:
                pass

        new_end = base_date + timedelta(days=days)
        new_end_str = new_end.strftime("%Y-%m-%d %H:%M:%S")

        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
            UPDATE users 
            SET is_subscribed = 1, subscription_end = ? 
            WHERE user_id = ?
            """, (new_end_str, user_id))
            conn.commit()

        logger.info(f"Foydalanuvchi {user_id} ga {days} kunlik obuna faollashtirildi: {new_end_str}")
        return new_end_str

    def set_user_state(self, user_id: int, state: str | None, state_data: str | None = None):
        """Foydalanuvchi muloqot holatini saqlash"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("UPDATE users SET state = ?, state_data = ? WHERE user_id = ?", (state, state_data, user_id))
            conn.commit()

    def get_user_state(self, user_id: int) -> tuple[str | None, str | None]:
        user = self.get_user(user_id)
        if user:
            return user.get("state"), user.get("state_data")
        return None, None

    def clear_user_state(self, user_id: int):
        self.set_user_state(user_id, None, None)

    def create_payment(self, user_id: int, username: str, full_name: str, amount: int = 15000, receipt_message_id: int | None = None) -> int:
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
            INSERT INTO payments (user_id, username, full_name, amount, receipt_message_id, status, created_at)
            VALUES (?, ?, ?, ?, ?, 'pending', ?)
            """, (user_id, username, full_name, amount, receipt_message_id, now_str))
            conn.commit()
            return cursor.lastrowid

    def get_payment(self, payment_id: int) -> dict | None:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM payments WHERE id = ?", (payment_id,))
            row = cursor.fetchone()
            return dict(row) if row else None

    def update_payment_status(self, payment_id: int, status: str) -> bool:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("UPDATE payments SET status = ? WHERE id = ?", (status, payment_id))
            conn.commit()
            return cursor.rowcount > 0

    def save_feedback(self, user_id: int, username: str, full_name: str, message: str) -> int:
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
            INSERT INTO feedbacks (user_id, username, full_name, message, created_at)
            VALUES (?, ?, ?, ?, ?)
            """, (user_id, username, full_name, message, now_str))
            conn.commit()
            return cursor.lastrowid

    def get_all_users(self) -> list[dict]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM users")
            return [dict(r) for r in cursor.fetchall()]

    def get_all_user_ids(self) -> list[int]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT user_id FROM users")
            return [r["user_id"] for r in cursor.fetchall()]

    def get_stats(self) -> dict:
        now_str = datetime.now().strftime("%Y-%m-%d")
        with self._get_connection() as conn:
            cursor = conn.cursor()
            
            cursor.execute("SELECT COUNT(*) AS c FROM users")
            total_users = cursor.fetchone()["c"]

            cursor.execute("""
            SELECT COUNT(*) AS c FROM users 
            WHERE is_subscribed = 1 AND subscription_end > datetime('now', 'localtime')
            """)
            active_subscribers = cursor.fetchone()["c"]

            cursor.execute("SELECT COUNT(*) AS c FROM payments WHERE status = 'pending'")
            pending_payments = cursor.fetchone()["c"]

            cursor.execute("SELECT COUNT(*) AS c FROM users WHERE created_at LIKE ?", (f"{now_str}%",))
            today_users = cursor.fetchone()["c"]

            free_users = max(0, total_users - active_subscribers)

            return {
                "total_users": total_users,
                "active_subscribers": active_subscribers,
                "free_users": free_users,
                "pending_payments": pending_payments,
                "today_users": today_users
            }
