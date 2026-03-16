"""
User model synced from Clerk.

Minimal model — just the Clerk user ID. Authentication and user
metadata are handled by Clerk; we only need the ID for foreign keys.
"""

from sqlalchemy import Column, String

from .base import Base


class User(Base):
    """User model synced from Clerk."""

    __tablename__ = "users"

    id = Column(String, primary_key=True)  # Clerk User ID (user_xxx)
