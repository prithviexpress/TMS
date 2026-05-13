"""Declarative base shared by all gate-service ORM models."""

from __future__ import annotations

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Common SQLAlchemy declarative base for gate-service."""
