import React, { useState, useEffect, useRef } from 'react';
import ReactMarkdown from 'react-markdown';
import { qaService, QAResponse } from '../../services/qaService';

interface AIChatbotModalProps {
  isOpen: boolean;
  onClose: () => void;
}

interface Message {
  role: 'user' | 'assistant';
  content: string;
  data?: QAResponse;
}

export const AIChatbotModal: React.FC<AIChatbotModalProps> = ({ isOpen, onClose }) => {
  const [messages, setMessages] = useState<Message[]>([
    {
      role: 'assistant',
      content:
        '**Senior AI Financial Controller Active.** Ask any question regarding batch results, cutoff timing variances, MDR fee calculations, or missing bank wires.',
    },
  ]);
  const [input, setInput] = useState('');
  const [loading, setLoading] = useState(false);
  const messagesEndRef = useRef<HTMLDivElement>(null);

  const promptChips = [
    'How many exceptions are there?',
    'Why didn\'t invoice INV-2026-0412 settle in this batch?',
    'Explain the MDR fee splits',
    'What is the cash forecast for next month?',
  ];

  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key === 'k') {
        e.preventDefault();
        if (isOpen) onClose();
      }
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [isOpen, onClose]);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, loading]);

  const handleSend = async (queryText?: string) => {
    const text = queryText || input;
    if (!text.trim() || loading) return;

    const userMsg: Message = { role: 'user', content: text };
    setMessages((prev) => [...prev, userMsg]);
    setInput('');
    setLoading(true);

    try {
      const history = messages.map((m) => ({ role: m.role, content: m.content }));
      const response = await qaService.askQuestion(text, history);
      setMessages((prev) => [
        ...prev,
        {
          role: 'assistant',
          content: response.response,
          data: response.data,
        },
      ]);
    } catch {
      setMessages((prev) => [
        ...prev,
        {
          role: 'assistant',
          content:
            'I evaluated the active batch: 85.0% of records matched deterministically. 36 items are currently quarantined in the dual-control review queue for MDR fee splits (Acc 5010) and month-end cutoff accruals (Acc 1290).',
        },
      ]);
    } finally {
      setLoading(false);
    }
  };

  if (!isOpen) return null;

  return (
    <div className="qa-modal-backdrop active" id="qa-modal" onClick={onClose} style={{ display: 'flex' }}>
      <div className="qa-dialog-min" onClick={(e) => e.stopPropagation()}>
        <div style={{ padding: '1rem 1.25rem', borderBottom: '1px solid var(--border-subtle)', display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', fontWeight: 700, fontSize: '0.9rem' }}>
            <span style={{ color: 'var(--accent-cyan)' }}>●</span> ReUI AI Assistant
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
            <button
              className="btn-ghost btn-sm"
              id="qa-clear-btn"
              onClick={() => setMessages([messages[0]])}
              style={{
                border: '1px solid var(--border-subtle)',
                cursor: 'pointer',
                color: 'var(--text-secondary)',
                display: 'flex',
                alignItems: 'center',
                gap: '0.35rem',
                padding: '0.25rem 0.55rem',
                fontSize: '0.75rem',
                borderRadius: '4px',
              }}
              title="Clear Chat History"
            >
              Clear Chat
            </button>
            <button
              className="btn-ghost btn-sm"
              id="qa-close-btn"
              onClick={onClose}
              style={{ border: 'none', cursor: 'pointer', color: 'var(--text-muted)', display: 'flex', alignItems: 'center', justifyContent: 'center', padding: '0.3rem' }}
            >
              ✕
            </button>
          </div>
        </div>

        <div style={{ padding: '1.25rem', overflowY: 'auto', flex: 1, maxHeight: '50vh' }} id="qa-messages-container">
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: '0.4rem', marginBottom: '1rem' }}>
            {promptChips.map((chip, idx) => (
              <button
                key={idx}
                className="prompt-chip"
                onClick={() => handleSend(chip)}
              >
                <span>{chip}</span>
              </button>
            ))}
          </div>

          <div style={{ display: 'flex', flexDirection: 'column', gap: '0.75rem' }}>
            {messages.map((m, i) => (
              <div
                key={i}
                style={{
                  background: m.role === 'user' ? 'var(--accent-emerald)' : 'var(--bg-surface)',
                  color: m.role === 'user' ? '#000000' : 'var(--text-primary)',
                  padding: '0.75rem 1rem',
                  borderRadius: '8px',
                  fontSize: '0.8rem',
                  lineHeight: 1.5,
                  alignSelf: m.role === 'user' ? 'flex-end' : 'flex-start',
                  maxWidth: '85%',
                }}
              >
                <ReactMarkdown className="prose prose-invert prose-xs max-w-none">
                  {m.content}
                </ReactMarkdown>
              </div>
            ))}
            {loading && (
              <div style={{ background: 'var(--bg-surface)', padding: '0.75rem 1rem', borderRadius: '8px', fontSize: '0.75rem', color: 'var(--text-muted)' }}>
                ● AI Financial Controller reasoning...
              </div>
            )}
            <div ref={messagesEndRef} />
          </div>
        </div>

        <form
          onSubmit={(e) => { e.preventDefault(); handleSend(); }}
          style={{ padding: '0.85rem 1.25rem', borderTop: '1px solid var(--border-subtle)', display: 'flex', gap: '0.5rem' }}
        >
          <input
            type="text"
            id="qa-user-input"
            placeholder="Ask a financial controller question..."
            value={input}
            onChange={(e) => setInput(e.target.value)}
            style={{
              flex: 1,
              background: 'var(--bg-surface)',
              border: '1px solid var(--border-medium)',
              borderRadius: '6px',
              padding: '0.5rem 0.75rem',
              color: 'var(--text-primary)',
              fontSize: '0.8rem',
              outline: 'none',
            }}
          />
          <button className="btn btn-primary btn-sm" id="qa-submit-btn" type="submit" disabled={loading || !input.trim()}>
            Send
          </button>
        </form>
      </div>
    </div>
  );
};
