import pytest

from sepia import __version__
from sepia.cli import main


def test_main_version_flag_prints_version(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        main(["--version"])
    out = capsys.readouterr().out
    assert exc.value.code == 0, f"Expected exit code 0, got {exc.value.code}"
    assert __version__ in out, f"Expected {__version__!r} in {out!r}"
