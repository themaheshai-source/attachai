"""Production/local entry point for the AttachAI web platform."""
from .api import create_app

app = create_app()
