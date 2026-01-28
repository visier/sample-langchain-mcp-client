#!/usr/bin/env python3
"""
Entry point for the Visier MCP LangChain client.
Run this file to start the application.
"""

import sys
import os

# Add the project root to Python path
project_root = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, project_root)

# Import and run the main client
from client.client import main
import asyncio

if __name__ == "__main__":
    asyncio.run(main())