"""
create_app() 是应用工厂。相比直接把所有内容写成全局代码，它让你能够：

测试时创建独立应用；
为每个测试指定临时数据库；
未来根据开发、测试、生产环境加载不同配置。
"""
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI

from app.config import (
    DATABASE_PATH,
    DEEPSEEK_API_KEY,
    DEEPSEEK_BASE_URL,
    DEEPSEEK_MODEL,
    DEEPSEEK_TIMEOUT_SECONDS,
    INFORMATION_EXTRACTOR_MODE,
)
from app.database import init_db
from app.extraction import (
    InformationExtractor,
    build_information_extractor,
)
from app.routes import router


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)


def create_app(
    database_path: Path | None = None,
    information_extractor: InformationExtractor | None = None,
) -> FastAPI:
    """
    应用工厂。

    正常运行使用配置中的数据库；
    自动化测试可以传入临时数据库。
    """
    runtime_database_path = database_path or DATABASE_PATH
    runtime_information_extractor = (
        information_extractor
        or build_information_extractor(
            mode=INFORMATION_EXTRACTOR_MODE,
            api_key=DEEPSEEK_API_KEY,
            base_url=DEEPSEEK_BASE_URL,
            model=DEEPSEEK_MODEL,
            timeout_seconds=DEEPSEEK_TIMEOUT_SECONDS,
        )
    )

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        # 服务启动时初始化数据库结构。
        init_db(runtime_database_path)
        yield

    application = FastAPI(
        title="Customer Service Agent API",
        version="0.1.0",
        lifespan=lifespan,
    )

    application.state.database_path = runtime_database_path
    # 将提取器放入应用状态，路由通过依赖注入获取。
    # 测试可以注入假实现，因此不会调用真实付费 API。
    application.state.information_extractor = runtime_information_extractor
    application.include_router(router)

    return application


app = create_app()
