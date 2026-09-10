"""
售后客服 Agent 的 Streamlit 演示前端。

这个前端只通过 HTTP 调用 FastAPI，不直接导入 database.py
或 agent_service.py，从而保持前后端职责分离。
"""

import os
from typing import Any

import httpx
import streamlit as st
from dotenv import load_dotenv


# 读取项目根目录中的 .env。
load_dotenv()

# 允许部署时通过环境变量替换后端地址。
API_BASE_URL = os.getenv(
    "API_BASE_URL",
    "http://127.0.0.1:8000",
).rstrip("/")

REQUEST_TIMEOUT_SECONDS = 30.0


def request_api(
    method: str,
    path: str,
    **kwargs: Any,
) -> Any:
    """
    统一调用 FastAPI。

    将网络故障和 HTTP 错误转换成用户能够理解的异常，
    避免把复杂的 httpx 异常处理散落在页面各处。
    """
    url = f"{API_BASE_URL}{path}"

    try:
        response = httpx.request(
            method=method,
            url=url,
            timeout=REQUEST_TIMEOUT_SECONDS,
            **kwargs,
        )
        response.raise_for_status()

    except httpx.ConnectError as exc:
        raise RuntimeError(
            "无法连接后端，请确认 FastAPI 已经启动。"
        ) from exc

    except httpx.TimeoutException as exc:
        raise RuntimeError(
            "后端响应超时，请稍后重试。"
        ) from exc

    except httpx.HTTPStatusError as exc:
        try:
            detail = exc.response.json().get(
                "detail",
                "请求失败",
            )
        except ValueError:
            detail = "后端返回了无法解析的错误"

        raise RuntimeError(
            f"请求失败（{exc.response.status_code}）：{detail}"
        ) from exc

    try:
        return response.json()
    except ValueError as exc:
        raise RuntimeError(
            "后端返回的内容不是合法 JSON。"
        ) from exc


def initialize_page_state() -> None:
    """
    初始化 Streamlit 页面状态。

    Streamlit 每次交互都会重新执行脚本，
    因此需要使用 session_state 保存会话 ID 和聊天记录。
    """
    defaults = {
        "session_id": None,
        "messages": [],
        "session_status": None,
        "last_action": None,
        "requires_human": False,
        "last_error": None,
    }

    for key, default_value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = default_value


def reset_page_state() -> None:
    """清除当前浏览器页面保存的客服会话状态。"""
    st.session_state.session_id = None
    st.session_state.messages = []
    st.session_state.session_status = None
    st.session_state.last_action = None
    st.session_state.requires_human = False
    st.session_state.last_error = None


def create_new_session(user_name: str) -> None:
    """请求后端创建新会话，并在页面中保存 session_id。"""
    normalized_name = user_name.strip()

    session = request_api(
        "POST",
        "/sessions",
        json={
            "user_name": normalized_name or None,
        },
    )

    reset_page_state()

    st.session_state.session_id = session["session_id"]
    st.session_state.session_status = session["status"]


def load_existing_session(session_id: str) -> None:
    """
    从后端加载已有会话和历史消息。

    这项功能用于验证：即使关闭前端或重启服务，
    会话状态依然能够从 SQLite 恢复。
    """
    normalized_session_id = session_id.strip()

    if not normalized_session_id:
        raise RuntimeError("请输入会话 ID。")

    session = request_api(
        "GET",
        f"/sessions/{normalized_session_id}",
    )

    messages = request_api(
        "GET",
        f"/sessions/{normalized_session_id}/messages",
    )

    st.session_state.session_id = session["session_id"]
    st.session_state.session_status = session["status"]
    st.session_state.messages = [
        {
            "role": message["role"],
            "content": message["content"],
        }
        for message in messages
    ]
    st.session_state.last_action = None
    st.session_state.requires_human = (
        session["status"] == "waiting_for_human"
    )
    st.session_state.last_error = None


def run_agent_turn(message: str) -> None:
    """把一条用户消息发送给带状态 Agent。"""
    session_id = st.session_state.session_id

    if session_id is None:
        raise RuntimeError("请先创建或加载一个会话。")

    # 先在页面状态中保存用户消息。
    st.session_state.messages.append(
        {
            "role": "user",
            "content": message,
        }
    )

    result = request_api(
        "POST",
        f"/sessions/{session_id}/runs",
        json={
            "message": message,
        },
    )

    # 后端已经把这条回复持久化到 SQLite；
    # 页面中再保存一份是为了立即渲染聊天界面。
    st.session_state.messages.append(
        {
            "role": "assistant",
            "content": result["reply"],
        }
    )

    st.session_state.session_status = result[
        "session_status"
    ]
    st.session_state.last_action = result["action"]
    st.session_state.requires_human = result[
        "requires_human"
    ]
    st.session_state.last_error = None


# -------------------- 页面开始 --------------------

st.set_page_config(
    page_title="售后客服 Agent",
    page_icon="🤖",
    layout="centered",
)

initialize_page_state()

st.title("带状态的售后客服 Agent")
st.caption(
    "支持多轮信息收集、订单查询、状态持久化和高风险转人工。"
)


# -------------------- 侧边栏 --------------------

with st.sidebar:
    st.header("会话管理")

    user_name = st.text_input(
        "用户姓名（可以暂不填写）",
        placeholder="例如：张三",
    )

    if st.button(
        "创建新会话",
        use_container_width=True,
        type="primary",
    ):
        try:
            create_new_session(user_name)
            st.rerun()
        except RuntimeError as exc:
            st.error(str(exc))

    st.divider()

    existing_session_id = st.text_input(
        "加载已有会话",
        placeholder="输入 session_id",
    )

    if st.button(
        "加载会话",
        use_container_width=True,
    ):
        try:
            load_existing_session(existing_session_id)
            st.rerun()
        except RuntimeError as exc:
            st.error(str(exc))

    if st.button(
        "清除当前页面会话",
        use_container_width=True,
    ):
        reset_page_state()
        st.rerun()

    st.divider()

    if st.session_state.session_id:
        st.success("会话已连接")
        st.code(st.session_state.session_id)

        st.write(
            "当前状态：",
            st.session_state.session_status,
        )

        if st.session_state.last_action:
            st.write(
                "最近动作：",
                st.session_state.last_action,
            )

        if st.session_state.requires_human:
            st.warning("该会话正在等待人工客服处理。")
    else:
        st.info("请先创建或加载一个会话。")


# -------------------- 主聊天区域 --------------------

if st.session_state.last_error:
    st.error(st.session_state.last_error)

for message in st.session_state.messages:
    role = message["role"]

    # SQLite 中的角色目前只有 user 和 assistant。
    display_role = (
        role
        if role in {"user", "assistant"}
        else "assistant"
    )

    with st.chat_message(display_role):
        st.markdown(message["content"])

prompt = st.chat_input(
    "请输入您的售后问题",
    max_chars=4000,
    disabled=st.session_state.session_id is None,
)

if prompt:
    try:
        with st.spinner("客服 Agent 正在处理..."):
            run_agent_turn(prompt)

    except RuntimeError as exc:
        # 用户消息已经在页面中显示，因此将错误保存在页面状态，
        # 让用户知道本轮没有正常完成。
        st.session_state.last_error = str(exc)

    st.rerun()