// src/app/page.tsx
'use client';

export default function ResearchAgent() {

  const chat = async () => {
    const res = await fetch('/api/agent', { method: 'POST' });
    // const { text } = await res.json();
    // console.log(text);
  }

  return (
    <button onClick={chat}>chat</button>
  )
}
