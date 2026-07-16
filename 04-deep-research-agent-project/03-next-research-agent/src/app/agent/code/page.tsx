// src/app/page.tsx
'use client';

import { Button } from '@/components/ui/button'

export default function ResearchAgent() {

  const chat = async () => {
    const res = await fetch('/api/agent/code', { method: 'POST' });
    const { text, steps } = await res.json();
    console.log(text);
    console.log(steps);
  }

  return (
    <div>
      <Button onClick={chat}>code agent</Button>
    </div>
  )
}
