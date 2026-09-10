"""
与昨天相比主要变化

昨天路由只有：

GET /health
GET /orders/{order_id}

今天增加：

POST  /sessions
GET   /sessions/{session_id}
PATCH /sessions/{session_id}
POST  /sessions/{session_id}/messages
GET   /sessions/{session_id}/messages

注意：

create_session as create_session_record

这是导入别名。因为数据库函数和 API路由都可以叫 create_session，为了避免名称冲突，把数据库函数在当前文件中改名为：

create_session_record

原函数本身没有被改名。
"""
from pathlib import Path as FilePath
import secrets
from typing import Annotated, Any

from fastapi import (
    APIRouter,
    Depends,
    Header,
    HTTPException,
    Path,
    Request,
    status,
)

from app.database import (
    DatabaseOperationError,
    create_session as create_session_record,
    get_order_by_id,
    get_session_by_id,
    get_ticket_by_id,
    get_ticket_by_session_id,
    insert_message,
    list_messages_by_session,
    update_session as update_session_record,
)
from app.agent_service import (
    AgentSessionNotFoundError,
    run_agent,
)
from app.extraction import InformationExtractor
from app.schemas import (
    AgentRunRequest,
    AgentRunResponse,
    ErrorResponse,
    HealthResponse,
    MessageCreate,
    MessageResponse,
    OrderResponse,
    SessionCreate,
    SessionResponse,
    SessionUpdate,
    TicketResponse,
    TicketStatusUpdate,
)
from app.services import (
    build_session_response,
    determine_session_status,
    normalize_optional_text,
    normalize_session_updates,
)
from app.ticket_service import (
    InvalidTicketTransitionError,
    TicketNotFoundError,
    transition_ticket,
)


router = APIRouter()


def get_database_path(request: Request) -> FilePath:
    """
    从 FastAPI应用状态中获取数据库路径。

    测试时 create_app() 可以传入临时数据库，
    不会修改开发环境中的真实数据。
    """
    return request.app.state.database_path


def get_information_extractor(
    request: Request,
) -> InformationExtractor:
    """从应用状态获取当前环境配置的信息提取器。"""
    return request.app.state.information_extractor


def require_admin_token(
    request: Request,
    x_admin_token: Annotated[
        str | None,
        Header(alias="X-Admin-Token"),
    ] = None,
) -> None:
    """保护人工客服接口，避免普通用户直接批准自己的工单。"""
    configured_token = request.app.state.admin_api_key
    if not configured_token:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="人工工单管理接口尚未配置",
        )
    if x_admin_token is None or not secrets.compare_digest(
        x_admin_token,
        configured_token,
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="无权执行人工工单操作",
        )


def database_unavailable(
    exc: DatabaseOperationError,
) -> HTTPException:
    """
    将内部数据库错误转换成对外的 HTTP 503。

    客户端不需要看到数据库路径、SQL或异常堆栈。
    """
    return HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail="服务暂时不可用",
    )


def get_session_or_404(
    session_id: str,
    db_path: FilePath,
) -> dict[str, Any]:
    """
    查询会话，不存在时统一抛出404。

    多个路由都需要查询会话，因此抽取成公共函数，
    避免重复相同的异常处理。
    """
    try:
        session = get_session_by_id(
            session_id,
            db_path,
        )
    except DatabaseOperationError as exc:
        raise database_unavailable(exc) from exc

    if session is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"会话不存在：{session_id}",
        )

    return session


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
    db_path: Annotated[
        FilePath,
        Depends(get_database_path),
    ],
) -> OrderResponse:
    """【昨天已有】查询唯一订单号。"""
    try:
        order = get_order_by_id(
            order_id,
            db_path,
        )
    except DatabaseOperationError as exc:
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


# ==================== 以下为今天新增 ====================


