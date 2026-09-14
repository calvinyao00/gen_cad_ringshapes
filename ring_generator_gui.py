#!/usr/bin/env python3
"""Compatibility launcher for the local browser interface.

The filename is kept for the existing Windows BAT launcher. The application
itself no longer imports Tkinter, so the same command works on macOS and
Windows.
"""

from ring_generator_web import main


if __name__ == "__main__":
    main()
