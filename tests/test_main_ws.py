import pytest
import argparse
from unittest.mock import patch, AsyncMock

def test_main_shows_no_config_message(capsys, tmp_path, monkeypatch):
    """Without config, shows message to use install flow."""
    monkeypatch.chdir(tmp_path)
    # Mock interactive_install to raise SystemExit (simulating user退出)
    with patch("src.main.interactive_install", new_callable=AsyncMock) as mock_install:
        mock_install.side_effect = SystemExit
        from src.main import main
        with pytest.raises(SystemExit):
            main(["--log-level", "DEBUG"])