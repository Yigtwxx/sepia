from pathlib import Path

import pytest

from sepia import __version__
from sepia.cli import main
from sepia.painter import PainterError


def test_main_version_flag_prints_version(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        main(["--version"])
    out = capsys.readouterr().out
    assert exc.value.code == 0, f"Expected exit code 0, got {exc.value.code}"
    assert __version__ in out, f"Expected {__version__!r} in {out!r}"


def test_main_unknown_flag_exits_with_usage_error(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit) as exc:
        main(["--nope"])
    assert exc.value.code == 2, f"Expected exit code 2, got {exc.value.code}"
    assert "--nope" in capsys.readouterr().err, "The bad flag must be reported"


def test_main_without_flags_runs_the_prompt_window(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("sepia.repl.run_repl", lambda: 7)
    assert main([]) == 7, "main must return the prompt window's exit code"


def test_main_viewer_flag_runs_the_viewer_with_the_session_file(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[Path] = []

    def fake_viewer(session_file: Path) -> int:
        calls.append(session_file)
        return 3

    monkeypatch.setattr("sepia.viewer.run_viewer", fake_viewer)
    monkeypatch.setattr("sepia.repl.run_repl", lambda: pytest.fail("prompt ran"))
    assert main(["--viewer", "session.json"]) == 3, "Viewer exit code not returned"
    assert calls == [Path("session.json")], f"Wrong session file: {calls}"


def test_main_viewer_flag_wins_over_download(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("sepia.viewer.run_viewer", lambda session_file: 0)
    monkeypatch.setattr(
        "sepia.painter.download_local_model", lambda: pytest.fail("downloaded")
    )
    assert main(["--viewer", "s.json", "--download"]) == 0, "Viewer must run alone"


def test_main_download_flag_prints_the_model_folder(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr("sepia.painter.download_local_model", lambda: "models/klein")
    monkeypatch.setattr("sepia.repl.run_repl", lambda: pytest.fail("prompt ran"))
    code = main(["--download"])
    captured = capsys.readouterr()
    assert code == 0, f"Expected exit code 0, got {code}"
    assert captured.out.strip() == "downloaded to models/klein", captured.out


def test_main_download_failure_reports_on_stderr_and_exits_1(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def fail() -> str:
        raise PainterError("the local extra is not installed")

    monkeypatch.setattr("sepia.painter.download_local_model", fail)
    code = main(["--download"])
    captured = capsys.readouterr()
    assert code == 1, f"Expected exit code 1, got {code}"
    assert "the local extra is not installed" in captured.err, captured.err
    assert captured.out == "", f"Nothing belongs on stdout, got {captured.out!r}"


class _Stream:
    """A stream that records how `main` reconfigures it."""

    def __init__(self, error: type[Exception] | None = None) -> None:
        self.encodings: list[str] = []
        self._error = error

    def reconfigure(self, *, encoding: str) -> None:
        if self._error is not None:
            raise self._error("cannot reconfigure")
        self.encodings.append(encoding)

    def write(self, text: str) -> int:
        return len(text)

    def flush(self) -> None:
        pass


def test_main_switches_both_output_streams_to_utf8(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    out, err = _Stream(), _Stream()
    monkeypatch.setattr("sys.stdout", out)
    monkeypatch.setattr("sys.stderr", err)
    monkeypatch.setattr("sepia.repl.run_repl", lambda: 0)
    main([])
    assert out.encodings == ["utf-8"], f"stdout: {out.encodings}"
    assert err.encodings == ["utf-8"], f"stderr: {err.encodings}"


@pytest.mark.parametrize("error", [OSError, ValueError])
def test_main_stream_that_refuses_utf8_does_not_stop_startup(
    monkeypatch: pytest.MonkeyPatch, error: type[Exception]
) -> None:
    out, err = _Stream(error), _Stream()
    monkeypatch.setattr("sys.stdout", out)
    monkeypatch.setattr("sys.stderr", err)
    monkeypatch.setattr("sepia.repl.run_repl", lambda: 5)
    assert main([]) == 5, "A failing reconfigure must be ignored"
    assert err.encodings == ["utf-8"], "The other stream must still be switched"
