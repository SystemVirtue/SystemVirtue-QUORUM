from typing import Any, Literal
from pydantic import BaseModel, Field


Mode = Literal["fast", "balanced", "deep", "adversarial", "auditor"]
TaskType = Literal[
    "code_generation", "bug_fix", "code_review", "debugging", "refactor",
    "architecture", "test_generation", "security_review", "devops",
    "database_migration", "frontend_ui", "documentation", "explanation",
    "reasoning", "general_qa",
]


class ChatMessage(BaseModel):
    role: str
    content: str | list[Any] | None = None


class SystemVirtueOptions(BaseModel):
    require_approval: bool = False
    preferred_models: list[str] = Field(default_factory=list)
    banned_models: list[str] = Field(default_factory=list)
    show_trace: Literal["full", "standard", "minimal"] = "standard"
    allow_paid: bool = False
    consensus_mode: Literal["hub_synthesis", "deterministic"] = "hub_synthesis"


class ChatCompletionRequest(BaseModel):
    model: str = "SystemVirtue/quorum-free-balanced"
    messages: list[ChatMessage]
    stream: bool = False
    temperature: float | None = None
    max_tokens: int | None = None
    SystemVirtue: SystemVirtueOptions = Field(default_factory=SystemVirtueOptions)


class ClassificationProfile(BaseModel):
    task_type: TaskType
    primary_language: Literal["python", "typescript", "javascript", "rust", "go", "sql", "other", "none"]
    weights: dict[str, float]
    estimated_difficulty: int
    min_context_tokens: int
    risk_level: Literal["low", "medium", "high"]
    recommended_mode: Mode
    recommended_roles: list[str]
    rationale: str
    compatibility: dict[str, Any] = Field(default_factory=dict)


class ModelCapabilities(BaseModel):
    coding_strength: dict[str, float]
    reasoning: float = 5.0
    math: float = 5.0
    long_context: float = 5.0
    tool_use: float = 5.0
    critique: float = 5.0
    synthesis: float = 5.0
    json_reliability: float = 5.0
    model_class: Literal["coder", "reasoner", "generalist"] = "generalist"
    generic: dict[str, float] = Field(default_factory=dict)


class ModelTelemetry(BaseModel):
    p50_latency_ms: int = 8000
    p95_latency_ms: int = 20000
    availability_24h: float = 0.9
    recent_success_rate: float = 0.9
    rate_limit_hits_1h: int = 0
    json_parse_success_24h: float = 0.9
    timeout_score: float = 0.9
    malformed_json_rate_24h: float = 0.1


class FreeModel(BaseModel):
    id: str
    family: str
    context_length: int = 8192
    supports_json_mode: bool = False
    supports_tools: bool = False
    capabilities: ModelCapabilities
    telemetry: ModelTelemetry = Field(default_factory=ModelTelemetry)
    health_score: float = 0.75
    last_verified: str | None = None


class CouncilMember(BaseModel):
    label: str
    role: str
    model: FreeModel
    critique_template: str


class MemberOutput(BaseModel):
    label: str
    role: str
    model_id: str
    output_text: str
    confidence: float = 70.0
    status: str = "success"
    failure_reason: str | None = None
    substitute_for: str | None = None
    attempts: list[dict[str, Any]] = Field(default_factory=list)
    latency_ms: int = 0
    cost: float = 0.0
    critiques: list[dict[str, Any]] = Field(default_factory=list)
    revised_text: str | None = None


class ConsensusReport(BaseModel):
    consensus_items: list[dict[str, Any]]
    disagreements: list[dict[str, Any]]
    candidate_ranking: list[dict[str, Any]]
    overall_consensus_score: float


class QuorumResult(BaseModel):
    final_answer: str
    metadata: dict[str, Any]
    outputs: list[MemberOutput]
    consensus: ConsensusReport
