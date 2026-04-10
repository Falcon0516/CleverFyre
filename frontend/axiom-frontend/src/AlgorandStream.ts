import { useEffect, useState } from 'react';

export interface PaymentEvent {
  type: string;
  tx_id: string;
  sender: string;
  round: number;
  note: string;
  amount: number;
  ts: number;
}

const mockEvents: PaymentEvent[] = [
  { type: 'PAYMENT', tx_id: 'tx1', sender: 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', round: 28000001, note: 'ok', amount: 5000000, ts: Math.floor(Date.now() / 1000) - 100 },
  { type: 'BLOCK', tx_id: 'tx2', sender: 'ZZZZNNNNQQQQYYYY', round: 28000002, note: 'blocked', amount: 1000000, ts: Math.floor(Date.now() / 1000) - 80 },
  { type: 'WARNING', tx_id: 'tx3', sender: 'MMMMXXXXAAAA', round: 28000003, note: 'warn', amount: 3000000, ts: Math.floor(Date.now() / 1000) - 60 },
  { type: 'QUARANTINE', tx_id: 'tx4', sender: 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', round: 28000004, note: 'quarantine', amount: 8000000, ts: Math.floor(Date.now() / 1000) - 40 },
  { type: 'DRIFT', tx_id: 'tx5', sender: 'ZZZZNNNNQQQQYYYY', round: 28000005, note: 'drift', amount: 500000, ts: Math.floor(Date.now() / 1000) - 20 }
];

export function useAlgorandStream() {
  const [events, setEvents] = useState<PaymentEvent[]>(mockEvents);
  const [isConnected, setIsConnected] = useState(false);

  useEffect(() => {
    const ws = new WebSocket('ws://localhost:8000/ws/events');

    ws.onopen = () => {
      setIsConnected(true);
    };

    ws.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);
        setEvents((prev) => [...prev, data]);
      } catch (e) {
        console.error('Error parsing WS message', e);
      }
    };

    ws.onclose = () => {
      setIsConnected(false);
    };

    return () => {
      ws.close();
    };
  }, []);

  return { events, isConnected, setEvents };
}
