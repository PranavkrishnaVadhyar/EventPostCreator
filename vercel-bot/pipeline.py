"""
pipeline.py — Gemini pipeline (synchronous re-export)
======================================================

Re-exports the three pipeline functions from main.py so that
api/webhook.py can import them with a clean name that won't
conflict with Vercel's module resolution.

main.py must live at the project root (same level as this file).
"""

from main import extract_details, generate_hook, generate_post

__all__ = ["extract_details", "generate_hook", "generate_post"]
