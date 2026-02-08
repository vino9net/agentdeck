"""Tests for clipboard image copy."""

from unittest.mock import patch

import pytest

from agentdeck.sessions.clipboard import (
    copy_image_to_clipboard,
)


class TestMacOS:
    """macOS clipboard via osascript."""

    @patch("agentdeck.sessions.clipboard.sys")
    @patch("agentdeck.sessions.clipboard.subprocess.run")
    def test_png(self, mock_run, mock_sys):
        mock_sys.platform = "darwin"
        mock_run.return_value.returncode = 0

        copy_image_to_clipboard("/tmp/img.png", "png")

        args = mock_run.call_args
        cmd = args[0][0]
        assert cmd[0] == "osascript"
        script = cmd[2]
        assert "«class PNGf»" in script
        assert "/tmp/img.png" in script

    @patch("agentdeck.sessions.clipboard.sys")
    @patch("agentdeck.sessions.clipboard.subprocess.run")
    def test_jpeg(self, mock_run, mock_sys):
        mock_sys.platform = "darwin"
        mock_run.return_value.returncode = 0

        copy_image_to_clipboard("/tmp/img.jpg", "jpeg")

        script = mock_run.call_args[0][0][2]
        assert "JPEG picture" in script

    @patch("agentdeck.sessions.clipboard.sys")
    @patch("agentdeck.sessions.clipboard.subprocess.run")
    def test_failure_raises(self, mock_run, mock_sys):
        mock_sys.platform = "darwin"
        mock_run.return_value.returncode = 1
        mock_run.return_value.stderr = "osascript error"

        with pytest.raises(RuntimeError, match="osascript"):
            copy_image_to_clipboard("/tmp/img.png", "png")


class TestLinux:
    """Linux clipboard via xclip / wl-copy."""

    @patch("agentdeck.sessions.clipboard.sys")
    @patch("agentdeck.sessions.clipboard.shutil.which")
    @patch("agentdeck.sessions.clipboard.subprocess.run")
    def test_xclip_png(self, mock_run, mock_which, mock_sys):
        mock_sys.platform = "linux"
        mock_which.side_effect = lambda x: "/usr/bin/xclip" if x == "xclip" else None
        mock_run.return_value.returncode = 0

        copy_image_to_clipboard("/tmp/img.png", "png")

        cmd = mock_run.call_args[0][0]
        assert "xclip" in cmd
        assert "image/png" in cmd
        assert "/tmp/img.png" in cmd

    @patch("agentdeck.sessions.clipboard.sys")
    @patch("agentdeck.sessions.clipboard.shutil.which")
    @patch("agentdeck.sessions.clipboard.subprocess.run")
    def test_xclip_jpeg(self, mock_run, mock_which, mock_sys):
        mock_sys.platform = "linux"
        mock_which.side_effect = lambda x: "/usr/bin/xclip" if x == "xclip" else None
        mock_run.return_value.returncode = 0

        copy_image_to_clipboard("/tmp/img.jpg", "jpeg")

        cmd = mock_run.call_args[0][0]
        assert "image/jpeg" in cmd

    @patch(
        "agentdeck.sessions.clipboard.open",
        create=True,
    )
    @patch("agentdeck.sessions.clipboard.sys")
    @patch("agentdeck.sessions.clipboard.shutil.which")
    @patch("agentdeck.sessions.clipboard.subprocess.run")
    def test_wl_copy_fallback(self, mock_run, mock_which, mock_sys, mock_open):
        mock_sys.platform = "linux"
        mock_which.side_effect = lambda x: "/usr/bin/wl-copy" if x == "wl-copy" else None
        mock_run.return_value.returncode = 0

        copy_image_to_clipboard("/tmp/img.png", "png")

        cmd = mock_run.call_args[0][0]
        assert "wl-copy" in cmd
        assert "image/png" in cmd

    @patch("agentdeck.sessions.clipboard.sys")
    @patch("agentdeck.sessions.clipboard.shutil.which")
    def test_no_tool_raises(self, mock_which, mock_sys):
        mock_sys.platform = "linux"
        mock_which.return_value = None

        with pytest.raises(RuntimeError, match="No clipboard tool"):
            copy_image_to_clipboard("/tmp/img.png", "png")
