import { useRef } from 'react';
import './ChatInput.css';

function SendIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
      <path d="M12 19V5M5 12l7-7 7 7" />
    </svg>
  );
}

export default function ChatInput({ value, onChange, onSend, disabled, placeholder = 'Message...' }) {
  const textareaRef = useRef(null);

  const handleInput = (e) => {
    onChange(e.target.value);
    const el = textareaRef.current;
    if (el) {
      el.style.height = 'auto';
      el.style.height = Math.min(el.scrollHeight, 200) + 'px';
    }
  };

  const handleKeyDown = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      if (value.trim() && !disabled) {
        onSend();
        if (textareaRef.current) textareaRef.current.style.height = 'auto';
      }
    }
  };

  return (
    <div className="chat-input-bar">
      <div className="chat-input-container">
        <textarea
          ref={textareaRef}
          className="chat-input"
          placeholder={placeholder}
          rows={1}
          value={value}
          onChange={handleInput}
          onKeyDown={handleKeyDown}
          disabled={disabled}
        />
        <button
          className="send-button"
          disabled={!value.trim() || disabled}
          onClick={onSend}
          title="Send message"
        >
          <SendIcon />
        </button>
      </div>
      <div className="chat-input-hint">Press Enter to send, Shift+Enter for a new line</div>
    </div>
  );
}
