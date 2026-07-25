"""
Vercel serverless entry point for ClipVault Flask app.
"""
import sys
import os

# Add parent to path so imports work
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import app

# Vercel expects a WSGI callable named 'app'
# Flask's app is already a WSGI app, so this works directly
