"""edp-contracts — single-sourced base contracts for the eda-base system.

Public surface only (HLD §5). Anything not re-exported here is internal.
"""

from .broker import (
    CORE_KINDS,
    BrokerMessage,
    is_registered,
    register_kind,
    registered_kinds,
)
from .errors import ALL_CODES, RETRYABLE_CODES, EnvelopeViolation, ErrorCode
from .logging import LoggerLike, LogRecordModel, get_logger
from .service import HealthStatus, Microservice, mount
from .skill import (
    SkillHeader,
    SkillIO,
    SkillRule,
    Violation,
    parse_skill_header,
    validate_skill,
)
from .tool import Tool, ToolError, ToolOk, ToolResult

__version__ = "0.1.0"

__all__ = [
    # service
    "Microservice",
    "HealthStatus",
    "mount",
    # tool
    "Tool",
    "ToolOk",
    "ToolError",
    "ToolResult",
    # skill
    "validate_skill",
    "parse_skill_header",
    "SkillHeader",
    "SkillIO",
    "SkillRule",
    "Violation",
    # broker
    "BrokerMessage",
    "register_kind",
    "is_registered",
    "registered_kinds",
    "CORE_KINDS",
    # logging
    "get_logger",
    "LoggerLike",
    "LogRecordModel",
    # errors
    "EnvelopeViolation",
    "ErrorCode",
    "ALL_CODES",
    "RETRYABLE_CODES",
]
