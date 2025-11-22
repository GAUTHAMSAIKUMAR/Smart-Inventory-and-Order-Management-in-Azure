from datetime import datetime, timedelta
from jose import JWTError, jwt
from passlib.context import CryptContext
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer

# ---------------- JWT CONFIG ----------------
SECRET_KEY = "smartinventorysupersecretkey"
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60

# ---------------- PASSWORD HASHING CONFIG ----------------
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# OAuth2 password flow (used by /auth/login endpoint)
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="auth/login")

# ---------------- USERS CONFIG ----------------
# ✅ Keep passwords short (< 72 chars) for bcrypt
raw_users = {
    "admin": {"password": "admin123", "role": "admin"},
    "warehouse": {"password": "warehouse123", "role": "warehouse"},
}

# ✅ Hash at runtime (inside a loop) instead of dict comprehension
# This helps avoid the bcrypt import issues on Windows and keeps logs cleaner
fake_users_db = {}
for username, user in raw_users.items():
    password = user["password"][:72]  # ensure bcrypt-safe
    fake_users_db[username] = {
        "username": username,
        "hashed_password": pwd_context.hash(password),
        "role": user["role"],
    }

# ---------------- HELPERS ----------------
def verify_password(plain_password, hashed_password):
    """Verify a plain password against its hashed version."""
    return pwd_context.verify(plain_password, hashed_password)


def authenticate_user(username: str, password: str):
    """Check if a user exists and password is valid."""
    user = fake_users_db.get(username)
    if not user:
        return None
    if not verify_password(password, user["hashed_password"]):
        return None
    return user


def create_access_token(data: dict):
    """Generate JWT token with expiry time."""
    to_encode = data.copy()
    expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


def verify_token(token: str = Depends(oauth2_scheme)):
    """Decode JWT token and verify authenticity."""
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return payload
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
        )


# ---------------- ROLE-BASED ACCESS ----------------
def require_role(*allowed_roles):
    """
    Dependency to restrict access based on user role.
    Example:
        Depends(require_role("admin"))
        Depends(require_role("admin", "warehouse"))
    """
    def role_checker(payload=Depends(verify_token)):
        user_role = payload.get("role")
        if user_role not in allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Access denied. Requires one of {allowed_roles} roles.",
            )
        return payload

    return role_checker
