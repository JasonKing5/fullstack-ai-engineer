从零搭建 Next.js + FastAPI 流式 AI Chat 项目

Context

参考当前项目 03-fastapi-react-project，从零搭建一个功能完全相同的新项目，但使用更新的依赖版本。核心功能：
- FastAPI Python 后端，通过 SSE Data Stream Protocol 流式返回 AI 响应
- Next.js 前端，useChat hook 接收流式数据，打字机效果展示
- 工具调用（Function Calling）：天气查询示例
- 图文混合输入（Multimodal）

版本升级要点：
- Next.js 13 → 15.x（React 19）
- 去除 Vercel 特有依赖（vercel、vercel-sdk），改为直接调用 OpenAI API（base_url 可配置，支持 LiteLLM 等代理）

---
最终目录结构

03-ai-chat-app/
├── api/
│   ├── index.py
│   └── utils/
│       ├── __init__.py
│       ├── attachment.py
│       ├── prompt.py
│       ├── stream.py
│       └── tools.py
├── app/
│   ├── (chat)/
│   │   └── page.tsx
│   ├── globals.css
│   ├── icons.tsx
│   └── layout.tsx
├── components/
│   ├── chat.tsx
│   ├── icons.tsx
│   ├── message.tsx
│   ├── multimodal-input.tsx
│   ├── navbar.tsx
│   ├── overview.tsx
│   ├── weather.tsx
│   └── ui/           ← shadcn 自动生成
│       ├── button.tsx
│       └── textarea.tsx
├── hooks/
│   └── use-scroll-to-bottom.tsx
├── lib/
│   └── utils.ts      ← shadcn 自动生成
├── venv/             ← Python 虚拟环境（不提交 git）
├── components.json
├── tailwind.config.js
├── next.config.js
├── package.json
├── requirements.txt
├── tsconfig.json
└── .env

---
分步操作指南

Step 1：创建 Next.js 项目（CLI 脚手架）

pnpm create next-app@latest 03-ai-chat-app \
--typescript \
--tailwind \
--eslint \
--app \
--no-src-dir \
--import-alias="@/*"

cd 03-ai-chat-app

交互选项全部选默认即可（App Router，不使用 src 目录）。

---
Step 2：安装前端依赖

pnpm add ai @ai-sdk/react \
framer-motion sonner usehooks-ts \
date-fns clsx tailwind-merge tailwindcss-animate \
streamdown geist lucide-react \
concurrently

---
Step 3：初始化 shadcn/ui

pnpm dlx shadcn@latest init

选项：
- Style: New York
- Base color: Zinc
- CSS variables: Yes

然后添加组件：

pnpm dlx shadcn@latest add button textarea

这会自动生成 components/ui/button.tsx、components/ui/textarea.tsx、lib/utils.ts、更新 tailwind.config.js。

---
Step 4：配置 Python 虚拟环境

python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate

pip install fastapi uvicorn openai python-dotenv requests pydantic

pip freeze > requirements.txt

---
Step 5：创建 .env 文件

# .env
OPENAI_API_KEY=your_key_here

# 如果使用 LiteLLM 或其他代理，额外加：
# OPENAI_BASE_URL=https://www.litellm.org/

---
Step 6：配置文件修改

next.config.js（参考当前项目，路径不变）

/** @type {import('next').NextConfig} */
const nextConfig = {
rewrites: async () => [
  {
    source: "/api/:path*",
    destination:
      process.env.NODE_ENV === "development"
        ? "http://127.0.0.1:8000/api/:path*"
        : "/api/",
  },
],
};
module.exports = nextConfig;

package.json scripts 部分

手动添加 scripts（create-next-app 只生成 dev/build/start/lint）：

"scripts": {
"next-dev": "next dev",
"fastapi-dev": "source venv/bin/activate && uvicorn api.index:app --reload",
"dev": "concurrently \"npm run next-dev\" \"npm run fastapi-dev\"",
"build": "next build",
"start": "next start",
"lint": "next lint"
}

---
Step 7：创建 Python 后端文件

按以下顺序创建，每个文件直接参考当前项目对应文件：

api/__init__.py

空文件。

api/utils/__init__.py

空文件。

api/utils/attachment.py

参考：03-fastapi-react-project/api/utils/attachment.py
内容完全相同（定义 ClientAttachment Pydantic model）。

api/utils/tools.py

参考：03-fastapi-react-project/api/utils/tools.py
内容完全相同（get_current_weather 函数 + TOOL_DEFINITIONS + AVAILABLE_TOOLS）。

api/utils/prompt.py

参考：03-fastapi-react-project/api/utils/prompt.py
内容完全相同（ClientMessage Pydantic model + convert_to_openai_messages 转换函数）。

api/utils/stream.py

参考：03-fastapi-react-project/api/utils/stream.py
内容完全相同（stream_text + patch_response_with_headers）。
▎ 注意：这个文件的 SSE 格式实现已经符合 Vercel AI SDK v5 的 Data Stream Protocol 规范，不需要修改。

api/index.py

参考：03-fastapi-react-project/api/index.py，但做以下修改（去除 Vercel 特有依赖）：

import os
from typing import List

from dotenv import load_dotenv
from fastapi import FastAPI, Query
from fastapi import Request as FastAPIRequest
from fastapi.responses import StreamingResponse
from openai import OpenAI
from pydantic import BaseModel

