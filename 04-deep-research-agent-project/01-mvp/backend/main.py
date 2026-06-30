# backend/main.py
import asyncio
import json
import operator
import os
from typing import Annotated, TypedDict

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
# 1-B 策略：使用 LangChain 原生的 .with_retry() 极速实现防抖和重试
llm = ChatOpenAI(
    model=model_name,
    base_url=openai_base_url,
    api_key=openai_api_key,
    temperature=0.3,
    max_tokens=4000,
    streaming=True,  # 开启流式输出
).with_retry(
    stop_after_attempt=3,  # 失败自动重试 3 次
    wait_exponential_jitter=True,  # 使用指数退避算法，防止把 API 冲垮
)

# 编写后端 API 契约与跨域配置 (CORS)
app = FastAPI(title="Deep Research Agent API")

# 配置 CORS，允许 Next.js 前端访问
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 前端地址
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# 后续所有的 API 路由将写在下面...
# 实现文件解析接口 (BackgroundTasks)
# --- 模拟耗时的后台解析任务 ---
async def parse_document_background(file_name: str, file_size: int):
    print(f"[后台任务开始] 正在调用 LlamaParse 解析 {file_name}...")
    await asyncio.sleep(
        5
    )  # 模拟解析耗时 (注意用 asyncio.sleep，不能用 time.sleep 阻塞主线程)
    print(f"[后台任务完成] {file_name} 解析完毕，已存入 Qdrant 向量库。")


# --- 接口 1：文件上传 ---
@app.post("/api/upload")
async def upload_document(
    background_tasks: BackgroundTasks, file: UploadFile = File(...)
):
    # 1. 验证文件
    if not file.filename.endswith(".pdf"):
        raise HTTPException(status_code=400, detail="只接受 PDF 文件")

    # 2. 读取一点元数据
    file_content = await file.read()

    # 3. 把真正的重活儿丢给后台任务，不阻塞当前 HTTP 响应
    background_tasks.add_task(
        parse_document_background, file.filename, len(file_content)
    )

    # 4. 立刻给前端返回响应
    return {
        "status": "success",
        "message": f"文件 {file.filename} 已接收，正在后台解析中...",
    }


# 构建简易 LangGraph 状态机与流式对话接口
import operator
from typing import Annotated, TypedDict

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph


# 1. 定义状态
class AgentState(TypedDict):
    messages: Annotated[list, operator.add]
    approved: bool  # 记录人类是否审批通过


# 2. 编写节点函数
async def research_node(state: AgentState):
    # 从状态中获取用户最近的一条消息
    user_msg = state["messages"][-1]

    # 构造系统提示词
    sys_msg = SystemMessage(
        content="你是一个顶级的 B2B 金融分析师。请根据用户的需求，立刻撰写一份简短、专业的研报草稿。"
    )

    # 调用 LLM。注意：这里我们不需要写流式循环。
    # 因为在 LangGraph 中，只要你用 await llm.ainvoke，底层产生的流式 token 会自动冒泡给 astream_events！
    response = await llm.ainvoke([sys_msg, HumanMessage(content=user_msg)])

    # 将模型输出的文本存入状态机
    return {"messages": [response.content]}


async def publish_node(state: AgentState):
    if state.get("approved"):
        return {"messages": ["人类已审批通过，最终深度研报生成完毕！"]}
    else:
        return {"messages": ["人类拒绝了该草稿，任务终止。"]}


# 3. 构建图
builder = StateGraph(AgentState)
builder.add_node("research", research_node)
builder.add_node("publish", publish_node)

builder.add_edge(START, "research")
builder.add_edge("research", "publish")

# 重点：配置全局内存持久化！这保证了跨 HTTP 请求的状态不会丢
memory_checkpointer = MemorySaver()

# 重点：在 publish 节点前打断点，等待人类审批
graph = builder.compile(checkpointer=memory_checkpointer, interrupt_before=["publish"])


# --- 定义前端传来的请求体 ---
class ChatRequest(BaseModel):
    thread_id: str
    message: str


# --- 极简流式适配器 (Vercel AI SDK Protocol Adapter) ---
async def vercel_stream_adapter(graph_instance, config, inputs=None):
    """
    这个适配器会自动过滤 LangGraph 中海量的底层事件，
    只把 LLM 生成的文字转化为前端 Vercel SDK 认识的 `0:"..."\n` 格式。
    """
    async for event in graph_instance.astream_events(inputs, config, version="v2"):
        kind = event["event"]

        # 仅仅捕捉大模型流式输出的文本 token
        if kind == "on_chat_model_stream":
            chunk = event["data"]["chunk"]
            if chunk.content:
                # 严格遵守 Vercel AI SDK 协议： 0:"这里是文本内容"\n
                yield f"0:{json.dumps(chunk.content)}\n"

        # 当到达审批环节时，给前端抛出一个提示文本
        elif kind == "on_chain_end" and event["name"] == "publish":
            final_msg = event["data"]["output"]["messages"][0]
            yield f"0:{json.dumps(final_msg)}\n"


# --- 接口 2：流式对话核心逻辑 ---
@app.post("/api/research/chat")
async def chat_stream(req: ChatRequest):
    config = {"configurable": {"thread_id": req.thread_id}}

    # 更新用户的新消息到状态里
    graph.update_state(config, {"messages": [f"User: {req.message}"]})

    # async def event_generator():
    #     # astream_events 是极其强大的 API，它会把图流转的每一步广播出来
    #     async for event in graph.astream_events(None, config, version="v2"):
    #         kind = event["event"]
    #         if kind == "on_chat_model_stream":  # （未来替换为真实 LLM 时的 token 流）
    #             pass
    #         elif kind == "on_chain_end" and event["name"] == "research":
    #             # 模拟大模型输出。适配 Vercel AI SDK 的文本格式： 0:"文本内容"\n
    #             yield f'0:"{json.dumps("分析完毕，请审核。")}"\n'

    # return StreamingResponse(event_generator(), media_type="text/event-stream")

    # 直接返回接入了适配器的流
    return StreamingResponse(
        vercel_stream_adapter(graph, config, inputs=None),
        media_type="text/event-stream",
    )


# 实现人类审批接口 (打通断点续传)
# --- 接口 3：人类审批 ---
class ApproveRequest(BaseModel):
    thread_id: str
    approved: bool


@app.post("/api/research/approve")
async def approve_step(req: ApproveRequest):
    config = {"configurable": {"thread_id": req.thread_id}}

    # 1. 检查图当前是否真的在挂起状态
    current_state = graph.get_state(config)
    if not current_state.next:
        raise HTTPException(status_code=400, detail="当前没有等待审批的任务")

    # 2. 将人类的决策（True/False）更新到状态机中
    # 注意用 as_node="research" 伪装成是从上一个节点传来的状态
    graph.update_state(config, {"approved": req.approved}, as_node="research")

    # 3. 唤醒图，让它继续往下走
    # async def resume_generator():
    #     async for event in graph.astream_events(None, config, version="v2"):
    #         # 捕获 publish 节点输出的消息
    #         if event["event"] == "on_chain_end" and event["name"] == "publish":
    #             final_msg = event["data"]["output"]["messages"][0]
    #             yield f'0:"{json.dumps(final_msg)}"\n'

    # return StreamingResponse(resume_generator(), media_type="text/event-stream")

    # 唤醒图继续往下走，同样套上适配器！
    return StreamingResponse(
        vercel_stream_adapter(graph, config, inputs=None),
        media_type="text/event-stream",
    )
