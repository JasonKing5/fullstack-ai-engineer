import asyncio
from typing import TypedDict

from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.graph import END, START, StateGraph


# 最简状态：只保留验证持久化所需字段
class AgentState(TypedDict):
    company: str
    research_outline: str
    raw_data: str
    draft: str


# Mock 节点，无需 LLM，只写入固定数据
async def planner_node(state: AgentState):
    print(">>> [Planner] 制定大纲...")
    return {"research_outline": f"{state['company']} 研报大纲：1.财务 2.风险 3.展望"}


async def researcher_node(state: AgentState):
    print(">>> [Researcher] 检索资料...")
    await asyncio.sleep(0.5)
    return {"raw_data": f"{state['company']} 2026年Q1营收增长15%，毛利率28%"}


async def writer_node(state: AgentState):
    print(">>> [Writer] 撰写初稿...")
    return {"draft": f"研报初稿：{state.get('raw_data')}，前景乐观。"}


THREAD_ID = "tesla_report_001"
DB_FILE = "checkpoints.sqlite"


async def main():
    async with AsyncSqliteSaver.from_conn_string(DB_FILE) as saver:
        builder = StateGraph(AgentState)
        builder.add_node("planner", planner_node)
        builder.add_node("researcher", researcher_node)
        builder.add_node("writer", writer_node)
        builder.add_edge(START, "planner")
        builder.add_edge("planner", "researcher")
        builder.add_edge("researcher", "writer")
        builder.add_edge("writer", END)

        # interrupt_before=["writer"]：在 writer 执行前挂起，模拟"程序中途退出"
        graph = builder.compile(checkpointer=saver, interrupt_before=["writer"])
        thread_config = {"configurable": {"thread_id": THREAD_ID}}

        # ── 第一阶段：检查是否已有存档 ────────────────────────────────
        existing = await graph.aget_state(thread_config)
        if existing.values:
            print("\n✅ 发现已有存档！直接从 SQLite 读取历史进度（无需重新运行）：")
            print(f"   raw_data  = {existing.values.get('raw_data')}")
            print(f"   draft     = {existing.values.get('draft')}")
            print(f"   下一步节点 = {existing.next}")
            print("\n💡 结论：即使关机重启，只要 thread_id='tesla_report_001'，数据永远在。")
            return

        # ── 第二阶段：首次运行，执行到断点自动挂起 ─────────────────────
        print("\n====== 首次运行：Planner → Researcher → 挂起（writer 前断点）======")
        async for output in graph.astream({"company": "特斯拉 (Tesla)"}, thread_config):
            print("  流转节点:", list(output.keys()))

        # ── 第三阶段：读取挂起时的状态 ──────────────────────────────────
        state = await graph.aget_state(thread_config)
        print("\n📦 当前 SQLite 中保存的状态：")
        print(f"   raw_data  = {state.values.get('raw_data')}")
        print(f"   下一步节点 = {state.next}")
        print("\n🔒 现在关掉终端，明天再运行这个脚本……")
        print("   只要 thread_id 还是 'tesla_report_001'，上面的数据会被原封不动读出来。")


if __name__ == "__main__":
    asyncio.run(main())
