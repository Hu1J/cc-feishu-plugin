"""Tests for restarter.py."""
import pytest
from unittest.mock import patch, MagicMock

from cc_feishu_bridge.restarter import (
    RestartError,
    StartupTimeoutError,
    RestartStep,
    RestartResult,
    _CLI_STEP_LABELS,
    _FEISHU_STEP_LABELS,
    _restart_to,
    run_restart,
    run_restart_cli,
    check_version,
    UpdateStep,
    _UPDATE_CLI_STEP_LABELS,
    _UPDATE_FEISHU_STEP_LABELS,
    _do_update,
    run_update,
    run_update_cli,
)


class TestRestartStepDataclass:
    """Tests for RestartStep dataclass fields."""

    def test_default_values(self):
        """RestartStep has correct default values."""
        step = RestartStep(step=1, total=4, label="准备重启", status="done")
        assert step.step == 1
        assert step.total == 4
        assert step.label == "准备重启"
        assert step.status == "done"
        assert step.detail == ""
        assert step.success is False
        assert step.new_pid is None

    def test_all_fields_set(self):
        """RestartStep accepts all fields including optional ones."""
        step = RestartStep(
            step=3,
            total=4,
            label="等待新进程就绪",
            status="done",
            detail="PID 12345",
            success=False,
            new_pid=12345,
        )
        assert step.step == 3
        assert step.detail == "PID 12345"
        assert step.new_pid == 12345

    def test_final_step_success(self):
        """RestartStep for final success step."""
        step = RestartStep(
            step=4,
            total=4,
            label="重启完成",
            status="final",
            detail="新 PID 99999",
            success=True,
            new_pid=99999,
        )
        assert step.success is True
        assert step.status == "final"
        assert step.new_pid == 99999


class TestRestartResultDataclass:
    """Tests for RestartResult dataclass fields."""

    def test_success_result(self):
        """RestartResult success with new_pid."""
        result = RestartResult(success=True, new_pid=12345)
        assert result.success is True
        assert result.new_pid == 12345

    def test_failure_result(self):
        """RestartResult failure with no new_pid."""
        result = RestartResult(success=False)
        assert result.success is False
        assert result.new_pid is None


class TestStepLabels:
    """Tests for step label constants."""

    def test_cli_step_labels_length(self):
        """_CLI_STEP_LABELS has 4 entries."""
        assert len(_CLI_STEP_LABELS) == 4

    def test_feishu_step_labels_length(self):
        """_FEISHU_STEP_LABELS has 4 entries."""
        assert len(_FEISHU_STEP_LABELS) == 4

    def test_cli_step_labels_match_count(self):
        """Both label lists have the same length."""
        assert len(_CLI_STEP_LABELS) == len(_FEISHU_STEP_LABELS)

    def test_cli_step_labels_content(self):
        """_CLI_STEP_LABELS contains expected Chinese labels."""
        assert "准备重启" in _CLI_STEP_LABELS
        assert "启动新 bridge" in _CLI_STEP_LABELS
        assert "等待新进程就绪" in _CLI_STEP_LABELS
        assert "重启完成" in _CLI_STEP_LABELS

    def test_feishu_step_labels_have_emoji(self):
        """_FEISHU_STEP_LABELS contains emoji."""
        expected_emoji_per_step = ["🛑", "🚀", "⏳", "✅"]
        for i, label in enumerate(_FEISHU_STEP_LABELS):
            assert expected_emoji_per_step[i] in label, f"Step {i+1} label missing expected emoji {expected_emoji_per_step[i]}"


class TestExceptions:
    """Tests for exception classes."""

    def test_restart_error_is_exception(self):
        """RestartError inherits from Exception."""
        assert issubclass(RestartError, Exception)

    def test_startup_timeout_error_is_restart_error(self):
        """StartupTimeoutError inherits from RestartError."""
        assert issubclass(StartupTimeoutError, RestartError)
        assert issubclass(StartupTimeoutError, Exception)

    def test_restart_error_can_be_raised_and_caught(self):
        """RestartError can be raised and caught."""
        with pytest.raises(RestartError):
            raise RestartError("test restart error")

    def test_startup_timeout_error_can_be_raised_and_caught(self):
        """StartupTimeoutError can be raised and caught."""
        with pytest.raises(StartupTimeoutError):
            raise StartupTimeoutError("test timeout")


