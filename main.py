"""
Backward compatibility wrapper for main.py.
For new usage, please use: python -m geoguessr fetch <username> [options]
"""
from geoguessr.__main__ import main

if __name__ == "__main__":
    main()