from .utils.prompt import ClientMessage, convert_to_openai_messages
from .utils.stream import patch_response_with_headers, stream_text
from .utils.tools import AVAILABLE_TOOLS, TOOL_DEFINITIONS

load_dotenv()

app = FastAPI()

class Request(BaseModel):
  messages: List[ClientMessage]

@app.post("/api/chat")
async def handle_chat_data(request: Request, protocol: str = Query("data")):
  messages = request.messages
  openai_messages = convert_to_openai_messages(messages)

  client = OpenAI(
      api_key=os.getenv("OPENAI_API_KEY"),
      base_url=os.getenv("OPENAI_BASE_URL"),  # None = 默认 OpenAI；填 LiteLLM 地址则走代理
  )

  response = StreamingResponse(
      stream_text(client, openai_messages, TOOL_DEFINITIONS, AVAILABLE_TOOLS, protocol),
      media_type="text/event-stream",
  )
  return patch_response_with_headers(response, protocol)

stream.py 中 model 参数也改为从环境变量读取：
# stream.py 第 34 行 model 改为：
model=os.getenv("MODEL_NAME", "gpt-4o-mini"),

---
Step 8：创建前端文件

按以下顺序创建：

app/globals.css

create-next-app 已生成，只需保留 Tailwind 指令，加上 CSS 变量（shadcn 的颜色变量）。参考当前项目 app/globals.css，完整复制 :root 和 .dark 里的 CSS 变量部分。

app/layout.tsx

参考：03-fastapi-react-project/app/layout.tsx
完全相同（引入 GeistSans 字体、Toaster、Navbar，设置 metadata）。

app/(chat)/page.tsx

参考：03-fastapi-react-project/app/(chat)/page.tsx
完全相同（export const dynamic = "force-dynamic"，渲染 <Chat />）。

app/icons.tsx

参考：03-fastapi-react-project/app/icons.tsx
完全相同（Python logo SVG 组件）。

components/icons.tsx

参考：03-fastapi-react-project/components/icons.tsx
完全相同（SparklesIcon、ArrowUpIcon、StopIcon、GitIcon、VercelIcon、MessageIcon SVG 组件）。

components/navbar.tsx

参考：03-fastapi-react-project/components/navbar.tsx
完全相同（顶部导航栏）。

components/overview.tsx

参考：03-fastapi-react-project/components/overview.tsx
完全相同（初始欢迎页 motion 动画）。

hooks/use-scroll-to-bottom.tsx

参考：03-fastapi-react-project/hooks/use-scroll-to-bottom.tsx
完全相同（MutationObserver 自动滚动 hook）。

lib/utils.ts

shadcn init 已生成 cn，只需追加 sanitizeUIMessages 函数。
参考：03-fastapi-react-project/lib/utils.ts 第 9-43 行。

components/weather.tsx

参考：03-fastapi-react-project/components/weather.tsx
完全相同（天气展示 UI 组件）。

components/message.tsx

参考：03-fastapi-react-project/components/message.tsx
完全相同（PreviewMessage + ThinkingMessage，使用 Streamdown 渲染 markdown）。

components/multimodal-input.tsx

参考：03-fastapi-react-project/components/multimodal-input.tsx
完全相同（输入框 + 快捷建议按钮 + 发送/停止按钮）。

components/chat.tsx

参考：03-fastapi-react-project/components/chat.tsx
完全相同（useChat hook 集成，消息列表渲染，表单提交）。

---
Step 9：tailwind.config.js 补充

shadcn init 已生成大部分，需要补充 streamdown 的路径（确保 markdown 样式生效）：

content: [
'./app/**/*.{js,ts,jsx,tsx,mdx}',
'./components/**/*.{js,ts,jsx,tsx,mdx}',
'./node_modules/streamdown/dist/*.js',   // ← 追加这行
],

---
Step 10：启动开发服务

# 终端 1（或用 concurrently 一键启动）
pnpm dev

访问 http://localhost:3000 验证功能。

---
关键版本对比

┌───────────────────┬─────────┬─────────────────────┐
│        包         │ 原项目  │       新项目        │
├───────────────────┼─────────┼─────────────────────┤
│ next              │ 13.4.4  │ 15.x                │
├───────────────────┼─────────┼─────────────────────┤
│ react             │ 18.2.0  │ 19.x                │
├───────────────────┼─────────┼─────────────────────┤
│ ai                │ v5.0.76 │ v5.x (latest)       │
├───────────────────┼─────────┼─────────────────────┤
│ @ai-sdk/react     │ v2.0.76 │ v2.x (latest)       │
├───────────────────┼─────────┼─────────────────────┤
│ openai (Python)   │ 2.6.0   │ 1.57+ (标准 v1 SDK) │
├───────────────────┼─────────┼─────────────────────┤
│ vercel/vercel-sdk │ 依赖    │ 移除                │
└───────────────────┴─────────┴─────────────────────┘

注意事项

- openai Python SDK v2.x 是实验性版本，当前项目用的其实是 v1.x（pip install openai 默认装 v1）
- stream.py 中的 SSE 格式是自定义实现，符合 Vercel AI SDK Data Stream Protocol v1 规范，前后端协议固定，不需要随 SDK 版本改动
- Next.js 15 App Router 的 headers()/cookies() 变为 async，但本项目没有用到，无影响
