import hashlib
import hmac
import time

from itsdangerous import BadSignature, URLSafeTimedSerializer

from app.config import settings

SESSION_COOKIE = "session"
SESSION_MAX_AGE = 60 * 60 * 24 * 7  # 7 days

_serializer = URLSafeTimedSerializer(settings.session_secret, salt="admin-session")


def verify_telegram_login(data: dict) -> bool:
    """Verifies the payload Telegram's Login Widget redirects back with.
    https://core.telegram.org/widgets/login#checking-authorization
    """
    received_hash = data.get("hash")
    if not received_hash:
        return False

    check_fields = {k: v for k, v in data.items() if k != "hash"}
    check_string = "\n".join(f"{k}={check_fields[k]}" for k in sorted(check_fields))

    secret_key = hashlib.sha256(settings.telegram_bot_token.encode()).digest()
    computed_hash = hmac.new(secret_key, check_string.encode(), hashlib.sha256).hexdigest()

    if not hmac.compare_digest(computed_hash, received_hash):
        return False

    auth_date = int(data.get("auth_date", 0))
    if time.time() - auth_date > 86400:  # reject stale login attempts
        return False

    return True


def create_session_cookie(telegram_user_id: int) -> str:
    return _serializer.dumps({"uid": telegram_user_id})


def read_session_cookie(token: str) -> int | None:
    try:
        data = _serializer.loads(token, max_age=SESSION_MAX_AGE)
        return data["uid"]
    except BadSignature:
        return None
