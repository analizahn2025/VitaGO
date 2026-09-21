#!/usr/bin/env python
"""Django command-line utility for VitaGo."""

import os
import sys


def main() -> None:
    """Run administrative tasks."""
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.local")

    try:
        from django.core.management import execute_from_command_line
    except ImportError as exc:
        raise ImportError(
            "Django is not available. Install the dependencies from "
            "requirements/base.txt inside the project virtual environment."
        ) from exc

    execute_from_command_line(sys.argv)


if __name__ == "__main__":
    main()

