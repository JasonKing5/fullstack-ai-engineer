import asyncio
import os
from contextlib import asynccontextmanager
from typing import TypedDict

import aiosqlite
from dotenv import load_dotenv
from fastapi import BackgroundTasks, FastAPI, Request
from fastapi.responses import HTMLResponse
from langchain_openai import ChatOpenAI
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel

# 环境变量配置
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


# ==========================================
# 1. 定义 Agent 状态和图逻辑
# ==========================================
class AgentState(TypedDict):
    company: str
    raw_data: str
    draft: str
    human_feedback: str  # 人类给的修改意见
    is_approved: bool  # 人类是否批准通过


async def researcher_node(state: AgentState):
    print(">>> [Researcher] 正在检索资料...")
    await asyncio.sleep(3)  # 模拟真实耗时，方便前端看到“Running”状态

    feedback = state.get("human_feedback")
    if feedback:
        print(f">>> [Researcher] 收到打回意见，正在重新检索：{feedback}")
        data = f"关于 {state['company']} 的补充调研数据，已解决'{feedback}'的问题。"
    else:
        data = f"关于 {state['company']} 的第一版基础调研数据。"
    return {"raw_data": data}


async def writer_node(state: AgentState):
    print(">>> [Writer] 正在撰写初稿...")
    prompt = f"根据以下数据写一份50字的极简研报：\n{state.get('raw_data')}"
    response = await llm.ainvoke(prompt)
    return {"draft": response.content}


async def human_review_node(state: AgentState):
    """
    这是一个占位节点，其实它什么都不用干。
    我们把它放在图里，单纯是为了在它『执行之前』设置一个断点。
    """
    print(">>> [Human Review] 人类审批完成，流程继续...")
    return {}


async def publisher_node(state: AgentState):
    print(">>> [Publisher] 正在发布最终研报并存库...")
    return {}


def route_after_human(state: AgentState) -> str:
    """条件路由：根据人类的决定，决定下一步去哪"""
    if state.get("is_approved"):
        return "publisher"
    else:
        print("!!! 流程被人类拒绝，打回重做...")
        return "researcher"


# 全局变量存放编译好的 Graph
app_graph = None


# ==========================================
# 2. FastAPI 初始化与数据库挂载
# ==========================================
@asynccontextmanager
async def lifespan(app: FastAPI):
    # 启动时连接 SQLite 并编译 Graph
    async with aiosqlite.connect("checkpoints.sqlite") as conn:
        checkpointer = AsyncSqliteSaver(conn)

        builder = StateGraph(AgentState)
        builder.add_node("researcher", researcher_node)
        builder.add_node("writer", writer_node)
        builder.add_node("human_review", human_review_node)
        builder.add_node("publisher", publisher_node)

        builder.add_edge(START, "researcher")
        builder.add_edge("researcher", "writer")
        builder.add_edge("writer", "human_review")
        # 核心：人类审批节点后，接条件路由
        builder.add_conditional_edges(
            "human_review",
            route_after_human,
            {"publisher": "publisher", "researcher": "researcher"},
        )
        builder.add_edge("publisher", END)

        global app_graph
        # 【核心断点】：在 human_review 执行前暂停挂起！
        app_graph = builder.compile(
            checkpointer=checkpointer, interrupt_before=["human_review"]
        )

        print("====== 🚀 FastAPI 启动，LangGraph 已就绪 ======")
        yield


app = FastAPI(lifespan=lifespan)


# ==========================================
# 3. FastAPI 接口设计 (前后端桥梁)
# ==========================================
class StartReq(BaseModel):
    thread_id: str
    company: str


class ApproveReq(BaseModel):
    is_approved: bool
    feedback: str


@app.post("/api/start")
async def start_graph(req: StartReq, background_tasks: BackgroundTasks):
    config = {"configurable": {"thread_id": req.thread_id}}
    # 后台异步运行，不会阻塞 API 响应
    background_tasks.add_task(app_graph.ainvoke, {"company": req.company}, config)
    return {"msg": "Task started in background"}


@app.get("/api/status/{thread_id}")
async def get_status(thread_id: str):
    config = {"configurable": {"thread_id": thread_id}}
    state_snapshot = await app_graph.aget_state(config)

    # 巧妙的判断逻辑：
    if not state_snapshot or not state_snapshot.next:
        # 如果 next 为空，且 state_snapshot 里有数据，说明走到了 END
        if state_snapshot and state_snapshot.values.get("draft"):
            return {"status": "finished", "draft": state_snapshot.values.get("draft")}
        return {"status": "not_started"}

    # 如果 next 指向的是 human_review，说明碰到了我们的断点，正处于挂起等待状态
    if "human_review" in state_snapshot.next:
        return {
            "status": "waiting_for_approval",
            "draft": state_snapshot.values.get("draft"),
        }

    # 其他情况就是图还在后台转圈圈运行中
    return {"status": "running"}