@router.post(
    "/sessions",
    response_model=SessionResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["sessions"],
    responses={
        503: {"model": ErrorResponse},
    },
)
def create_session(
    payload: SessionCreate,
    db_path: Annotated[
        FilePath,
        Depends(get_database_path),
    ],
) -> SessionResponse:
    """创建一条新的售后客服会话。"""
    user_name = normalize_optional_text(
        payload.user_name
    )

    try:
        session = create_session_record(
            user_name=user_name,
            db_path=db_path,
        )
    except DatabaseOperationError as exc:
        raise database_unavailable(exc) from exc

    return build_session_response(session)


@router.get(
    "/sessions/{session_id}",
    response_model=SessionResponse,
    tags=["sessions"],
    responses={
        404: {"model": ErrorResponse},
        503: {"model": ErrorResponse},
    },
)
def read_session(
    session_id: Annotated[
        str,
        Path(min_length=1, max_length=64),
    ],
    db_path: Annotated[
        FilePath,
        Depends(get_database_path),
    ],
) -> SessionResponse:
    """查询一条已有会话及其当前状态。"""
    session = get_session_or_404(
        session_id,
        db_path,
    )
    return build_session_response(session)


@router.patch(
    "/sessions/{session_id}",
    response_model=SessionResponse,
    tags=["sessions"],
    responses={
        404: {"model": ErrorResponse},
        503: {"model": ErrorResponse},
    },
)
def patch_session(
    session_id: Annotated[
        str,
        Path(min_length=1, max_length=64),
    ],
    payload: SessionUpdate,
    db_path: Annotated[
        FilePath,
        Depends(get_database_path),
    ],
) -> SessionResponse:
    """
    对会话进行部分更新。

    exclude_unset=True 很重要：
    它只提取客户端本次真正发送的字段，
    不会用模型默认的 None 覆盖其他已有字段。
    """
    existing_session = get_session_or_404(
        session_id,
        db_path,
    )

    raw_updates = payload.model_dump(
        mode="json",
        exclude_unset=True,
    )
    updates = normalize_session_updates(raw_updates)

    # 将本次更新覆盖到旧状态上，计算更新后的业务状态。
    candidate_session = {
        **existing_session,
        **updates,
    }

    updates["status"] = determine_session_status(
        candidate_session
    )

    try:
        updated_session = update_session_record(
            session_id=session_id,
            updates=updates,
            db_path=db_path,
        )
    except DatabaseOperationError as exc:
        raise database_unavailable(exc) from exc

    # 理论上前面已经确认会话存在。
    # 这里仍处理 None，防止查询和更新之间记录被其他请求删除。
    if updated_session is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"会话不存在：{session_id}",
        )

    return build_session_response(updated_session)


@router.post(
    "/sessions/{session_id}/messages",
    response_model=MessageResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["messages"],
    responses={
        404: {"model": ErrorResponse},
        503: {"model": ErrorResponse},
    },
)
def create_message(
    session_id: Annotated[
        str,
        Path(min_length=1, max_length=64),
    ],
    payload: MessageCreate,
    db_path: Annotated[
        FilePath,
        Depends(get_database_path),
    ],
) -> MessageResponse:
    """保存一条用户消息。"""
    get_session_or_404(session_id, db_path)

    content = payload.content.strip()

    if not content:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="消息内容不能为空",
        )

    try:
        message = insert_message(
            session_id=session_id,
            role="user",
            content=content,
            db_path=db_path,
        )
    except DatabaseOperationError as exc:
        raise database_unavailable(exc) from exc

    return MessageResponse.model_validate(message)


@router.get(
    "/sessions/{session_id}/messages",
    response_model=list[MessageResponse],
    tags=["messages"],
    responses={
        404: {"model": ErrorResponse},
        503: {"model": ErrorResponse},
    },
)
def read_messages(
    session_id: Annotated[
        str,
        Path(min_length=1, max_length=64),
    ],
    db_path: Annotated[
        FilePath,
        Depends(get_database_path),
    ],
) -> list[MessageResponse]:
    """按照保存顺序返回某个会话的全部消息。"""
    get_session_or_404(session_id, db_path)

    try:
        messages = list_messages_by_session(
            session_id,
            db_path,
        )
    except DatabaseOperationError as exc:
        raise database_unavailable(exc) from exc

    return [
        MessageResponse.model_validate(message)
        for message in messages
    ]


