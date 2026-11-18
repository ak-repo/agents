"""Loads .env (if present) into the environment before any settings are read.

Real environment variables always win over values in .env.
"""
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent / ".env", override=False)
