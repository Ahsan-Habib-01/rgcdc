"""
WSGI & ASGI Entrypoint for PythonAnywhere / Gunicorn / Uvicorn Deployment
Allows FastAPI to run seamlessly on both standard WSGI hosts (PythonAnywhere Free Plan)
and ASGI hosts (Render, Railway, Uvicorn).
"""
import os
import sys

project_home = os.path.dirname(os.path.abspath(__file__))
if project_home not in sys.path:
    sys.path.insert(0, project_home)

from backend.main import app as fastapi_app

try:
    from a2wsgi import ASGIMiddleware
    application = ASGIMiddleware(fastapi_app)
except ImportError:
    application = fastapi_app
