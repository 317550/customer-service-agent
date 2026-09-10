"""
与昨天相比改了什么？

昨天只有：

HealthResponse
OrderResponse
ErrorResponse

今天保留它们，并新增：

SessionStatus
ProblemType
SessionCreate
SessionUpdate
SessionResponse
MessageCreate
MessageResponse

创建模型和更新模型分开，是因为二者语义不同：

SessionCreate：创建新资源；
SessionUpdate：只修改已有资源的一部分。
"""


from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field, field_validator


class HealthResponse(BaseModel):
    """健康检查接口的响应模型。"""

    status: Literal["ok"]


class OrderResponse(BaseModel):
    """订单查询接口的响应模型。"""

    id: int
    order_id: str
    customer_id: str
    product: str
    amount: float = Field(ge=0)
    status: str


class ErrorResponse(BaseModel):
    """HTTP异常的统一响应结构。"""

    detail: str


# ==================== 以下为今天新增 ====================


class SessionStatus(str, Enum):
    """
    会话状态枚举。

    继承 str 后，枚举值可以直接序列化成 JSON字符串，
    例如 SessionStatus.COLLECTING_INFORMATION 最终返回
    "collecting_information"。
    """

    COLLECTING_INFORMATION = "collecting_information"
    READY_FOR_PROCESSING = "ready_for_processing"
    WAITING_FOR_HUMAN = "waiting_for_human"
    COMPLETED = "completed"


class ProblemType(str, Enum):
    """
    当前支持的问题类型。

    使用枚举可以避免数据库中同时出现 refund、
    Refund、退款等无法统一统计的值。
    """

    REFUND = "refund"
    LOGISTICS = "logistics"
    QUALITY = "quality"
    OTHER = "other"


class SessionCreate(BaseModel):
    """
    创建客服会话的请求模型。

    用户可以先不提供姓名，因此 user_name 是可选字段。
    其他业务信息通过后续 PATCH 请求逐步补充。
    """

    user_name: str | None = Field(
        default=None,
        max_length=100,
    )


class SessionUpdate(BaseModel):
    """
    更新会话状态的请求模型。

    所有字段都是可选字段，因为一次请求可能只补充其中一个信息。
    例如第一轮补充订单号，第二轮再补充问题描述。
    """

    user_name: str | None = Field(
        default=None,
        max_length=100,
    )
    order_id: str | None = Field(
        default=None,
        max_length=64,
    )
    problem_type: ProblemType | None = None
    description: str | None = Field(
        default=None,
        max_length=2000,
    )


class SessionResponse(BaseModel):
    """查询、创建和更新会话时统一使用的响应模型。"""

    session_id: str
    user_name: str | None
    order_id: str | None
    problem_type: str | None
    description: str | None
    status: SessionStatus

    # missing_fields 并不直接存入数据库，
    # 它是根据当前会话状态实时计算出来的派生字段。
    missing_fields: list[str]

    created_at: str
    updated_at: str


class MessageCreate(BaseModel):
    """用户发送消息时的请求模型。"""

    content: str = Field(
        min_length=1,
        max_length=4000,
    )


class MessageResponse(BaseModel):
    """一条会话消息的响应模型。"""

    message_id: int
    session_id: str
    role: str
    content: str
    created_at: str


# ==================== Agent 工作流新增 ====================


class AgentAction(str, Enum):
    """一轮 Agent 执行后选择的业务动作。"""

    ASK_USER = "ask_user"
    QUERY_ORDER = "query_order"
    HANDOFF_TO_HUMAN = "handoff_to_human"


class AgentRunRequest(BaseModel):
    """执行一轮客服 Agent 时，客户端只需要发送用户原话。"""

    message: str = Field(max_length=4000)

    @field_validator("message")
    @classmethod
    def message_must_not_be_blank(cls, value: str) -> str:
        """Pydantic 的 min_length 会把空格算作字符，因此在这里再 strip。"""
        normalized = value.strip()
        if not normalized:
            raise ValueError("消息内容不能为空")
        return normalized


class ExtractedCustomerInfo(BaseModel):
    """
    从用户自然语言中提取出的结构化字段。

    以后接入 LLM 时，模型也必须输出这个结构，而不能让模型直接修改数据库。
    """

    user_name: str | None = None
    order_id: str | None = None
    problem_type: ProblemType | None = None
    description: str | None = None


class AgentRunResponse(BaseModel):
    """一次 Agent 执行的稳定响应契约。"""

    session_id: str
    reply: str
    action: AgentAction
    session_status: SessionStatus
    missing_fields: list[str]
    requires_human: bool
    order: OrderResponse | None = None
