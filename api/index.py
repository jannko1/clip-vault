"""Vercel serverless entry point for ClipVault."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app import app as application
# Vercel expects 'app' variable
app = application
