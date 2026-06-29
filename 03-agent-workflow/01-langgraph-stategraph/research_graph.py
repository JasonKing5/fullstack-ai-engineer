import asyncio
import os
from typing import List, TypedDict

from dotenv import load_dotenv
from langchain_openai import ChatOpenAI
from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel, Field

# 第一步：安装依赖与环境变量配置
# pip install langgraph langchain-openai pydantic
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


# 第二步：定义全局状态 (State) 和 结构化输出模型
class AgentState(TypedDict):
    company: str
    research_outline: str
    raw_data: str
    draft: str
    review_feedback: str
    revision_count: int


class ReviewResult(BaseModel):
    is_pass: bool = Field(
        description="文章是否合格，无数据缺失或逻辑错误为 True，否则为 False"
    )
    feedback: str = Field(
        description="如果不合格，给出具体的修改建议；如果合格，返回 'Looks good'"
    )


# 第三步：编写节点函数 (Nodes) - 核心业务逻辑
async def planner_node(state: AgentState):
    print(">>> 节点执行中: [Planner] 正在制定大纲...")
    company = state["company"]

    prompt = f"你是资深金融分析师，请为公司【{company}】制定一份简短的研报大纲，只需3个要点。"
    response = await llm.ainvoke(prompt)

    # 初始化 revision_count 为 0
    return {"research_outline": response.content, "revision_count": 0}


async def researcher_node(state: AgentState):
    print(">>> 节点执行中: [Researcher] 正在检索资料...")
    outline = state.get("research_outline", "")
    feedback = state.get("review_feedback", "")

    # 模拟真实世界：如果带有 Reviewer 的打回意见，检索策略应该调整
    if feedback:
        print(f"    - 收到打回意见，补充检索: {feedback}")

    # 【选项 A：使用 Mock RAG 数据】代替真实的 LlamaIndex 查询
    mock_rag_data = f"""
    [Mock数据库召回内容]
    1. {state["company"]} 2026年第一季度财报显示营收增长稳健。
    2. 主要风险在于供应链的波动。
    3. 补充说明：针对反馈'{feedback}'的补充数据已获取。
    """

    # 模拟网络延迟
    await asyncio.sleep(1)
    return {"raw_data": mock_rag_data}


async def writer_node(state: AgentState):
    print(">>> 节点执行中: [Writer] 正在撰写初稿...")
    raw_data = state.get("raw_data", "")

    prompt = f"根据以下数据写一篇短研报：\n{raw_data}"
    response = await llm.ainvoke(prompt)

    return {"draft": response.content}


async def reviewer_node(state: AgentState):
    print(">>> 节点执行中: [Reviewer] 正在审查初稿质量...")
    draft = state.get("draft", "")
    revision_count = state.get("revision_count", 0)

    # 让大模型强制返回符合 ReviewResult 的 JSON 对象
    reviewer_llm = llm.with_structured_output(ReviewResult)

    prompt = (
        f"请审查这篇研报草稿：\n{draft}\n\n要求字数充实且逻辑清晰。严格判定是否合格。"
    )
    # 强制大模型打分判定
    result: ReviewResult = await reviewer_llm.ainvoke(prompt)

    print(f"    - 审查结果: {'通过' if result.is_pass else '不通过'}")
    print(f"    - 审查意见: {result.feedback}")

    # 更新打回次数，防止死循环
    return {"review_feedback": result.feedback, "revision_count": revision_count + 1}


# 第四步：编写条件路由逻辑 (Conditional Edge)
def route_after_review(state: AgentState) -> str:
    """条件边逻辑，不返回 state 字典，而是返回下一步节点的名称"""
    revision_count = state.get("revision_count", 0)
    feedback = state.get("review_feedback", "")

    # 1. 如果模型说通过了，结束
    if feedback == "Looks good" or "合格" in feedback or len(feedback) < 5:
        # 为了应对 structured_output 的容错，这里可以多重判断。或者直接用 is_pass (这里为了演示直接抓状态)
        # 注意：更好的做法是把 is_pass 也放进 AgentState 里，这里我们用 feedback 内容或者 revision_count 来做防御
        pass

    # 假设我们在 reviewer 里没把 is_pass 传出来，而是根据 feedback 内容判断：
    # 如果 review_feedback 表示不合格：
    if "不合格" in feedback or "补充" in feedback:
        # 2. 如果重试次数超过2次，强制结束，防止大模型陷入死循环破产
        if revision_count >= 2:
            print("!!! 警告: 重试次数达到上限，强行终止循环。")
            return END
        print(">>> 路由判定: 质量不达标，打回 Researcher 节点重做。")
        return "researcher"

    print(">>> 路由判定: 质量合格，流程结束。")
    return END


# 第五步：组装图 (Graph) 并执行
# 1. 初始化图构建器
builder = StateGraph(AgentState)

# 2. 注册所有节点
builder.add_node("planner", planner_node)
builder.add_node("researcher", researcher_node)
builder.add_node("writer", writer_node)
builder.add_node("reviewer", reviewer_node)

# 3. 定义普通边 (线性流程)
builder.add_edge(START, "planner")
builder.add_edge("planner", "researcher")
builder.add_edge("researcher", "writer")
builder.add_edge("writer", "reviewer")

# 4. 定义条件边 (循环与终结)
# 当 reviewer 节点执行完后，调用 route_after_review 判断下一步
builder.add_conditional_edges(
    "reviewer",
    route_after_review,
    # 映射路由函数返回的字符串到实际的节点名称
    {"researcher": "researcher", END: END},
)

# 5. 编译成可执行的图 (这就是你可以在前端暴露出的最终对象)
graph = builder.compile()


# 6. 运行主函数
async def main():
    print("====== 开始运行 LangGraph 研报流水线 ======")
    initial_state = {"company": "特斯拉 (Tesla)"}

    # 使用 astream 事件流，可以在控制台清晰看到每一步状态的变化
    async for output in graph.astream(initial_state):
        for node_name, state_value in output.items():
            print(f"--- 节点 [{node_name}] 处理完毕 ---")

    print("\n====== 最终输出草稿 ======")
    # 最终的图状态可以通过 ainvoke 获取
    final_state = await graph.ainvoke(initial_state)
    print(final_state["draft"])


if __name__ == "__main__":
    asyncio.run(main())
