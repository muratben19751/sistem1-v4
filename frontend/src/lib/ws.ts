import { getStaticAuthToken } from './auth-token';

type MessageHandler = (data: any) => void;

function notifyAuthRequired() {
  window.dispatchEvent(new CustomEvent('sistem1:auth-required'));
}

class WsClient {
  private ws: WebSocket | null = null;
  private handlers = new Map<string, Set<MessageHandler>>();
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  private pingTimer: ReturnType<typeof setInterval> | null = null;
  private reconnectAttempt = 0;
  private intentionalClose = false;
  latency = 0;

  connect() {
    if (this.ws && (this.ws.readyState === WebSocket.OPEN || this.ws.readyState === WebSocket.CONNECTING)) return;
    this.intentionalClose = false;

    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const url = new URL(`${protocol}//${window.location.host}/ws`);
    const token = getStaticAuthToken();
    if (token) url.searchParams.set('token', token);
    this.ws = new WebSocket(url);

    this.ws.onmessage = (event) => {
      try {
        const msg = JSON.parse(event.data);
        if (msg.type === 'pong' && msg.ts) {
          this.latency = Date.now() - msg.ts;
          const handlers = this.handlers.get('latency');
          if (handlers) for (const h of handlers) h(this.latency);
          return;
        }
        const handlers = this.handlers.get(msg.type);
        if (handlers) {
          for (const handler of handlers) handler(msg.data);
        }
      } catch {}
    };

    this.ws.onopen = () => {
      this.reconnectAttempt = 0;
      this.startPing();
    };

    this.ws.onerror = () => {};

    this.ws.onclose = (event) => {
      this.stopPing();
      if (this.intentionalClose) return;
      if (event.code === 1008) {
        notifyAuthRequired();
        return;
      }
      const delay = Math.min(3000 * Math.pow(2, this.reconnectAttempt), 30000);
      this.reconnectAttempt++;
      this.reconnectTimer = setTimeout(() => this.connect(), delay);
    };
  }

  disconnect() {
    this.intentionalClose = true;
    this.stopPing();
    if (this.reconnectTimer) clearTimeout(this.reconnectTimer);
    this.reconnectTimer = null;
    this.ws?.close();
    this.ws = null;
  }

  send(data: unknown) {
    if (this.ws?.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify(data));
    }
  }

  private startPing() {
    this.stopPing();
    this.pingTimer = setInterval(() => {
      this.send({ type: 'ping', ts: Date.now() });
    }, 5000);
  }

  private stopPing() {
    if (this.pingTimer) { clearInterval(this.pingTimer); this.pingTimer = null; }
  }

  on(event: string, handler: MessageHandler) {
    if (!this.handlers.has(event)) this.handlers.set(event, new Set());
    this.handlers.get(event)!.add(handler);
    return () => { this.handlers.get(event)?.delete(handler); };
  }
}

export const wsClient = new WsClient();
