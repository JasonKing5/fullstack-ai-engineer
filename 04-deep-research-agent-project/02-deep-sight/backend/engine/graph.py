# backend/engine/graph.py
from engine.nodes import (
    drafter_node,
    planner_node,
    publish_node,
    retriever_node,
    reviewer_node,
)
from engine.state import AgentState
from langgraph.graph import END, START, StateGraph


def route_review(state: AgentState):
    """条件路由：决定是重新搜索、重写、还是前往审批"""
    # 1. 检查防死循环熔断
    if state.get("revision_count", 0) >= 3:
        print("🚨 重写超过 3 次熔断，强制进入审批环节。")
        return "publish_node"

    # 2. 如果 AI 提出了修改意见 (不为空且不是"无")，代表未通过
    feedback = state.get("feedback", "")
    if feedback and feedback != "无":
        # 认为需要补充数据，打回给 Planner 重新规划检索词
        return "planner_node"

    # 3. 如果完美通过，前往发布（但在到达之前会被打断）
    return "publish_node"


def build_graph():
    builder = StateGraph(AgentState)

    # 注册所有节点
    builder.add_node("planner_node", planner_node)
    builder.add_node("retriever_node", retriever_node)
    builder.add_node("drafter_node", drafter_node)
    builder.add_node("reviewer_node", reviewer_node)
    builder.add_node("publish_node", publish_node)

    # 编排执行主流程
    builder.add_edge(START, "planner_node")
    builder.add_edge("planner_node", "retriever_node")
    builder.add_edge("retriever_node", "drafter_node")
    builder.add_edge("drafter_node", "reviewer_node")

    # 根据 Reviewer 的反思结果，动态路由
    builder.add_conditional_edges("reviewer_node", route_review)

    builder.add_edge("publish_node", END)

    return builder
