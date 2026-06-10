import { useState, useRef, useEffect } from 'react';
import { MessageSquare, X, Send, Loader2 } from 'lucide-react';
import { api } from '../lib/api';

interface Message {
  role: 'user' | 'assistant';
  content: string;
}

export default function ChatBox() {
  const [open, setOpen] = useState(false);
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState('');
  const [loading, setLoading] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    if (scrollRef.current) scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
  }, [messages, open]);

  useEffect(() => {
    if (open && inputRef.current) inputRef.current.focus();
  }, [open]);

  const send = async () => {
    const text = input.trim();
    if (!text || loading) return;
    const userMsg: Message = { role: 'user', content: text };
    const next = [...messages, userMsg];
    setMessages(next);
    setInput('');
    setLoading(true);
    try {
      const res = await api.post<{ reply: string }>('/chat', { messages: next });
      setMessages([...next, { role: 'assistant', content: res.reply }]);
    } catch (err: any) {
      setMessages([...next, { role: 'assistant', content: `Hata: ${err.message}` }]);
    }
    setLoading(false);
  };

  const handleKey = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      send();
    }
  };

  if (!open) {
    return (
      <button
        onClick={() => setOpen(true)}
        className="fixed bottom-5 right-5 z-50 w-11 h-11 bg-info/90 hover:bg-info text-ink-900 rounded-full flex items-center justify-center shadow-lg shadow-info/30 transition-all hover:scale-105"
      >
        <MessageSquare size={18} />
      </button>
    );
  }

  return (
    <div className="fixed bottom-5 right-5 z-50 w-[380px] h-[520px] bg-ink-900 border border-white/10 rounded-lg shadow-2xl shadow-black/50 flex flex-col">
      <div className="flex items-center justify-between px-3 h-9 bg-ink-850 border-b border-white/5 rounded-t-lg flex-shrink-0">
        <span className="text-[10px] tracking-[0.2em] font-bold animate-pulse bg-gradient-to-r from-info via-purple-400 to-pink-400 bg-clip-text text-transparent">NEOooolu LEEeeeynnn</span>
        <button onClick={() => setOpen(false)} className="text-ink-500 hover:text-ink-200 transition-colors">
          <X size={14} />
        </button>
      </div>

      <div ref={scrollRef} className="flex-1 overflow-y-auto p-3 space-y-3 min-h-0">
        {messages.length === 0 && (
          <div className="text-center py-8">
            <p className="text-ink-500 text-[11px]">Trading asistanina sor.</p>
            <p className="text-ink-600 text-[10px] mt-1">Pozisyonlar, trade gecmisi, strateji analizi...</p>
          </div>
        )}
        {messages.map((m, i) => (
          <div key={i} className={`flex ${m.role === 'user' ? 'justify-end' : 'justify-start'}`}>
            <div className={`max-w-[85%] px-3 py-2 text-[11px] leading-[17px] ${
              m.role === 'user'
                ? 'bg-info/15 border border-info/20 text-ink-100 rounded-lg rounded-br-sm'
                : 'bg-ink-800 border border-white/5 text-ink-200 rounded-lg rounded-bl-sm'
            }`}>
              <div className="whitespace-pre-wrap break-words">{m.content}</div>
            </div>
          </div>
        ))}
        {loading && (
          <div className="flex justify-start">
            <div className="bg-ink-800 border border-white/5 px-3 py-2 rounded-lg rounded-bl-sm">
              <Loader2 size={14} className="animate-spin text-ink-400" />
            </div>
          </div>
        )}
      </div>

      <div className="p-2 border-t border-white/5 flex-shrink-0">
        <div className="flex items-end gap-1.5 bg-ink-800 border border-white/5 rounded-lg px-2.5 py-1.5">
          <textarea
            ref={inputRef}
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={handleKey}
            placeholder="Mesaj yaz..."
            rows={1}
            className="flex-1 bg-transparent text-[11px] text-ink-100 placeholder:text-ink-500 resize-none outline-none max-h-[80px] leading-[18px]"
            style={{ minHeight: '18px' }}
          />
          <button
            onClick={send}
            disabled={!input.trim() || loading}
            className="text-info hover:text-info/80 disabled:text-ink-600 transition-colors p-0.5 flex-shrink-0"
          >
            <Send size={14} />
          </button>
        </div>
      </div>
    </div>
  );
}
