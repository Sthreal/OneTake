type MiniClawWsHandler<T = unknown> = (event: T) => void;

export interface MiniClawWsEvent {
  type: string;
  [key: string]: unknown;
}

export function buildMiniClawWebSocketUrl(
  origin = window.location.origin,
): string {
  const url = new URL("/miniclaw-ws", origin);
  url.protocol = url.protocol === "https:" ? "wss:" : "ws:";
  return url.toString();
}

export class MiniClawWsClient {
  private socket: WebSocket | null = null;
  private handlers = new Map<string, Set<MiniClawWsHandler>>();
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  private reconnectDelay = 1000;

  connect(): void {
    if (
      this.socket?.readyState === WebSocket.OPEN ||
      this.socket?.readyState === WebSocket.CONNECTING
    ) {
      return;
    }

    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }

    const socket = new WebSocket(buildMiniClawWebSocketUrl());
    this.socket = socket;

    socket.onopen = () => {
      if (this.socket !== socket) return;
      this.reconnectDelay = 1000;
      this.emit("connected", {});
    };

    socket.onmessage = (message) => {
      if (this.socket !== socket) return;
      try {
        const event = JSON.parse(String(message.data)) as MiniClawWsEvent;
        if (event && typeof event.type === "string")
          this.emit(event.type, event);
      } catch {
        // Ignore malformed events; the HTTP client remains authoritative.
      }
    };

    socket.onclose = (event) => {
      if (this.socket !== socket) return;
      this.socket = null;
      this.emit("disconnected", { code: event.code, reason: event.reason });
      if (event.code !== 1008 && event.code !== 4001) this.scheduleReconnect();
    };

    socket.onerror = () => {
      if (this.socket !== socket) return;
      socket.close();
    };
  }

  disconnect(): void {
    if (this.reconnectTimer) clearTimeout(this.reconnectTimer);
    this.reconnectTimer = null;
    const socket = this.socket;
    this.socket = null;
    socket?.close();
  }

  isConnected(): boolean {
    return this.socket?.readyState === WebSocket.OPEN;
  }

  send(data: object): boolean {
    if (this.socket?.readyState !== WebSocket.OPEN) return false;
    this.socket.send(JSON.stringify(data));
    return true;
  }

  on<T = MiniClawWsEvent>(
    type: string,
    handler: MiniClawWsHandler<T>,
  ): () => void {
    if (!this.handlers.has(type)) this.handlers.set(type, new Set());
    const typedHandler = handler as MiniClawWsHandler;
    this.handlers.get(type)!.add(typedHandler);
    return () => this.handlers.get(type)?.delete(typedHandler);
  }

  private emit(type: string, event: unknown): void {
    this.handlers.get(type)?.forEach((handler) => handler(event));
  }

  private scheduleReconnect(): void {
    if (this.reconnectTimer) return;
    this.reconnectTimer = setTimeout(() => {
      this.reconnectTimer = null;
      this.reconnectDelay = Math.min(this.reconnectDelay * 2, 30000);
      this.connect();
    }, this.reconnectDelay);
  }
}

export const miniclawWs = new MiniClawWsClient();
