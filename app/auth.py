"""Password hashing and signed session cookies (stdlib only)."""
import base64
import hashlib
import hmac
import secrets

ALGO = "pbkdf2_sha256"
ITERATIONS = 240_000


def hash_password(password: str, salt: str | None = None, iterations: int = ITERATIONS) -> str:
    salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), iterations).hex()
    return f"{ALGO}${iterations}${salt}${digest}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, iterations, salt, digest = stored.split("$")
        if algo != ALGO:
            return False
        candidate = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), int(iterations)).hex()
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(candidate, digest)


_DUMMY = hash_password("dummy", salt="00" * 16)


def verify_login(users: dict[str, str], username: str, password: str) -> bool:
    """Always does one hash so unknown users cost the same time as wrong passwords."""
    stored = users.get(username)
    ok = verify_password(password, stored or _DUMMY)
    return bool(stored) and ok


def _sig(msg: str, secret: str) -> str:
    return hmac.new(secret.encode(), msg.encode(), hashlib.sha256).hexdigest()


def make_session(user: str, secret: str, now: int, ttl: int) -> str:
    if "|" in user:
        raise ValueError("bad username")
    msg = f"{user}|{now + ttl}"
    return base64.urlsafe_b64encode(f"{msg}|{_sig(msg, secret)}".encode()).decode()


def read_session(token: str, secret: str, now: int) -> str | None:
    try:
        raw = base64.urlsafe_b64decode(token.encode()).decode()
        user, exp, sig = raw.rsplit("|", 2)
        if not hmac.compare_digest(sig, _sig(f"{user}|{exp}", secret)):
            return None
        return user if int(exp) > now else None
    except (ValueError, TypeError):
        return None
