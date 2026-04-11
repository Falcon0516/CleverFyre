import { useEffect, useState, useRef, useCallback } from 'react';

export interface PaymentEvent {
  type: string;
  tx_id: string;
  sender: string;
  receiver?: string;
  round: number;
  note: string;
  amount: number;
  ts: number;
}

export interface BackendState {
  round: number;
  agents: Record<string, AgentSnapshot>;
  events: PaymentEvent[];
  error?: string;
}

export interface AgentSnapshot {
  address: string;
  reputation_score: number;
  tier: number;
  dna_drift: number;
  policy_status: string;
  payments_made: number;
  payments_blocked: number;
}

const API_BASE = 'http://localhost:8000';
const WS_URL = 'ws://localhost:8000/ws/events';

export function useAlgorandStream() {
  const [events, setEvents] = useState<PaymentEvent[]>([]);
  const [isConnected, setIsConnected] = useState(false);
  const [currentRound, setCurrentRound] = useState(0);
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const connect = useCallback(() => {
    if (wsRef.current?.readyState === WebSocket.OPEN) return;

    const ws = new WebSocket(WS_URL);
    wsRef.current = ws;

    ws.onopen = () => {
      setIsConnected(true);
      console.log('[AXIOM] WebSocket connected');
    };

    ws.onmessage = (event) => {
      try {
        const data: PaymentEvent = JSON.parse(event.data);
        if (data.ts === 0) data.ts = Math.floor(Date.now() / 1000);
        if (!data.tx_id) data.tx_id = `ws-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
        setEvents((prev) => {
          const next = [...prev, data].slice(-500);
          return next;
        });
        if (data.round > 0) {
          setCurrentRound(data.round);
        }
      } catch (e) {
        console.error('[AXIOM] WS parse error', e);
      }
    };

    ws.onclose = () => {
      setIsConnected(false);
      console.log('[AXIOM] WebSocket disconnected — reconnecting in 3s');
      reconnectTimerRef.current = setTimeout(connect, 3000);
    };

    ws.onerror = () => {
      ws.close();
    };
  }, []);

  useEffect(() => {
    connect();
    return () => {
      wsRef.current?.close();
      if (reconnectTimerRef.current) clearTimeout(reconnectTimerRef.current);
    };
  }, [connect]);

  return { events, isConnected, currentRound, setEvents };
}

export async function fetchState(round?: number): Promise<BackendState> {
  const url = round !== undefined && round > 0
    ? `${API_BASE}/api/state?round=${round}`
    : `${API_BASE}/api/state`;
  const res = await fetch(url);
  return res.json();
}

export async function fetchAgents(): Promise<{ status: string; agents: any[] }> {
  const res = await fetch(`${API_BASE}/api/v1/agents`);
  return res.json();
}

export async function spawnAgent(name: string, role: string, apiKey?: string) {
  const res = await fetch(`${API_BASE}/api/v1/agents/spawn`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ name, role, groq_api_key: apiKey || null }),
  });
  return res.json();
}

export async function dispatchAgent(agentName: string, scenario: string) {
  const res = await fetch(`${API_BASE}/api/v1/agents/dispatch`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ agent_name: agentName, scenario }),
  });
  return res.json();
}

export async function injectEvent(event: Partial<PaymentEvent>) {
  const res = await fetch(`${API_BASE}/api/v1/inject-event`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(event),
  });
  return res.json();
}

export async function triggerAgent() {
  const res = await fetch(`${API_BASE}/api/v1/trigger-agent`, { method: 'POST' });
  return res.json();
}