# ==================== Agent 工作流新增 ====================


@router.post(
    "/sessions/{session_id}/runs",
    response_model=AgentRunResponse,
    tags=["agent"],
    responses={
        404: {"model": ErrorResponse},
        503: {"model": ErrorResponse},
    },
)
def run_customer_service_agent(
    session_id: Annotated[
        str,
        Path(min_length=1, max_length=64),
    ],
    payload: AgentRunRequest,
    db_path: Annotated[
        FilePath,
        Depends(get_database_path),
    ],
    extractor: Annotated[
        InformationExtractor,
        Depends(get_information_extractor),
    ],
) -> AgentRunResponse:
    """执行一轮带状态的售后客服 Agent。"""
    try:
        return run_agent(
            session_id=session_id,
            message=payload.message,
            db_path=db_path,
            extractor=extractor,
        )
    except AgentSessionNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"会话不存在：{session_id}",
        ) from exc
    except DatabaseOperationError as exc:
        raise database_unavailable(exc) from exc


# ==================== 人工工单闭环 ====================


@router.get(
    "/sessions/{session_id}/ticket",
    response_model=TicketResponse,
    tags=["tickets"],
    responses={404: {"model": ErrorResponse}, 503: {"model": ErrorResponse}},
)
def read_session_ticket(
    session_id: Annotated[str, Path(min_length=1, max_length=64)],
    db_path: Annotated[FilePath, Depends(get_database_path)],
) -> TicketResponse:
    """用户通过难以猜测的会话 ID 查询本会话工单进度。"""
    get_session_or_404(session_id, db_path)
    try:
        ticket = get_ticket_by_session_id(session_id, db_path)
    except DatabaseOperationError as exc:
        raise database_unavailable(exc) from exc
    if ticket is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"该会话尚未创建工单：{session_id}",
        )
    return TicketResponse.model_validate(ticket)


@router.get(
    "/tickets/{ticket_id}",
    response_model=TicketResponse,
    tags=["tickets"],
    dependencies=[Depends(require_admin_token)],
    responses={401: {"model": ErrorResponse}, 404: {"model": ErrorResponse}},
)
def read_ticket(
    ticket_id: Annotated[int, Path(ge=1)],
    db_path: Annotated[FilePath, Depends(get_database_path)],
) -> TicketResponse:
    """人工客服根据工单编号查看详情。"""
    try:
        ticket = get_ticket_by_id(ticket_id, db_path)
    except DatabaseOperationError as exc:
        raise database_unavailable(exc) from exc
    if ticket is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"工单不存在：{ticket_id}",
        )
    return TicketResponse.model_validate(ticket)


@router.patch(
    "/tickets/{ticket_id}/status",
    response_model=TicketResponse,
    tags=["tickets"],
    dependencies=[Depends(require_admin_token)],
    responses={
        401: {"model": ErrorResponse},
        404: {"model": ErrorResponse},
        409: {"model": ErrorResponse},
        503: {"model": ErrorResponse},
    },
)
def patch_ticket_status(
    ticket_id: Annotated[int, Path(ge=1)],
    payload: TicketStatusUpdate,
    db_path: Annotated[FilePath, Depends(get_database_path)],
) -> TicketResponse:
    """人工审核工单；领域服务会拒绝越级或终态修改。"""
    try:
        ticket = transition_ticket(ticket_id, payload.status, db_path)
    except TicketNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"工单不存在：{ticket_id}",
        ) from exc
    except InvalidTicketTransitionError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc
    except DatabaseOperationError as exc:
        raise database_unavailable(exc) from exc
    return TicketResponse.model_validate(ticket)
