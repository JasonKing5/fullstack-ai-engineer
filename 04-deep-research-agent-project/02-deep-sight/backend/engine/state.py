# backend/engine/state.py
import operator
from typing import Annotated, List, TypedDict


class AgentState(TypedDict):
    """
    LangGraph 状态字典：图中所有节点都将读取和修改这个状态。
    """

    company: str  # 目标公司 (例如 Tesla)
    query: str  # 用户原始提问
    search_queries: List[str]  # Planner 拆解出的多个检索词

    # Annotated[List, operator.add] 意味着每次写入都会附加到列表中，而不是覆盖
    context: Annotated[List[str], operator.add]

    draft: str  # 生成的草稿
    feedback: str  # AI Reviewer 或者 人类 给出的修改意见
    revision_count: int  # 重写次数 (防死循环)
    approved: bool  # 人类是否审批通过
    final_report: str  # 最终生成的报告