class TestRestartTo:
    """Tests for _restart_to generator."""

    def test_yields_4_steps(self):
        """_restart_to yields exactly 4 RestartStep objects."""
        with patch("cc_feishu_bridge.restarter._start_bridge") as mock_start:
            mock_start.return_value = 12345
            steps = list(_restart_to())
            assert len(steps) == 4

    def test_final_step_has_success_and_new_pid(self):
        """Final step has success=True and new_pid equal to mocked return value."""
        with patch("cc_feishu_bridge.restarter._start_bridge") as mock_start:
            mock_start.return_value = 99999
            steps = list(_restart_to())
            final_step = steps[-1]
            assert final_step.success is True
            assert final_step.new_pid == 99999
            assert final_step.status == "final"

    def test_calls_file_lock_release_when_provided(self):
        """file_lock.release() is called when file_lock is provided."""
        mock_lock = MagicMock()
        with patch("cc_feishu_bridge.restarter._start_bridge") as mock_start:
            mock_start.return_value = 12345
            list(_restart_to(file_lock=mock_lock))
            mock_lock.release.assert_called_once()

    def test_no_file_lock_release_when_not_provided(self):
        """file_lock.release() is not called when file_lock is None."""
        with patch("cc_feishu_bridge.restarter._start_bridge") as mock_start:
            mock_start.return_value = 12345
            list(_restart_to(file_lock=None))
            # No error means no release() called on None

    def test_step_labels_correct(self):
        """Each step has correct label from _CLI_STEP_LABELS."""
        with patch("cc_feishu_bridge.restarter._start_bridge") as mock_start:
            mock_start.return_value = 12345
            steps = list(_restart_to())
            assert steps[0].label == _CLI_STEP_LABELS[0]
            assert steps[1].label == _CLI_STEP_LABELS[1]
            assert steps[2].label == _CLI_STEP_LABELS[2]
            assert steps[3].label == _CLI_STEP_LABELS[3]

    def test_step_numbers_correct(self):
        """Each step has correct step number and total."""
        with patch("cc_feishu_bridge.restarter._start_bridge") as mock_start:
            mock_start.return_value = 12345
            steps = list(_restart_to())
            for i, s in enumerate(steps):
                assert s.step == i + 1
                assert s.total == 4


class TestRunRestartCli:
    """Tests for run_restart_cli()."""

    def test_no_feishu_yields_steps_from_restart_to(self):
        """run_restart_cli with feishu=None directly yields steps from _restart_to."""
        with patch("cc_feishu_bridge.restarter._start_bridge") as mock_start:
            mock_start.return_value = 12345
            mock_lock = MagicMock()
            steps = list(run_restart_cli(file_lock=mock_lock, feishu=None, chat_id=None))
            assert len(steps) == 4
            assert steps[-1].status == "final"
            assert steps[-1].new_pid == 12345

    def test_no_feishu_accepts_only_file_lock(self):
        """run_restart_cli with feishu=None and no chat_id works."""
        with patch("cc_feishu_bridge.restarter._start_bridge") as mock_start:
            mock_start.return_value = 99999
            mock_lock = MagicMock()
            steps = list(run_restart_cli(file_lock=mock_lock))
            assert len(steps) == 4
            assert steps[-1].new_pid == 99999

    def test_with_feishu_sends_expected_cards(self):
        """run_restart_cli with mock feishu sends expected progress and final cards."""
        with patch("cc_feishu_bridge.restarter._start_bridge") as mock_start:
            mock_start.return_value = 54321
            mock_lock = MagicMock()
            mock_feishu = MagicMock()

            sent_cards = []
            async def mock_send(chat_id, card_md, reply_to):
                sent_cards.append(card_md)

            mock_feishu.send_interactive_reply = mock_send

            steps = list(run_restart_cli(file_lock=mock_lock, feishu=mock_feishu, chat_id="test_chat"))

            # Should have 5 sends: initial + 4 steps (3 progress + 1 final)
            assert len(sent_cards) == 5
            # Initial card
            assert "🔄 正在重启" in sent_cards[0]
            assert "⏳ 准备重启，请稍候..." in sent_cards[0]
            # Progress cards (steps 1-3)
            assert "🔄 正在重启" in sent_cards[1]
            assert "░" in sent_cards[1]  # progress bar
            # Final card
            assert "✅ 重启完成" in sent_cards[4]
            assert "54321" in sent_cards[4]  # new_pid
            assert "🎉 Bridge 已重启" in sent_cards[4]

    def test_feishu_send_error_raises_gracefully(self):
        """run_restart_cli mock feishu raises gracefully on send error."""
        with patch("cc_feishu_bridge.restarter._start_bridge") as mock_start:
            mock_start.return_value = 12345
            mock_lock = MagicMock()
            mock_feishu = MagicMock()

            # First call succeeds, second raises
            call_count = [0]
            async def mock_send(chat_id, card_md, reply_to):
                call_count[0] += 1
                if call_count[0] > 1:
                    raise RuntimeError("Feishu send failed")

            mock_feishu.send_interactive_reply = mock_send

            # Should not raise - send errors are caught
            steps = list(run_restart_cli(file_lock=mock_lock, feishu=mock_feishu, chat_id="test_chat"))

            # All steps still yielded despite send error
            assert len(steps) == 4
            assert steps[-1].status == "final"


