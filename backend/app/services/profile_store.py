from copy import deepcopy
from datetime import datetime
from typing import Any, Dict, List, Optional

DEFAULT_NOTIFICATION_CATEGORIES = ["reservations", "payments", "maintenance", "system"]


class ProfileStore:
    """In-memory profile storage for Challenge Mode when Supabase is unavailable."""

    _profiles: Dict[str, Dict[str, Any]] = {}
    _preferences: Dict[str, Dict[str, Any]] = {}
    _notification_prefs: Dict[str, Dict[str, Dict[str, Any]]] = {}

    @classmethod
    def is_challenge_mode(cls) -> bool:
        from app.config import settings

        return not (settings.supabase_url and settings.supabase_service_role_key)

    @classmethod
    def _now_iso(cls) -> str:
        return datetime.utcnow().isoformat()

    @classmethod
    def default_profile(cls, user_id: str, email: Optional[str] = None) -> Dict[str, Any]:
        now = cls._now_iso()
        return {
            "id": f"synthetic-{user_id}",
            "user_id": user_id,
            "display_name": (email.split("@")[0] if email else "User"),
            "bio": None,
            "phone": None,
            "department": None,
            "job_title": None,
            "location": None,
            "timezone": "UTC",
            "language": "en",
            "theme": "light",
            "avatar_url": None,
            "created_at": now,
            "updated_at": now,
        }

    @classmethod
    def default_preferences(cls, user_id: str) -> Dict[str, Any]:
        now = cls._now_iso()
        return {
            "id": f"synthetic-{user_id}",
            "user_id": user_id,
            "notification_email": True,
            "notification_push": True,
            "notification_desktop": True,
            "notification_sound": True,
            "auto_refresh": True,
            "compact_view": False,
            "sidebar_collapsed": False,
            "created_at": now,
            "updated_at": now,
        }

    @classmethod
    def default_notification_preferences(cls, user_id: str) -> List[Dict[str, Any]]:
        now = cls._now_iso()
        return [
            {
                "id": f"synthetic-{user_id}-{category}",
                "user_id": user_id,
                "category": category,
                "email_enabled": True,
                "push_enabled": True,
                "desktop_enabled": True,
                "sound_enabled": True,
                "created_at": now,
                "updated_at": now,
            }
            for category in DEFAULT_NOTIFICATION_CATEGORIES
        ]

    @classmethod
    def get_profile(cls, user_id: str, email: Optional[str] = None) -> Dict[str, Any]:
        if user_id in cls._profiles:
            return deepcopy(cls._profiles[user_id])
        return cls.default_profile(user_id, email)

    @classmethod
    def get_preferences(cls, user_id: str) -> Dict[str, Any]:
        if user_id in cls._preferences:
            return deepcopy(cls._preferences[user_id])
        return cls.default_preferences(user_id)

    @classmethod
    def get_notification_preferences(cls, user_id: str) -> List[Dict[str, Any]]:
        if user_id in cls._notification_prefs:
            return [
                deepcopy(pref)
                for pref in cls._notification_prefs[user_id].values()
            ]
        return cls.default_notification_preferences(user_id)

    @classmethod
    def update_profile(cls, user_id: str, updates: Dict[str, Any], email: Optional[str] = None) -> Dict[str, Any]:
        profile = cls.get_profile(user_id, email)
        profile.update(updates)
        profile["updated_at"] = cls._now_iso()
        cls._profiles[user_id] = profile
        return deepcopy(profile)

    @classmethod
    def update_preferences(cls, user_id: str, updates: Dict[str, Any]) -> Dict[str, Any]:
        preferences = cls.get_preferences(user_id)
        preferences.update(updates)
        preferences["updated_at"] = cls._now_iso()
        cls._preferences[user_id] = preferences
        return deepcopy(preferences)

    @classmethod
    def update_notification_preference(
        cls, user_id: str, category: str, updates: Dict[str, Any]
    ) -> Dict[str, Any]:
        if user_id not in cls._notification_prefs:
            cls._notification_prefs[user_id] = {
                pref["category"]: pref
                for pref in cls.default_notification_preferences(user_id)
            }

        prefs = cls._notification_prefs[user_id]
        if category not in prefs:
            now = cls._now_iso()
            prefs[category] = {
                "id": f"synthetic-{user_id}-{category}",
                "user_id": user_id,
                "category": category,
                "email_enabled": True,
                "push_enabled": True,
                "desktop_enabled": True,
                "sound_enabled": True,
                "created_at": now,
                "updated_at": now,
            }

        prefs[category].update(updates)
        prefs[category]["updated_at"] = cls._now_iso()
        return deepcopy(prefs[category])

    @classmethod
    def set_avatar_url(cls, user_id: str, avatar_url: str, email: Optional[str] = None) -> Dict[str, Any]:
        return cls.update_profile(user_id, {"avatar_url": avatar_url}, email)

    @classmethod
    def clear_avatar(cls, user_id: str, email: Optional[str] = None) -> Dict[str, Any]:
        return cls.update_profile(user_id, {"avatar_url": None}, email)
