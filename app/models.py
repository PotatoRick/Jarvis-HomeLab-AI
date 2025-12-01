"""
Pydantic models for request/response validation and data structures.
"""

from pydantic import BaseModel, Field
from typing import List, Dict, Optional, Literal
from datetime import datetime
from enum import Enum


class RiskLevel(str, Enum):
    """Risk level classification for remediation actions."""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class AlertStatus(str, Enum):
    """Alertmanager alert status."""
    FIRING = "firing"
    RESOLVED = "resolved"


class AlertLabels(BaseModel):
    """Prometheus alert labels."""
    alertname: str
    instance: str = "unknown"
    severity: str = "warning"
    # Allow additional dynamic labels
    model_config = {"extra": "allow"}


class AlertAnnotations(BaseModel):
    """Prometheus alert annotations."""
    description: Optional[str] = None
    summary: Optional[str] = None
    # Allow additional dynamic annotations
    model_config = {"extra": "allow"}


class Alert(BaseModel):
    """Single alert from Alertmanager."""
    status: AlertStatus
    labels: AlertLabels
    annotations: AlertAnnotations
    startsAt: str
    endsAt: Optional[str] = None
    fingerprint: str
    generatorURL: Optional[str] = None


class AlertmanagerWebhook(BaseModel):
    """Alertmanager webhook payload."""
    version: str = "4"
    groupKey: str
    status: AlertStatus
    receiver: str
    groupLabels: Dict[str, str] = {}
    commonLabels: Dict[str, str] = {}
    commonAnnotations: Dict[str, str] = {}
    externalURL: str
    alerts: List[Alert]


class RemediationAttempt(BaseModel):
    """Database model for remediation attempt."""
    id: Optional[int] = None
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    alert_name: str
    alert_instance: str
    alert_fingerprint: str
    severity: str
    attempt_number: int
    ai_analysis: Optional[str] = None
    ai_reasoning: Optional[str] = None
    remediation_plan: Optional[str] = None
    commands_executed: List[str] = []
    command_outputs: List[str] = []
    exit_codes: List[int] = []
    success: bool = False
    error_message: Optional[str] = None
    execution_duration_seconds: Optional[int] = None
    risk_level: Optional[RiskLevel] = None
    escalated: bool = False
    user_approved: Optional[bool] = None
    discord_message_id: Optional[str] = None
    discord_thread_id: Optional[str] = None


class ClaudeAnalysis(BaseModel):
    """Claude AI remediation analysis response."""
    analysis: str = Field(..., description="Root cause analysis")
    commands: List[str] = Field(..., description="Commands to execute")
    risk: RiskLevel = Field(..., description="Risk level assessment")
    expected_outcome: str = Field(..., description="Expected result after execution")
    reasoning: str = Field(..., description="Explanation of why these commands will work")
    estimated_duration: str = Field(default="30 seconds", description="Expected execution time")


class CommandValidationResult(BaseModel):
    """Result of command safety validation."""
    safe: bool
    validated_commands: List[str] = []
    rejected_commands: List[str] = []
    rejection_reasons: List[str] = []


class SSHExecutionResult(BaseModel):
    """Result of SSH command execution."""
    success: bool
    commands: List[str]
    outputs: List[str]
    exit_codes: List[int]
    duration_seconds: int
    error: Optional[str] = None


class HostType(str, Enum):
    """Target host types."""
    NEXUS = "nexus"
    HOMEASSISTANT = "homeassistant"
    OUTPOST = "outpost"
    SKYNET = "skynet"


class LogGatherRequest(BaseModel):
    """Parameters for gathering logs from a system."""
    host: HostType
    service_type: Literal["docker", "systemd", "system"]
    service_name: Optional[str] = None
    lines: int = 100


class ServiceRestartRequest(BaseModel):
    """Parameters for restarting a service."""
    host: HostType
    service_type: Literal["docker", "systemd", "homeassistant"]
    service_name: str


class CommandExecutionRequest(BaseModel):
    """Parameters for executing a safe command."""
    host: HostType
    command: str


class MaintenanceWindow(BaseModel):
    """Maintenance mode configuration."""
    start_time: datetime = Field(default_factory=datetime.utcnow)
    end_time: datetime
    reason: str
    created_by: str


class HealthCheckResponse(BaseModel):
    """Health check endpoint response."""
    status: str
    version: str
    timestamp: datetime
    database_connected: bool
    maintenance_mode: bool
