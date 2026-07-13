from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class RawSession:
    name: str        # short name (no PID prefix)
    full_name: str   # unique identifier used for all commands
    attached: bool


class SessionBackend(ABC):
    @abstractmethod
    def list_sessions(self) -> list[RawSession]:
        """Return all live multiplexer sessions."""

    @abstractmethod
    def launch(self, name: str, shell_cmd: str, cwd: str | None = None,
               cols: int = 220, rows: int = 50) -> None:
        """Start a new detached session running shell_cmd."""

    @abstractmethod
    def kill(self, full_name: str) -> None:
        """Terminate a session."""

    @abstractmethod
    def send_input(self, full_name: str, text: str) -> None:
        """Send text + Enter to a session."""

    @abstractmethod
    def send_raw(self, full_name: str, text: str) -> None:
        """Send raw bytes to a session with no appended Enter."""

    @abstractmethod
    def attach_cmd(self, full_name: str) -> str:
        """Return the shell command string to attach to this session."""

    @abstractmethod
    def capture(self, full_name: str) -> list[str]:
        """Capture current visible screen content as lines."""