class TestRunRestart:
    """Tests for run_restart()."""

    def test_sends_all_4_cards(self):
        """run_restart sends a card for every step (3 progress + 1 final)."""
        import asyncio

        with patch("cc_feishu_bridge.restarter._start_bridge") as mock_start:
            mock_start.return_value = 12345
            mock_lock = MagicMock()
            mock_feishu = MagicMock()

            sent_cards = []
            async def mock_send(chat_id, card_md, reply_to):
                sent_cards.append(card_md)

            mock_feishu.send_interactive_reply = mock_send

            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                loop.run_until_complete(
                    run_restart(file_lock=mock_lock, feishu=mock_feishu,
                                chat_id="test_chat", reply_to_message_id="test_reply")
                )
            finally:
                loop.close()

            # 4 cards sent: steps 1-3 progress + step 4 final
            assert len(sent_cards) == 4, f"Expected 4 cards, got {len(sent_cards)}: {sent_cards}"

            # Steps 1-3 are progress cards
            for i in range(3):
                assert "🔄 正在重启" in sent_cards[i]
                assert "░" in sent_cards[i]  # progress bar
                assert "✅ 重启完成" not in sent_cards[i]

            # Step 4 is the final card
            assert "✅ 重启完成" in sent_cards[3]
            assert "12345" in sent_cards[3]
            assert "🎉 Bridge 已重启" in sent_cards[3]

    def test_progress_cards_have_correct_step_labels(self):
        """Each progress card shows the correct step label from _FEISHU_STEP_LABELS."""
        import asyncio

        with patch("cc_feishu_bridge.restarter._start_bridge") as mock_start:
            mock_start.return_value = 99999
            mock_lock = MagicMock()
            mock_feishu = MagicMock()

            sent_cards = []
            async def mock_send(chat_id, card_md, reply_to):
                sent_cards.append(card_md)

            mock_feishu.send_interactive_reply = mock_send

            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                loop.run_until_complete(
                    run_restart(file_lock=mock_lock, feishu=mock_feishu,
                                chat_id="test_chat", reply_to_message_id="test_reply")
                )
            finally:
                loop.close()

            # Check each progress card has the correct step label
            for i, label in enumerate(_FEISHU_STEP_LABELS[:3]):
                assert label in sent_cards[i], f"Step {i+1} missing label {label}"


# ---------------------------------------------------------------------------
# Tests for update / hot-upgrade support
# ---------------------------------------------------------------------------

