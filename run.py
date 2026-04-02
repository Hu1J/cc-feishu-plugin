"""PyInstaller entry point — wraps cc_feishu_bridge.main:main for binary builds."""
import sys
try:
    sys.stdout.reconfigure(encoding="utf-8")
except (AttributeError, TypeError):
    pass

from cc_feishu_bridge.main import main

if __name__ == "__main__":
    main()
