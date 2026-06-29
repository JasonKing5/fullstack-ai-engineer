import asyncio
import os
from typing import List, TypedDict

from dotenv import load_dotenv
from langchain_openai import ChatOpenAI

# 【新引入】异步 SQLite 检查点
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel, Field

load_dotenv()

openai_api_key = os.getenv("OPENAI_API_KEY")
openai_base_url = os.getenv("OPENAI_BASE_URL")
model_name = os.getenv("MODEL_NAME")
qdrant_url = os.getenv("QDRANT_URL")
qdrant_api_key = os.getenv("QDRANT_API_KEY")
cohere_api_key = os.getenv("COHERE_API_KEY")
tavily_api_key = os.getenv("TAVILY_API_KEY")

llm = ChatOpenAI(
    model=model_name,
    base_url=openai_base_url,
    api_key=openai_api_key,
    temperature=0.3,
    max_tokens=4000,
)


class AgentState(TypedDict):
    company: str
    research_outline: str
    raw_data: str
    draft: str
    review_feedback: str
    revision_count: int


class ReviewResult(BaseModel):
    is_pass: bool = Field(description="文章是否合格")
    feedback: str = Field(description="反馈意见")


# --- 节点定义 (与 Task 8 完全一致) ---
async def planner_node(state: AgentState):
    print(">>> [Planner] 正在制定大纲...")
    company = state["company"]
    response = await llm.ainvoke(
        f"为公司【{company}】制定一份极简研报大纲，只需3个要点。"
    )
    return {"research_outline": response.content, "revision_count": 0}


async def researcher_node(state: AgentState):
    print(">>> [Researcher] 正在检索资料...")
    # 这里依然使用 Mock 数据，一会我们要用时间旅行来“篡改”它
    mock_rag_data = f"{state['company']} 2026年Q1财报表现平平，没有亮点。"
    await asyncio.sleep(1)
    return {"raw_data": mock_rag_data}


async def writer_node(state: AgentState):
    print(">>> [Writer] 正在撰写初稿...")
    prompt = f"根据以下数据写一篇短研报：\n{state.get('raw_data')}"
    response = await llm.ainvoke(prompt)
    return {"draft": response.content}


async def reviewer_node(state: AgentState):
    print(">>> [Reviewer] 正在审查...")
    reviewer_llm = llm.with_structured_output(ReviewResult)
    result = await reviewer_llm.ainvoke(
        f"审查草稿并判定是否合格(无脑挑刺也可以)：\n{state.get('draft')}"
    )
    print(f"    - 审查结果: {result.is_pass}, 意见: {result.feedback}")
    return {
        "review_feedback": result.feedback,
        "revision_count": state.get("revision_count", 0) + 1,
    }


def route_after_review(state: AgentState) -> str:
    if (
        state.get("revision_count", 0) >= 2
        or "合格" in state.get("review_feedback", "")
        or "Looks good" in state.get("review_feedback", "")
    ):
        return END
    return "researcher"


# ==========================================
# 主流程：组装图、持久化与时间旅行演示
# ==========================================
async def main():
    # 【新引入】使用上下文管理器打开 SQLite 数据库
    async with AsyncSqliteSaver.from_conn_string("checkpoints.sqlite") as saver:
        builder = StateGraph(AgentState)
        builder.add_node("planner", planner_node)
        builder.add_node("researcher", researcher_node)
        builder.add_node("writer", writer_node)
        builder.add_node("reviewer", reviewer_node)

        builder.add_edge(START, "planner")
        builder.add_edge("planner", "researcher")
        builder.add_edge("researcher", "writer")
        builder.add_edge("writer", "reviewer")
        builder.add_conditional_edges(
            "reviewer", route_after_review, {"researcher": "researcher", END: END}
        )

        # 【新引入】编译图时，传入 checkpointer。
        # 同时设置 interrupt_before=["writer"]，意思是：在执行 Writer 之前，立刻挂起图！
        graph = builder.compile(checkpointer=saver, interrupt_before=["writer"])

        # 【新引入】定义 Thread ID，这是 Agent 记忆的唯一标识
        thread_config = {"configurable": {"thread_id": "tesla_report_001"}}

        print("\n====== 第一阶段：正常运行并触发断点 ======")
        initial_state = {"company": "特斯拉 (Tesla)"}

        # 图会运行 Planner -> Researcher，然后自动暂停（因为遇到了 interrupt_before）
        async for output in graph.astream(initial_state, thread_config):
            print("当前状态流转:", list(output.keys()))

        print("\n[系统挂起] 图在 writer 节点前暂停了！")

        # 【新引入】获取当前挂起时的状态
        current_state = await graph.aget_state(thread_config)
        print("\n👉 当前数据库里保存的 Researcher 检索数据是：")
        print(current_state.values.get("raw_data"))
        print(f"当前下一个准备执行的节点是: {current_state.next}")

        print("\n====== 第二阶段：时间旅行与人工篡改 (Human-in-the-loop) ======")
        print("老板觉得 Researcher 搜出来的数据太烂了，决定人工注入机密数据...")

        fake_secret_data = "【人类强行注入的机密数据】：特斯拉即将在2026下半年发布带意识的擎天柱机器人，股价预计暴涨 500%！"

        # 【新引入】篡改历史状态
        # as_node="researcher" 的意思是：假装这个数据是 researcher 刚刚产出的
        await graph.aupdate_state(
            thread_config, {"raw_data": fake_secret_data}, as_node="researcher"
        )
        print("✅ 历史数据已篡改！")

        print("\n====== 第三阶段：恢复运行并分叉未来 ======")
        # 【新引入】传入 None 代替 initial_state，告诉图顺着被篡改的记忆往下跑
        # Writer 节点会被唤醒，并读取到那条“机密数据”进行写作！
        async for output in graph.astream(None, thread_config):
            print("当前状态流转:", list(output.keys()))

        # 获取最终生成的草稿
        final_state = await graph.aget_state(thread_config)
        print("\n====== 最终生成的研报 (请观察大模型是否采用了你注入的机密数据) ======")
        print(final_state.values.get("draft"))


if __name__ == "__main__":
    asyncio.run(main())
