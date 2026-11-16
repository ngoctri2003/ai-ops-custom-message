"""Print a password hash for the AUTH_USERS env var, and a random AUTH_SECRET.

Usage: python tools/hash_password.py   (asks for the password, nothing is stored)
"""
import getpass
import os
import secrets
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from app.auth import hash_password  # noqa: E402

password = getpass.getpass("Password: ")
if len(password) < 12:
    sys.exit("Use at least 12 characters.")
print("Hash for AUTH_USERS:\n" + hash_password(password))
print("\nAUTH_SECRET (only needed once for the whole project):\n" + secrets.token_urlsafe(48))