@app.post("/api/approve/{thread_id}")
async def approve_step(
    thread_id: str, req: ApproveReq, background_tasks: BackgroundTasks
):
    config = {"configurable": {"thread_id": thread_id}}

    # 1. 核心 API：向图中注入人类的审批结果
    await app_graph.aupdate_state(
        config,
        {"is_approved": req.is_approved, "human_feedback": req.feedback},
        as_node="writer",
    )  # 假装是刚从 writer 出来，准备进入下个阶段

    # 2. 唤醒图，让它从挂起的地方继续跑（传入 None 代表使用最新状态继续）
    background_tasks.add_task(app_graph.ainvoke, None, config)

    return {"msg": "Decision applied, graph resumed"}


# ==========================================
# 4. 极简前端页面 (直接用 FastAPI 返回 HTML)
# ==========================================
HTML_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <title>AI 研报审批流 (Human-in-the-loop)</title>
    <style>
        body { font-family: sans-serif; padding: 40px; background: #f4f4f9; }
        .card { background: white; padding: 20px; border-radius: 8px; box-shadow: 0 4px 6px rgba(0,0,0,0.1); max-width: 600px; margin: auto;}
        input, textarea { width: 100%; padding: 10px; margin: 10px 0; border: 1px solid #ccc; border-radius: 4px; box-sizing: border-box;}
        button { padding: 10px 20px; border: none; border-radius: 4px; cursor: pointer; color: white;}
        .btn-start { background: #3b82f6; }
        .btn-approve { background: #22c55e; }
        .btn-reject { background: #ef4444; }
        #status-bar { margin: 20px 0; padding: 10px; font-weight: bold; text-align: center; border-radius: 4px; }
    </style>
</head>
<body>
    <div class="card">
        <h2>深度研报 Agent</h2>

        <input type="text" id="company" placeholder="输入公司名，如：特斯拉" value="特斯拉">
        <button class="btn-start" onclick="startAgent()">🚀 开始生成研报</button>

        <div id="status-bar" style="background:#e5e7eb;">状态：尚未开始</div>

        <div id="approval-box" style="display: none; background: #fffbeb; padding: 15px; border-left: 4px solid #f59e0b;">
            <h3>⚠️ 请审批初稿：</h3>
            <textarea id="draft-display" rows="5" disabled></textarea>

            <input type="text" id="feedback" placeholder="如果拒绝，请填写修改意见...">
            <div style="display: flex; gap: 10px; margin-top:10px;">
                <button class="btn-approve" onclick="submitDecision(true)">✅ 合格，发布</button>
                <button class="btn-reject" onclick="submitDecision(false)">❌ 不合格，打回重做</button>
            </div>
        </div>
    </div>

    <script>
        const threadId = "thread_" + Math.floor(Math.random() * 10000);
        let pollInterval;

        async function startAgent() {
            const company = document.getElementById('company').value;
            await fetch('/api/start', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({ thread_id: threadId, company: company })
            });
            document.getElementById('status-bar').innerText = "状态：后台运行中 ⏳...";
            document.getElementById('status-bar').style.background = "#dbeafe";

            // 开始轮询状态
            pollInterval = setInterval(checkStatus, 2000);
        }

        async function checkStatus() {
            const res = await fetch('/api/status/' + threadId);
            const data = await res.json();

            if (data.status === "waiting_for_approval") {
                clearInterval(pollInterval);
                document.getElementById('status-bar').innerText = "状态：已挂起，等待人类审批 ✋";
                document.getElementById('status-bar').style.background = "#fef3c7";

                document.getElementById('approval-box').style.display = 'block';
                document.getElementById('draft-display').value = data.draft;
            } else if (data.status === "finished") {
                clearInterval(pollInterval);
                document.getElementById('status-bar').innerText = "状态：已完成发布 🎉";
                document.getElementById('status-bar').style.background = "#d1fae5";

                document.getElementById('approval-box').style.display = 'block';
                document.getElementById('draft-display').value = data.draft;
                document.querySelector('.btn-approve').style.display = 'none';
                document.querySelector('.btn-reject').style.display = 'none';
                document.getElementById('feedback').style.display = 'none';
            }
        }

        async function submitDecision(isApproved) {
            const feedback = document.getElementById('feedback').value;
            await fetch('/api/approve/' + threadId, {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({ is_approved: isApproved, feedback: feedback })
            });

            document.getElementById('approval-box').style.display = 'none';
            document.getElementById('status-bar').innerText = "状态：收到决策，图已恢复运行 ⏳...";

            // 重启轮询监听下一阶段结果
            pollInterval = setInterval(checkStatus, 2000);
        }
    </script>
</body>
</html>
"""


@app.get("/", response_class=HTMLResponse)
async def serve_frontend():
    return HTML_TEMPLATE
