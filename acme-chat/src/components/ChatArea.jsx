import { useEffect, useRef } from 'react';
import MessageContent from './MessageContent.jsx';
import './ChatArea.css';

export default function ChatArea({ messages, onWordClick, pending }) {
  const endRef = useRef(null);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, pending]);

  if (messages.length === 0 && !pending) {
    return (
      <div className="chat-area chat-area-empty">
        <h1>Ask acme-agent</h1>
      </div>
    );
  }

  return (
    <div className="chat-area">
      <div className="message-list">
        {messages.map((msg) => (
          <div key={msg.id} className={`message-row ${msg.role}`}>
            <div className={`message-bubble ${msg.isError ? 'error' : ''}`}>
              {msg.role === 'assistant' ? (
                <MessageContent text={msg.text} onWordClick={onWordClick} />
              ) : (
                msg.text
              )}
            </div>
          </div>
        ))}
        {pending && (
          <div className="message-row assistant">
            <div className="message-bubble message-bubble-pending">
              <span className="dot" />
              <span className="dot" />
              <span className="dot" />
            </div>
          </div>
        )}
        <div ref={endRef} />
      </div>
    </div>
  );
}
