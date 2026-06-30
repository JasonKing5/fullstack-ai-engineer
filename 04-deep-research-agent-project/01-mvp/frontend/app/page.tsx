'use client';

import { useChat } from '@ai-sdk/react';
import { DefaultChatTransport } from 'ai';
import { Card } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { ScrollArea } from '@/components/ui/scroll-area';
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer } from 'recharts';
import { useState, useMemo } from 'react';

export default function ChatPage() {
  const [input, setInput] = useState('');

  // sessionStorage 内复用同一 threadId，页面刷新/热更新不会丢失图状态
  const threadId = useMemo(() => {
    const key = 'research_thread_id';
    const stored = sessionStorage.getItem(key);
    if (stored) return stored;
    const id = crypto.randomUUID();
    sessionStorage.setItem(key, id);
    return id;
  }, []);

  const transport = useMemo(
    () => new DefaultChatTransport({
      api: 'http://localhost:8000/api/research/chat',
      body: { thread_id: threadId },
    }),
    [threadId]
  );

  const { messages, setMessages, sendMessage } = useChat({ transport });

  // 每张审批卡片独立维护：待确认的操作 + 反馈文字 + 是否已提交
  type CardState = { pendingAction: 'approve' | 'reject' | null; feedback: string };
  const [cardStateMap, setCardStateMap] = useState<Record<string, CardState>>({});
  const [actedSet, setActedSet] = useState<Set<string>>(new Set());

  const getCardState = (id: string): CardState =>
    cardStateMap[id] ?? { pendingAction: null, feedback: '' };

  const setCardPending = (id: string, action: 'approve' | 'reject') =>
    setCardStateMap(prev => ({ ...prev, [id]: { pendingAction: action, feedback: '' } }));

  const setCardFeedback = (id: string, text: string) =>
    setCardStateMap(prev => ({ ...prev, [id]: { ...getCardState(id), feedback: text } }));

  const resetCard = (id: string) =>
    setCardStateMap(prev => ({ ...prev, [id]: { pendingAction: null, feedback: '' } }));

  // 处理表单提交
  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!input.trim()) return;
    sendMessage({ text: input });
    setInput('');
  };

  /**
   * 消费 /api/research/approve 返回的 SSE 流。
   * 同意：流中只有 text-delta（最终报告）。
   * 拒绝：流中有 text-delta（新草稿）+ tool-input-available（新图表 + 新审批卡）。
   */
  const handleApprove = async (approved: boolean, toolCallId: string) => {
    const feedback = getCardState(toolCallId).feedback;

    // 标记该卡片已操作，防止重复提交
    setActedSet((prev) => new Set(prev).add(toolCallId));

    const newMsgId = `approve-resp-${Date.now()}`;

    const res = await fetch('http://localhost:8000/api/research/approve', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ thread_id: threadId, approved, feedback }),
    });
    if (!res.ok || !res.body) {
      // 请求失败，回滚已操作标记，让用户可以重试
      setActedSet((prev) => { const s = new Set(prev); s.delete(toolCallId); return s; });
      console.error('Approve failed:', res.status, await res.text());
      return;
    }

    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split('\n');
      buffer = lines.pop() ?? '';

      for (const line of lines) {
        if (!line.startsWith('data: ')) continue;
        const data = line.slice(6).trim();
        if (data === '[DONE]') break;

        try {
          const chunk = JSON.parse(data);

          if (chunk.type === 'text-delta') {
            setMessages((prev) => {
              const existing = prev.find((m) => m.id === newMsgId);
              if (!existing) {
                return [...prev, { id: newMsgId, role: 'assistant', parts: [{ type: 'text', text: chunk.delta }] } as any];
              }
              return prev.map((m) => {
                if (m.id !== newMsgId) return m;
                const parts = [...(m.parts as any[])];
                const textIdx = parts.findIndex((p) => p.type === 'text');
                if (textIdx >= 0) {
                  parts[textIdx] = { ...parts[textIdx], text: parts[textIdx].text + chunk.delta };
                } else {
                  parts.push({ type: 'text', text: chunk.delta });
                }
                return { ...m, parts };
              });
            });
          }

          // 拒绝并重新生成时，后端会下发新的图表和审批卡
          if (chunk.type === 'tool-input-available') {
            const toolPart = {
              type: 'dynamic-tool',
              toolCallId: chunk.toolCallId,
              toolName: chunk.toolName,
              input: chunk.input,
              state: 'input-available',
            };
            setMessages((prev) => {
              const existing = prev.find((m) => m.id === newMsgId);
              if (!existing) {
                return [...prev, { id: newMsgId, role: 'assistant', parts: [toolPart] } as any];
              }
              return prev.map((m) =>
                m.id === newMsgId ? { ...m, parts: [...(m.parts as any[]), toolPart] } : m
              );
            });
          }
        } catch { /* 忽略非 JSON 行 */ }
      }
    }
  };

  return (
    <div className="flex flex-col h-screen bg-gray-50 max-w-280 p-4">
      <h1 className="text-2xl font-bold mb-4">B2B 金融研报智能体 (Generative UI)</h1>

      <ScrollArea className="flex-1 bg-white border rounded-xl p-4 shadow-sm mb-4">
        {messages.map((m) => (
          <div key={m.id} className={`mb-6 ${m.role === 'user' ? 'text-right' : 'text-left'}`}>

            {/* 文本内容 */}
            {(m.parts as any[])
              .filter((p) => p.type === 'text')
              .map((p, i) => (
                <div
                  key={i}
                  className={`inline-block p-3 rounded-lg ${
                    m.role === 'user' ? 'bg-blue-600 text-white' : 'bg-gray-100 text-gray-800'
                  }`}
                >
                  {p.text}
                </div>
              ))}

            {/* Generative UI 工具卡片 */}
            {(m.parts as any[])
              .filter((p) => p.type === 'dynamic-tool')
              .map((tool) => {

                if (tool.toolName === 'render_financial_chart') {
                  return (
                    <Card key={tool.toolCallId} className="w-full mt-4 p-4 shadow-md bg-white border-blue-100 border-2">
                      <h3 className="font-bold text-lg mb-4">
                        📊 {tool.input.company} 历年营收趋势分析 (Generative UI)
                      </h3>
                      <div className="h-64 w-full">
                        <ResponsiveContainer width="100%" height="100%">
                          <BarChart data={tool.input.data}>
                            <XAxis dataKey="year" />
                            <YAxis />
                            <Tooltip cursor={{ fill: '#f3f4f6' }} />
                            <Bar dataKey="revenue" fill="#3b82f6" radius={[4, 4, 0, 0]} />
                          </BarChart>
                        </ResponsiveContainer>
                      </div>
                    </Card>
                  );
                }

                if (tool.toolName === 'request_human_approval') {
                  const isActed = actedSet.has(tool.toolCallId);
                  const card = getCardState(tool.toolCallId);

                  // 初始状态：仅展示两个操作按钮
                  if (!card.pendingAction && !isActed) {
                    return (
                      <Card key={tool.toolCallId} className="w-full mt-4 p-4 bg-orange-50 border-orange-200 shadow-md">
                        <h3 className="font-bold text-orange-700">
                          ⚠️ 需人类介入审批 (Human-in-the-loop)
                        </h3>
                        <p className="text-sm text-gray-600 my-3">{tool.input.summary}</p>
                        <div className="flex gap-3 mt-1">
                          <Button
                            onClick={() => setCardPending(tool.toolCallId, 'approve')}
                            className="bg-green-600 hover:bg-green-700"
                          >
                            同意并生成
                          </Button>
                          <Button
                            variant="outline"
                            onClick={() => setCardPending(tool.toolCallId, 'reject')}
                          >
                            拒绝并打回
                          </Button>
                        </div>
                      </Card>
                    );
                  }

                  // 已操作后的只读状态
                  if (isActed) {
                    return (
                      <Card key={tool.toolCallId} className="w-full mt-4 p-4 bg-gray-50 border-gray-200 shadow-md opacity-60">
                        <h3 className="font-bold text-gray-500">
                          ⚠️ 需人类介入审批 (Human-in-the-loop)
                        </h3>
                        <p className="text-sm text-gray-400 my-3">{tool.input.summary}</p>
                        <p className="text-xs text-gray-400">已提交</p>
                      </Card>
                    );
                  }

                  // 展开状态：显示对应 textarea + 确认/取消
                  const isApprove = card.pendingAction === 'approve';
                  return (
                    <Card key={tool.toolCallId} className="w-full mt-4 p-4 bg-orange-50 border-orange-200 shadow-md">
                      <h3 className="font-bold text-orange-700">
                        ⚠️ 需人类介入审批 (Human-in-the-loop)
                      </h3>
                      <p className="text-sm text-gray-600 my-3">{tool.input.summary}</p>
                      <label className="text-sm font-medium text-gray-700">
                        {isApprove ? '对最终报告的补充要求（可选）' : '请说明需要修改的内容（建议填写）'}
                      </label>
                      <textarea
                        autoFocus
                        value={card.feedback}
                        onChange={(e) => setCardFeedback(tool.toolCallId, e.target.value)}
                        placeholder={
                          isApprove
                            ? '例如：重点突出 2025 年增长预测…'
                            : '例如：需要补充竞争对手对比分析…'
                        }
                        rows={3}
                        className="w-full mt-1 mb-3 px-3 py-2 text-sm border border-gray-300 rounded-lg resize-none focus:outline-none focus:ring-2 focus:ring-orange-300"
                      />
                      <div className="flex gap-3">
                        <Button
                          onClick={() => handleApprove(isApprove, tool.toolCallId)}
                          className={isApprove ? 'bg-green-600 hover:bg-green-700' : 'bg-red-600 hover:bg-red-700'}
                        >
                          {isApprove ? '确认同意 ✓' : '确认拒绝并重新生成 ↩'}
                        </Button>
                        <Button
                          variant="outline"
                          onClick={() => resetCard(tool.toolCallId)}
                        >
                          取消
                        </Button>
                      </div>
                    </Card>
                  );
                }

                return (
                  <div key={tool.toolCallId} className="mt-4 p-4 bg-gray-100 rounded animate-pulse">
                    正在执行分析工具: {tool.toolName}...
                  </div>
                );
              })}
          </div>
        ))}
      </ScrollArea>

      <form onSubmit={handleSubmit} className="flex gap-2">
        <Input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder="例如：分析特斯拉最新财报..."
          className="flex-1 shadow-sm"
        />
        <Button type="submit">发送指令</Button>
      </form>
    </div>
  );
}
