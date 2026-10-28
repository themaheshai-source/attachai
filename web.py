"""Convenience root entrypoint: uvicorn web:app --reload"""
from advanced_rag.web import app

__all__ = ["app"]
