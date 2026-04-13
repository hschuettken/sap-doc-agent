import pytest
from unittest.mock import patch
from sap_doc_agent.cli import main


def test_cli_help(capsys):
    with pytest.raises(SystemExit) as exc_info:
        import sys

        with patch.object(sys, "argv", ["sap-doc-agent"]):
            import asyncio

            asyncio.run(main())
    assert exc_info.value.code in (0, 1)


def test_cli_missing_config(capsys):
    import sys

    with patch.object(sys, "argv", ["sap-doc-agent", "--config", "/nonexistent.yaml", "--scan"]):
        with pytest.raises(SystemExit) as exc_info:
            import asyncio

            asyncio.run(main())
        assert exc_info.value.code == 1
