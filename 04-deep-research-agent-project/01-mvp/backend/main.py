# backend/main.py
import asyncio
import json
import operator
import os
import uuid
from typing import Annotated, Optional, TypedDict

from dotenv import load_dotenv
from fastapi import BackgroundTasks, FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from langchain_core.messages import HumanMessage, SystemMessage

# --- 新增依赖 ---
from langchain_openai import ChatOpenAI
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel

load_dotenv()

openai_api_key = os.getenv("OPENAI_API_KEY")
openai_base_url = os.getenv("OPENAI_BASE_URL")
model_name = os.getenv("MODEL_NAME")
qdrant_url = os.getenv("QDRANT_URL")
qdrant_api_key = os.getenv("QDRANT_API_KEY")
cohere_api_key = os.getenv("COHERE_API_KEY")
tavily_api_key = os.getenv("TAVILY_API_KEY")

# --- 实例化防弹级 LLM ---
llm = ChatOpenAI(
    model=model_name,
    base_url=openai_base_url,
    api_key=openai_api_key,
    temperature=0.3,
    max_tokens=4000,
    streaming=True,
).with_retry(
    stop_after_attempt=3,
    wait_exponential_jitter=True,
)

app = FastAPI(title="Deep Research Agent API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# --- 文件上传接口（保留原逻辑） ---
async def parse_document_background(file_name: str, file_size: int):
    print(f"[后台任务开始] 正在调用 LlamaParse 解析 {file_name}...")
    await asyncio.sleep(5)
    print(f"[后台任务完成] {file_name} 解析完毕，已存入 Qdrant 向量库。")


@app.post("/api/upload")
async def upload_document(
    background_tasks: BackgroundTasks, file: UploadFile = File(...)
):
    if not file.filename.endswith(".pdf"):
        raise HTTPException(status_code=400, detail="只接受 PDF 文件")
    file_content = await file.read()
    background_tasks.add_task(parse_document_background, file.filename, len(file_content))
    return {"status": "success", "message": f"文件 {file.filename} 已接收，正在后台解析中..."}


# ============================================================
# LangGraph 状态机
# ============================================================

class AgentState(TypedDict):
    messages: Annotated[list, operator.add]
    approved: Optional[bool]   # None=待审批, True=通过, False=打回
    feedback: str              # 用户补充意见（同意或拒绝时都可填写）


async def research_node(state: AgentState):
    """生成（或依据反馈修改）研报草稿。"""
    feedback = state.get("feedback", "")
    msgs = state["messages"]

    sys_msg = SystemMessage(
        content="你是一个顶级的 B2B 金融分析师。请根据用户的需求，撰写一份简短、专业的研报草稿。如有修改反馈，请据此优化内容。"
    )

    if feedback and len(msgs) >= 2:
        # 重新生成：附带原始问题、上一版草稿和用户反馈
        original = msgs[0]        # 第一条：User: ...
        prev_draft = msgs[-1]     # 最后一条：上一次研报输出
        prompt = (
            f"{original}\n\n"
            f"【上一版草稿】:\n{prev_draft}\n\n"
            f"【修改反馈】: {feedback}\n\n"
            "请基于以上反馈修改草稿，保持专业风格。"
        )
    else:
        # 首次生成
        prompt = msgs[-1]

    response = await llm.ainvoke([sys_msg, HumanMessage(content=prompt)])

    # 重置审批状态与反馈，为下一轮人工审核做准备
    return {"messages": [response.content], "approved": None, "feedback": ""}


async def human_review_node(state: AgentState):
    """占位节点，仅用于承载 interrupt_before 断点。"""
    return {}


def route_after_review(state: AgentState) -> str:
    """审批通过 → publish；拒绝/未决 → 重新 research。"""
    if state.get("approved") is True:
        return "publish"
    return "research"


async def publish_node(state: AgentState):
    """基于审批通过的草稿，调用 LLM 生成正式最终报告。"""
    msgs = state["messages"]
    feedback = state.get("feedback", "")

    # 取最新一条研报草稿（messages 末尾即为上一轮 research 输出）
    latest_draft = msgs[-1]

    sys_msg = SystemMessage(
        content="你是一个顶级的 B2B 金融分析师。请将以下研报草稿整理为正式的最终报告，语言专业，结构清晰，分章节排版。"
    )

    if feedback:
        prompt = (
            f"研报草稿:\n{latest_draft}\n\n"
            f"审批人补充要求：{feedback}\n\n"
            "请将上述草稿结合补充要求，生成完整的最终正式报告。"
        )
    else:
        prompt = f"研报草稿:\n{latest_draft}\n\n请将以上内容整理为完整的最终正式报告。"

    response = await llm.ainvoke([sys_msg, HumanMessage(content=prompt)])
    return {"messages": [response.content]}


# --- 构建图 ---
builder = StateGraph(AgentState)
builder.add_node("research", research_node)
builder.add_node("human_review", human_review_node)
builder.add_node("publish", publish_node)

builder.add_edge(START, "research")
builder.add_edge("research", "human_review")
builder.add_conditional_edges(
    "human_review",
    route_after_review,
    {"publish": "publish", "research": "research"},
)
builder.add_edge("publish", END)

memory_checkpointer = MemorySaver()

# interrupt_before=["human_review"]：research 完成后暂停，等待人工审批
graph = builder.compile(checkpointer=memory_checkpointer, interrupt_before=["human_review"])


# ============================================================
# 请求体定义
# ============================================================

class ChatRequest(BaseModel):
    thread_id: str
    messages: Optional[list] = None  # AI SDK v4 格式
    message: Optional[str] = None    # 旧版兼容

    def get_latest_message(self) -> str:
        if self.message:
            return self.message
        if self.messages:
            for msg in reversed(self.messages):
                if isinstance(msg, dict) and msg.get("role") == "user":
                    for part in msg.get("parts", []):
                        if isinstance(part, dict) and part.get("type") == "text":
                            return part.get("text", "")
        return ""


class ApproveRequest(BaseModel):
    thread_id: str
    approved: bool
    feedback: Optional[str] = ""    # 用户补充意见（同意时的备注 or 拒绝时的修改要求）


# ============================================================
# SSE 流适配器
# ============================================================

async def vercel_stream_adapter(graph_instance, config, inputs=None):
    """将 LangGraph astream_events 转换为 AI SDK v4 UIMessageChunk SSE 格式。"""
    msg_id = str(uuid.uuid4())
    text_started = False

    yield f"data: {json.dumps({'type': 'start', 'messageId': msg_id})}\n\n"
    yield f"data: {json.dumps({'type': 'start-step'})}\n\n"

    async for event in graph_instance.astream_events(inputs, config, version="v2"):
        kind = event["event"]

        # 文本流 token
        if kind == "on_chat_model_stream":
            chunk = event["data"]["chunk"]
            if chunk.content:
                if not text_started:
                    yield f"data: {json.dumps({'type': 'text-start', 'id': 'text-1'})}\n\n"
                    text_started = True
                yield f"data: {json.dumps({'type': 'text-delta', 'id': 'text-1', 'delta': chunk.content})}\n\n"

        # research 节点完成 → 下发 Generative UI 工具卡片
        elif kind == "on_chain_end" and event["name"] == "research":
            # 每次 research 完成使用新 UUID，确保多轮迭代时 React key 不冲突
            chart_id = str(uuid.uuid4())
            approve_id = str(uuid.uuid4())

            yield f"data: {json.dumps({'type': 'tool-input-available', 'toolCallId': chart_id, 'toolName': 'render_financial_chart', 'input': {'company': 'Tesla', 'data': [{'year': '2023', 'revenue': 82.4}, {'year': '2024', 'revenue': 96.7}, {'year': '2025', 'revenue': 115.3}]}, 'dynamic': True})}\n\n"
            yield f"data: {json.dumps({'type': 'tool-input-available', 'toolCallId': approve_id, 'toolName': 'request_human_approval', 'input': {'summary': '已完成核心数据清洗与图表绘制，准备生成最终排版报告，请审批。'}, 'dynamic': True})}\n\n"

        # publish 节点完成 → 下发最终文本
        elif kind == "on_chain_end" and event["name"] == "publish":
            final_msg = event["data"]["output"]["messages"][0]
            if not text_started:
                yield f"data: {json.dumps({'type': 'text-start', 'id': 'text-1'})}\n\n"
                text_started = True
            yield f"data: {json.dumps({'type': 'text-delta', 'id': 'text-1', 'delta': final_msg})}\n\n"

    if text_started:
        yield f"data: {json.dumps({'type': 'text-end', 'id': 'text-1'})}\n\n"
    yield f"data: {json.dumps({'type': 'finish-step'})}\n\n"
    yield f"data: {json.dumps({'type': 'finish'})}\n\n"
    yield "data: [DONE]\n\n"


# ============================================================
# API 路由
# ============================================================

@app.post("/api/research/chat")
async def chat_stream(req: ChatRequest):
    config = {"configurable": {"thread_id": req.thread_id}}
    latest_message = req.get_latest_message()

    current_state = graph.get_state(config)
    if current_state.next:
        # 图暂停在断点，追加消息后恢复
        graph.update_state(config, {"messages": [f"User: {latest_message}"]})
        inputs = None
    else:
        # 新线程或已完成的图，全新启动
        inputs = {"messages": [f"User: {latest_message}"]}

    return StreamingResponse(
        vercel_stream_adapter(graph, config, inputs=inputs),
        media_type="text/event-stream",
    )


@app.post("/api/research/approve")
async def approve_step(req: ApproveRequest):
    config = {"configurable": {"thread_id": req.thread_id}}

    current_state = graph.get_state(config)
    if not current_state.next:
        raise HTTPException(status_code=400, detail="当前没有等待审批的任务")

    # 将审批决策和用户补充意见写入状态，然后恢复图的执行
    graph.update_state(config, {
        "approved": req.approved,
        "feedback": req.feedback or "",
    })

    return StreamingResponse(
        vercel_stream_adapter(graph, config, inputs=None),
        media_type="text/event-stream",
    )
