"""skillgate: a regression gate for skills that agents update themselves."""

from skillgate.config import Config, ConfigError, load_config
from skillgate.gate import Decision, Gate, GateError

__all__ = ["Config", "ConfigError", "Decision", "Gate", "GateError", "load_config"]
__version__ = "0.1.0"
