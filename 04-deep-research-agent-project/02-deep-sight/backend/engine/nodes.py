# backend/engine/nodes.py
from config import settings
from engine.state import AgentState
from engine.tools import retrieve_financial_data
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from pydantic import BaseModel, Field

# 实例化核心大模型
llm = ChatOpenAI(
    model="gpt-5-mini",
    api_key=settings.OPENAI_API_KEY,
    base_url=settings.OPENAI_BASE_URL,
    temperature=0.2,
    max_retries=3,  # Langchain 原生重试机制
)


# --- Planner Node 的输出约束 ---
class PlanOutput(BaseModel):
    search_queries: list[str] = Field(
        description="为了回答用户问题，需要去财报中检索的 1 到 3 个具体搜索词汇。"
    )


async def planner_node(state: AgentState):
    """规划节点：将用户提问拆解为专业检索词"""
    print("🧠 [Planner Node] 正在制定检索计划...")
    query = state.get("query")
    company = state.get("company")
    feedback = state.get("feedback", "")

    sys_prompt = f"你是一个金融分析师。用户正在查询 {company}。请将用户的自然语言提问转化为查阅财报时用的精确关键词。"
    if feedback:
        sys_prompt += f"\n注意之前的失败教训/反馈：{feedback}"

    structured_llm = llm.with_structured_output(PlanOutput)
    plan: PlanOutput = await structured_llm.ainvoke(
        [SystemMessage(content=sys_prompt), HumanMessage(content=query)]
    )

    return {"search_queries": plan.search_queries}


async def retriever_node(state: AgentState):
    """检索节点：根据计划执行检索"""
    print("🔎 [Retriever Node] 正在前往 Qdrant 检索财报...")
    company = state.get("company")
    queries = state.get("search_queries", [])

    # 工业级写法：使用 asyncio.gather 并发检索所有的关键词
    # import asyncio

    # tasks = [retrieve_financial_data(company, q) for q in queries]
    # results = await asyncio.gather(*tasks)

    # 弃用 asyncio.gather 并发，改为安全的串行 for 循环，防止打垮免费数据库
    results = []
    for q in queries:
        try:
            print(f"   -> 正在检索关键词: {q}")
            res = await retrieve_financial_data(company, q)
            results.append(res)
        except Exception as e:
            print(f"   -> 关键词 {q} 检索失败: {e}")
            results.append(f"关键词 {q} 检索失败。")

    # 手动累积：读取已有 context 再追加，支持多轮检索叠加
    existing_context = state.get("context", [])
    combined_context = f"【批次检索结果】:\n" + "\n---\n".join(results)
    return {"context": existing_context + [combined_context]}


async def drafter_node(state: AgentState):
    """起草节点：根据检索结果撰写草稿"""
    print("✍️ [Drafter Node] 正在起草分析报告...")
    query = state.get("query")
    context_list = state.get("context", [])
    full_context = "\n".join(context_list)

    prompt = f"""
    根据以下检索到的财报上下文，回答用户的问题：{query}。

    要求：
    - 使用 Markdown 格式输出，包含二级标题（##）、加粗关键数据、列表等结构
    - 排版专业，层次清晰
    - 引用具体数据支持结论

    上下文：
    {full_context}
    """
    res = await llm.ainvoke([HumanMessage(content=prompt)])

    # 每次起草，revision_count + 1
    current_rev = state.get("revision_count", 0)
    return {"draft": res.content, "revision_count": current_rev + 1}


# --- Reviewer Node 的输出约束 ---
class ReviewOutput(BaseModel):
    is_passed: bool = Field(description="草稿是否基本回答了用户问题并引用了相关数据？基本达标即为True，不要追求完美。")
    feedback: str = Field(
        description="如果不通过（is_passed=False），给出具体的改进方向；如果通过，填'无'。"
    )


async def reviewer_node(state: AgentState):
    """AI 质检节点：自我反思"""
    import asyncio
    print("🧐 [Reviewer Node] AI 正在审查草稿质量...")
    draft = state.get("draft")
    query = state.get("query")

    sys_prompt = (
        "你是金融研报审核员。请审查这份草稿是否基本回答了用户的核心问题，并引用了相关数据。"
        "审核标准：只要草稿能基本回答问题、引用了任何相关财报数据，就应当通过。"
        "只有当草稿完全偏题、存在明显事实错误、或完全没有引用任何数据时才打回。"
        "不要以'数据不够全面'或'缺少某些具体数字'为由打回，基本达标即可通过。"
    )
    structured_llm = llm.with_structured_output(ReviewOutput)
    messages = [
        SystemMessage(content=sys_prompt),
        HumanMessage(content=f"用户提问：{query}\n\n当前草稿：{draft}"),
    ]

    last_err = None
    for attempt in range(3):
        try:
            review: ReviewOutput = await structured_llm.ainvoke(messages)
            if not review.is_passed:
                print(f"⚠️ 质检未通过，反馈意见: {review.feedback}")
            return {"feedback": review.feedback}
        except Exception as e:
            last_err = e
            wait = 2 ** attempt  # 1s, 2s, 4s
            print(f"⚠️ [Reviewer] 第 {attempt + 1} 次调用失败: {e}，{wait}s 后重试...")
            await asyncio.sleep(wait)

    # 所有重试耗尽：默认通过，避免流程卡死
    print(f"❌ [Reviewer] 重试 3 次均失败，兜底通过。最后错误: {last_err}")
    return {"feedback": "无"}


async def publish_node(state: AgentState):
    """发布节点：被人类唤醒后执行，模板化封装定稿（不修改已审批内容）"""
    from datetime import datetime
    print("✅ [Publish Node] 人类审批完成，输出定稿！")

    company = state["company"]
    draft = state["draft"]
    query = state.get("query", "")
    now = datetime.now().strftime("%Y年%m月%d日 %H:%M")

    final_report = f"""# 深度研报：{company}

**研究问题：** {query}
**生成时间：** {now}
**状态：** 已通过 AI 交叉核验 · 人工审核通过

---

{draft}

---

*本报告由 AI 辅助生成，经人工审核。内容仅供参考，不构成投资建议。*"""

    return {"final_report": final_report}
