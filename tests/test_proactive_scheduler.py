"""Tests for proactive scheduler."""
from datetime import datetime, time
from unittest.mock import patch
import pytest

from cc_feishu_bridge.proactive_scheduler import _is_in_time_window


class TestIsInTimeWindow:
    """Test _is_in_time_window helper."""

    def test_within_daytime_window(self):
        """9am is within 08:00-22:00 window."""
        with patch("cc_feishu_bridge.proactive_scheduler.datetime") as mock_dt:
            mock_dt.now.return_value = datetime(2026, 4, 3, 9, 0, 0)
            mock_dt.side_effect = lambda *args, **kwargs: datetime(*args, **kwargs)
            result = _is_in_time_window("08:00", "22:00")
            assert result is True

    def test_outside_window_too_early(self):
        """7am is outside 08:00-22:00 window."""
        with patch("cc_feishu_bridge.proactive_scheduler.datetime") as mock_dt:
            mock_dt.now.return_value = datetime(2026, 4, 3, 7, 0, 0)
            mock_dt.side_effect = lambda *args, **kwargs: datetime(*args, **kwargs)
            result = _is_in_time_window("08:00", "22:00")
            assert result is False

    def test_outside_window_too_late(self):
        """23pm is outside 08:00-22:00 window."""
        with patch("cc_feishu_bridge.proactive_scheduler.datetime") as mock_dt:
            mock_dt.now.return_value = datetime(2026, 4, 3, 23, 0, 0)
            mock_dt.side_effect = lambda *args, **kwargs: datetime(*args, **kwargs)
            result = _is_in_time_window("08:00", "22:00")
            assert result is False

    def test_at_exact_start_boundary(self):
        """Exactly 08:00 is within the window (inclusive start)."""
        with patch("cc_feishu_bridge.proactive_scheduler.datetime") as mock_dt:
            mock_dt.now.return_value = datetime(2026, 4, 3, 8, 0, 0)
            mock_dt.side_effect = lambda *args, **kwargs: datetime(*args, **kwargs)
            result = _is_in_time_window("08:00", "22:00")
            assert result is True

    def test_at_exact_end_boundary(self):
        """Exactly 22:00 is outside the window (exclusive end)."""
        with patch("cc_feishu_bridge.proactive_scheduler.datetime") as mock_dt:
            mock_dt.now.return_value = datetime(2026, 4, 3, 22, 0, 0)
            mock_dt.side_effect = lambda *args, **kwargs: datetime(*args, **kwargs)
            result = _is_in_time_window("08:00", "22:00")
            assert result is False