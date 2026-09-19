import { useState } from 'react';
import './MessageContent.css';

// Parses raw message text into blocks: paragraphs and bullet lists.
// Bullet syntax: "- main point :: expandable detail text"
// Inline clickable-word syntax: "[[word]]"
function parseBlocks(text) {
  const lines = text.split('\n');
  const blocks = [];
  let paragraph = [];
  let bullets = null;

  const flushParagraph = () => {
    if (paragraph.length) {
      blocks.push({ type: 'paragraph', text: paragraph.join(' ') });
      paragraph = [];
    }
  };
  const flushBullets = () => {
    if (bullets) {
      blocks.push(bullets);
      bullets = null;
    }
  };

  for (const rawLine of lines) {
    const line = rawLine.trim();
    if (line.startsWith('- ')) {
      flushParagraph();
      if (!bullets) bullets = { type: 'bullets', items: [] };
      const [main, detail] = line.slice(2).split('::').map((s) => s.trim());
      bullets.items.push({ main, detail: detail || null });
    } else if (line === '') {
      flushBullets();
      flushParagraph();
    } else {
      flushBullets();
      paragraph.push(line);
    }
  }
  flushBullets();
  flushParagraph();
  return blocks;
}

function renderInline(text, onWordClick) {
  const parts = text.split(/(\[\[.+?\]\])/g);
  return parts.map((part, i) => {
    const match = part.match(/^\[\[(.+?)\]\]$/);
    if (match) {
      return (
        <button
          key={i}
          type="button"
          className="clickable-word"
          onClick={() => onWordClick(match[1])}
        >
          {match[1]}
        </button>
      );
    }
    return <span key={i}>{part}</span>;
  });
}

function BulletItem({ item, onWordClick }) {
  const [expanded, setExpanded] = useState(false);

  return (
    <li className="bullet-item">
      <div className="bullet-row">
        <span className="bullet-text">{renderInline(item.main, onWordClick)}</span>
        {item.detail && (
          <button
            type="button"
            className={`bullet-toggle ${expanded ? 'expanded' : ''}`}
            onClick={() => setExpanded((e) => !e)}
            aria-expanded={expanded}
            title={expanded ? 'Collapse' : 'Expand'}
          >
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round">
              <path d="M9 6l6 6-6 6" />
            </svg>
          </button>
        )}
      </div>
      {item.detail && expanded && (
        <div className="bullet-detail">{renderInline(item.detail, onWordClick)}</div>
      )}
    </li>
  );
}

export default function MessageContent({ text, onWordClick }) {
  const blocks = parseBlocks(text);

  return (
    <>
      {blocks.map((block, i) => {
        if (block.type === 'bullets') {
          return (
            <ul className="bullet-list" key={i}>
              {block.items.map((item, j) => (
                <BulletItem key={j} item={item} onWordClick={onWordClick} />
              ))}
            </ul>
          );
        }
        return (
          <p className="message-paragraph" key={i}>
            {renderInline(block.text, onWordClick)}
          </p>
        );
      })}
    </>
  );
}
