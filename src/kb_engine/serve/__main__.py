"""``python -m kb_engine.serve`` entrypoint (generic serve CLI)."""

import sys

from kb_engine.serve.cli import main

if __name__ == "__main__":
    sys.exit(main())
