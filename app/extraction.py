"""用户信息提取模块。

当前版本使用确定性规则，便于离线运行和自动化测试。
未来接入 DeepSeek 等模型时，只替换提取器实现，Agent 编排无需重写。
"""

import re
from typing import Protocol

from app.schemas import ExtractedCustomerInfo, ProblemType


class InformationExtractor(Protocol):
    """信息提取器协议；规则实现和 LLM 实现都要遵守这个接口。"""

    def extract(self, message: str) -> ExtractedCustomerInfo:
        ...


class RuleBasedInformationExtractor:
    """用于 MVP 和测试环境的规则提取器。"""

    _name_pattern = re.compile(
        r"(?:我叫|我是|姓名(?:是|为|[:：]))\s*([\u4e00-\u9fff]{2,10})"
    )
    _order_pattern = re.compile(
        # 不再使用 \b，因为中文字符在 Python Unicode 正则中
        # 也可能被视为“单词字符”，会导致“订单ORD001”无法匹配。
        #
        # 这里改为检查订单号前后不能紧邻其他 ASCII 字母、
        # 数字、下划线或连字符，但允许紧邻中文和中文标点。
        r"(?<![A-Za-z0-9_-])(ORD[A-Za-z0-9_-]+)(?![A-Za-z0-9_-])",
        flags=re.IGNORECASE,
    )

    _problem_keywords = {
        ProblemType.REFUND: ("退款", "退货", "退钱"),
        ProblemType.LOGISTICS: ("物流", "快递", "发货", "到货", "没收到"),
        ProblemType.QUALITY: ("质量", "损坏", "坏了", "故障", "破损"),
    }

    def extract(self, message: str) -> ExtractedCustomerInfo:
        normalized = message.strip()

        name_match = self._name_pattern.search(normalized)
        order_match = self._order_pattern.search(normalized)

        problem_type: ProblemType | None = None
        for candidate, keywords in self._problem_keywords.items():
            if any(keyword in normalized for keyword in keywords):
                problem_type = candidate
                break

        # 用户明确表达“问题/投诉”但没有命中已知类别时，归入 other。
        if problem_type is None and any(
            marker in normalized
            for marker in ("问题", "投诉", "售后", "客服")
        ):
            problem_type = ProblemType.OTHER

        # 只有包含问题语义时才更新描述，避免“我叫张三”覆盖之前的问题描述。
        has_problem_description = problem_type is not None

        return ExtractedCustomerInfo(
            user_name=name_match.group(1) if name_match else None,
            order_id=(
                order_match.group(1).upper()
                if order_match
                else None
            ),
            problem_type=problem_type,
            description=normalized if has_problem_description else None,
        )


default_information_extractor = RuleBasedInformationExtractor()
