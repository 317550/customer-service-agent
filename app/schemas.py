"""
这里没有直接返回任意字典，而是定义响应模型，因为真实接口需要稳定的数据契约。

例如 OrderResponse 可以保证：

id 必须是整数；
amount 不能小于0；
必要字段不能丢失；
/docs 能自动展示响应格式。
"""

from typing import Literal

from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    status: Literal["ok"]


class OrderResponse(BaseModel):
    id: int
    order_id: str
    customer_id: str
    product: str
    amount: float = Field(ge=0)
    status: str


class ErrorResponse(BaseModel):
    detail: str