class TestCheckVersion:
    """Tests for check_version()."""

    def test_check_version_returns_tuple(self):
        """check_version returns (current_ver, latest_ver) as strings."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout="cc-feishu-bridge (0.2.5)",
                stderr="",
            )
            current, latest = check_version()
            assert isinstance(current, str)
            assert isinstance(latest, str)
            assert latest == "0.2.5"

    def test_check_version_raises_on_failure(self):
        """check_version raises RestartError when pip index versions fails."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="error")
            with pytest.raises(RestartError, match="pip index versions failed"):
                check_version()

    def test_check_version_raises_on_parse_error(self):
        """check_version raises RestartError when output cannot be parsed."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="unexpected output", stderr="")
            with pytest.raises(RestartError, match="无法解析"):
                check_version()

    def test_check_version_raises_on_timeout(self):
        """check_version raises RestartError on subprocess timeout."""
        import subprocess
        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = subprocess.TimeoutExpired("pip", 15)
            with pytest.raises(RestartError, match="检查版本超时"):
                check_version()


class TestUpdateStepDataclass:
    """Tests for UpdateStep dataclass."""

    def test_default_values(self):
        """UpdateStep has correct default values."""
        step = UpdateStep(step=1, total=7, label="检查更新", status="done")
        assert step.step == 1
        assert step.total == 7
        assert step.label == "检查更新"
        assert step.status == "done"
        assert step.detail == ""
        assert step.success is False
        assert step.new_pid is None

    def test_all_fields_set(self):
        """UpdateStep accepts all fields including optional ones."""
        step = UpdateStep(
            step=7, total=7, label="重启完成",
            status="final", detail="新 PID 99999",
            success=True, new_pid=99999,
        )
        assert step.step == 7
        assert step.success is True
        assert step.new_pid == 99999


class TestUpdateStepLabels:
    """Tests for update step label constants."""

    def test_update_cli_step_labels_length(self):
        """_UPDATE_CLI_STEP_LABELS has 7 entries."""
        assert len(_UPDATE_CLI_STEP_LABELS) == 7

    def test_update_feishu_step_labels_length(self):
        """_UPDATE_FEISHU_STEP_LABELS has 7 entries."""
        assert len(_UPDATE_FEISHU_STEP_LABELS) == 7

    def test_update_cli_step_labels_content(self):
        """_UPDATE_CLI_STEP_LABELS contains expected labels."""
        expected = ["检查更新", "下载新版本", "下载完成", "准备重启", "启动新 bridge", "等待新进程就绪", "重启完成"]
        assert _UPDATE_CLI_STEP_LABELS == expected


class TestDoUpdate:
    """Tests for _do_update generator."""

    def test_already_latest_yields_skip(self):
        """_do_update yields skip steps when already on latest version."""
        with patch("cc_feishu_bridge.restarter.check_version") as mock_cv:
            mock_cv.return_value = ("0.2.5", "0.2.5")  # same version
            steps = list(_do_update())
            assert len(steps) == 2
            assert steps[0].status == "done"
            assert steps[0].step == 1
            assert steps[1].status == "skip"
            assert steps[1].step == 2
            assert steps[1].success is True

    def test_has_7_steps_on_update(self):
        """_do_update yields 7 steps when update is needed."""
        with patch("cc_feishu_bridge.restarter.check_version") as mock_cv:
            mock_cv.return_value = ("0.2.5", "0.2.6")  # update available
            with patch("subprocess.run") as mock_pip:
                mock_pip.return_value = MagicMock(returncode=0)
                with patch("cc_feishu_bridge.restarter._start_bridge") as mock_start:
                    mock_start.return_value = 12345
                    mock_lock = MagicMock()
                    steps = list(_do_update(file_lock=mock_lock))
                    assert len(steps) == 7
                    assert steps[0].step == 1
                    assert steps[1].step == 2
                    assert steps[2].step == 3
                    assert steps[6].step == 7
                    assert steps[6].status == "final"
                    assert steps[6].new_pid == 12345

    def test_already_latest_detail_contains_version(self):
        """Skip step detail contains current version info."""
        with patch("cc_feishu_bridge.restarter.check_version") as mock_cv:
            mock_cv.return_value = ("0.2.5", "0.2.5")
            steps = list(_do_update())
            assert "0.2.5" in steps[1].detail
            assert "已是最新" in steps[1].detail

    def test_restart_step1_maps_to_update_step4_label(self):
        """Update step 4 (first restart step) has label '准备重启'.

        Regression test: restart_step.step=1 must map to _UPDATE_CLI_STEP_LABELS[4]
        which should be '准备重启' (the first restart step label).
        """
        with patch("cc_feishu_bridge.restarter.check_version") as mock_cv:
            mock_cv.return_value = ("0.2.5", "0.2.6")  # update available
            with patch("subprocess.run") as mock_pip:
                mock_pip.return_value = MagicMock(returncode=0)
                with patch("cc_feishu_bridge.restarter._start_bridge") as mock_start:
                    mock_start.return_value = 12345
                    mock_lock = MagicMock()
                    steps = list(_do_update(file_lock=mock_lock))
                    # steps[3] is update step 4 (the first restart step, restart_step.step=1)
                    assert steps[3].step == 4
                    assert steps[3].label == "准备重启"

    def test_pip_install_failure_raises_restart_error(self):
        """_do_update raises RestartError when pip install returns non-zero."""
        with patch("cc_feishu_bridge.restarter.check_version") as mock_cv:
            mock_cv.return_value = ("0.2.5", "0.2.6")  # update available
            with patch("subprocess.run") as mock_pip:
                mock_pip.return_value = MagicMock(
                    returncode=1,
                    stdout="",
                    stderr="Could not find a version that satisfies the requirement",
                )
                mock_lock = MagicMock()
                with pytest.raises(RestartError, match="pip install 失败"):
                    list(_do_update(file_lock=mock_lock))


class TestRunUpdateCliAlreadyLatest:
    """Tests for run_update_cli early return when already latest."""

    def test_already_latest_returns_early(self):
        """run_update_cli returns early without yielding restart steps when already latest."""
        with patch("cc_feishu_bridge.restarter.check_version") as mock_cv:
            mock_cv.return_value = ("0.2.5", "0.2.5")
            mock_lock = MagicMock()
            # No feishu — should directly yield from _do_update
            steps = list(run_update_cli(file_lock=mock_lock, feishu=None, chat_id=None))
            assert len(steps) == 2
            assert steps[1].status == "skip"

    def test_already_latest_sends_card_and_returns(self):
        """run_update_cli with feishu sends already-latest card and returns."""
        with patch("cc_feishu_bridge.restarter.check_version") as mock_cv:
            mock_cv.return_value = ("0.2.5", "0.2.5")
            mock_lock = MagicMock()
            mock_feishu = MagicMock()

            sent_cards = []
            async def mock_send(chat_id, card_md, reply_to):
                sent_cards.append(card_md)

            mock_feishu.send_interactive_reply = mock_send

            steps = list(run_update_cli(file_lock=mock_lock, feishu=mock_feishu, chat_id="test_chat"))

            # Should have sent initial card + already-latest card, then returned
            assert len(sent_cards) == 2
            assert "🔄 正在更新" in sent_cards[0]
            assert "✅ 已是最新版本" in sent_cards[1]
            assert "0.2.5" in sent_cards[1]
            # No steps yielded when status == "skip" (returns immediately after sending card)
            assert len(steps) == 0


class TestRunUpdateCliWithUpdate:
    """Tests for run_update_cli with actual update flow."""

    def test_with_update_yields_7_steps(self):
        """run_update_cli with update needed yields all 7 steps."""
        with patch("cc_feishu_bridge.restarter.check_version") as mock_cv:
            mock_cv.return_value = ("0.2.5", "0.2.6")
            with patch("subprocess.run") as mock_pip:
                mock_pip.return_value = MagicMock(returncode=0)
                with patch("cc_feishu_bridge.restarter._start_bridge") as mock_start:
                    mock_start.return_value = 99999
                    mock_lock = MagicMock()
                    mock_feishu = MagicMock()

                    sent_cards = []
                    async def mock_send(chat_id, card_md, reply_to):
                        sent_cards.append(card_md)

                    mock_feishu.send_interactive_reply = mock_send

                    steps = list(run_update_cli(file_lock=mock_lock, feishu=mock_feishu, chat_id="test_chat"))

                    # Should have initial + 7 step cards = 8 sends
                    assert len(sent_cards) == 8
                    # 7 steps yielded
                    assert len(steps) == 7
                    assert steps[6].status == "final"
                    assert steps[6].new_pid == 99999

    def test_no_feishu_yields_7_steps(self):
        """run_update_cli without feishu yields 7 steps directly."""
        with patch("cc_feishu_bridge.restarter.check_version") as mock_cv:
            mock_cv.return_value = ("0.2.5", "0.2.6")
            with patch("subprocess.run") as mock_pip:
                mock_pip.return_value = MagicMock(returncode=0)
                with patch("cc_feishu_bridge.restarter._start_bridge") as mock_start:
                    mock_start.return_value = 12345
                    mock_lock = MagicMock()
                    steps = list(run_update_cli(file_lock=mock_lock, feishu=None, chat_id=None))
                    assert len(steps) == 7
                    assert steps[6].new_pid == 12345

