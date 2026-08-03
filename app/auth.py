import hashlib
import hmac
import secrets
import time

from fastapi import HTTPException, Request
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from .config import config

SESSION_COOKIE = "raspicam_session"
SESSION_MAX_AGE = 60 * 60 * 24 * 30
MAX_ATTEMPTS = 8
ATTEMPT_WINDOW = 300

_attempts = {}


def _serializer():
    secret = config.section("auth").get("secret") or "raspicam"
    return URLSafeTimedSerializer(secret, salt="raspicam-session")


def hash_password(password):
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=16384, r=8, p=1, dklen=32)
    return salt.hex() + "$" + digest.hex()


def verify_password(password, stored):
    if not stored or "$" not in stored:
        return False
    salt_hex, digest_hex = stored.split("$", 1)
    try:
        salt = bytes.fromhex(salt_hex)
    except ValueError:
        return False
    digest = hashlib.scrypt(password.encode(), salt=salt, n=16384, r=8, p=1, dklen=32)
    return hmac.compare_digest(digest.hex(), digest_hex)


def is_configured():
    return bool(config.section("auth").get("password"))


def set_password(password):
    config.update_section("auth", {"password": hash_password(password)})


def rate_limited(client):
    record = _attempts.get(client)
    if not record:
        return False
    count, first = record
    if time.time() - first > ATTEMPT_WINDOW:
        _attempts.pop(client, None)
        return False
    return count >= MAX_ATTEMPTS


def register_failure(client):
    count, first = _attempts.get(client, (0, time.time()))
    if time.time() - first > ATTEMPT_WINDOW:
        count, first = 0, time.time()
    _attempts[client] = (count + 1, first)


def clear_failures(client):
    _attempts.pop(client, None)


def create_session():
    return _serializer().dumps({"issued": int(time.time()), "nonce": secrets.token_hex(8)})


def valid_session(token):
    if not token:
        return False
    try:
        _serializer().loads(token, max_age=SESSION_MAX_AGE)
    except (BadSignature, SignatureExpired):
        return False
    return True


def authenticated(request: Request):
    return valid_session(request.cookies.get(SESSION_COOKIE))


def require_session(request: Request):
    if not is_configured():
        raise HTTPException(status_code=401, detail="Setup required")
    if not authenticated(request):
        raise HTTPException(status_code=401, detail="Authentication required")
    return True


def client_key(request: Request):
    if request.client:
        return request.client.host
    return "unknown"
