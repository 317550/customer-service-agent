"""
这段代码包含几个真实开发习惯：

路径参数有限制，拒绝明显不合法的订单号；
使用 response_model 保证返回格式；
订单不存在返回404；
数据库异常返回503；
不向客户端泄露 SQL、文件路径和堆栈；
使用依赖注入让测试数据库可以替换真实数据库。
"""
from pathlib import Path as FilePath
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, Request, status

from app.database import DatabaseOperationError, get_order_by_id
from app.schemas import ErrorResponse, HealthResponse, OrderResponse


router = APIRouter()


def get_database_path(request: Request) -> FilePath:
    """
    从 FastAPI 应用状态中取得数据库路径。

    把路径作为依赖提供，方便测试替换成临时数据库，
    避免测试污染真实数据。
    """
    return request.app.state.database_path


@router.get(
    "/health",
    response_model=HealthResponse,
    tags=["system"],
)
def health_check() -> HealthResponse:
    return HealthResponse(status="ok")


@router.get(
    "/orders/{order_id}",
    response_model=OrderResponse,
    tags=["orders"],
    responses={
        404: {"model": ErrorResponse},
        503: {"model": ErrorResponse},
    },
)
def read_order(
    order_id: Annotated[
        str,
        Path(
            min_length=1,
            max_length=64,
            pattern=r"^[A-Za-z0-9_-]+$",
        ),
    ],
    db_path: Annotated[FilePath, Depends(get_database_path)],
) -> OrderResponse:
    try:
        order = get_order_by_id(order_id, db_path)
    except DatabaseOperationError as exc:
        # 不把数据库路径、SQL等内部信息暴露给客户端。
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="订单服务暂时不可用",
        ) from exc

    if order is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"订单不存在：{order_id}",
        )

    return OrderResponse.model_validate(order)