"""Pytest fixtures for the BNPL decision service tests."""
import os
import sys

# Add service directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
