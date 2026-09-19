import { useState } from 'react';
import ChatArea from './components/ChatArea.jsx';
import ChatInput from './components/ChatInput.jsx';
import './App.css';

let nextMessageId = 1;

export default function App() {
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState('');
  const [pending, setPending] = useState(false);

  const sendMessage = async (text) => {
    const trimmed = text.trim();
    if (!trimmed || pending) return;

    const userMessage = { id: nextMessageId++, role: 'user', text: trimmed };
    setMessages((prev) => [...prev, userMessage]);
    setInput('');
    setPending(true);

    try {
      const res = await fetch('/api/ask', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message: trimmed }),
      });
      const data = await res.json();

      const assistantMessage = {
        id: nextMessageId++,
        role: 'assistant',
        text: res.ok ? data.output || '(no output)' : data.error || 'Something went wrong.',
        isError: !res.ok,
      };
      setMessages((prev) => [...prev, assistantMessage]);
    } catch (err) {
      setMessages((prev) => [
        ...prev,
        {
          id: nextMessageId++,
          role: 'assistant',
          text: `Failed to reach the server: ${err.message}`,
          isError: true,
        },
      ]);
    } finally {
      setPending(false);
    }
  };

  const handleSend = () => sendMessage(input);
  const handleWordClick = (word) => sendMessage(`Tell me more about "${word}"`);

  return (
    <div className="app">
      <div className="main-panel">
        <ChatArea messages={messages} onWordClick={handleWordClick} pending={pending} />
        <ChatInput
          value={input}
          onChange={setInput}
          onSend={handleSend}
          disabled={pending}
          placeholder={pending ? 'Running acme-agent...' : 'Message...'}
        />
      </div>
    </div>
  );
}
