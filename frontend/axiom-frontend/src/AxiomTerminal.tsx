import { useEffect, useRef } from 'react';
import type { PaymentEvent } from './AlgorandStream';
import { injectEvent } from './AlgorandStream';

interface Props {
  events: PaymentEvent[];
  onEventClick?: (event: PaymentEvent) => void;
}

const TYPE_COLORS: Record<string, string> = {
  PAYMENT: '#00FF7F',
  BLOCKED: '#FF4444',
  WARNING: '#FFD700',
  QUARANTINE: '#FF8C00',
  DRIFT: '#9B59B6',
  EXPIRED: '#888888',
};

const TYPE_LABELS: Record<string, string> = {
  PAYMENT: 'PAY',
  BLOCKED: 'BLOCK',
  WARNING: 'WARN',
  QUARANTINE: 'QUAR',
  DRIFT: 'DRIFT',
  EXPIRED: 'EXPD',
};

function formatTime(ts: number): string {
  if (!ts) return '--:--:--';
  const d = new Date(ts * 1000);
  return d.toLocaleTimeString('en-US', { hour12: false, hour: '2-digit', minute: '2-digit', second: '2-digit' });
}

function formatAddr(addr: string): string {
  if (!addr) return '--------';
  if (addr.length <= 10) return addr;
  return addr.slice(0, 8) + '…';
}

function formatAmount(amount: number): string {
  if (!amount) return '0';
  const algo = amount / 1_000_000;
  if (algo >= 1) return algo.toFixed(2);
  if (algo >= 0.01) return algo.toFixed(4);
  return algo.toFixed(6);
}

export default function AxiomTerminal({ events, onEventClick }: Props) {
  const logRef = useRef<HTMLDivElement>(null);

  // Auto-scroll to bottom on new events
  useEffect(() => {
    if (logRef.current) {
      logRef.current.scrollTop = logRef.current.scrollHeight;
    }
  }, [events.length]);

  const visibleEvents = events.slice(-200);

  return (
    <div className="terminal-container">
      <div className="terminal-header">
        <div style={{ display: 'flex', alignItems: 'center' }}>
          <span className="terminal-header-title">Live Feed</span>
          <span className="event-count">{events.length}</span>
        </div>
      </div>

      <div className="terminal-log" ref={logRef}>
        {visibleEvents.length === 0 ? (
          <div className="terminal-empty">
            <span>○ No events received</span>
            <span style={{ fontSize: 10, opacity: 0.5 }}>
              Waiting for WebSocket stream...
            </span>
          </div>
        ) : (
          visibleEvents.map((ev, i) => {
            const typeColor = TYPE_COLORS[ev.type] || '#888';
            const typeLabel = TYPE_LABELS[ev.type] || ev.type;

            return (
              <div
                key={ev.tx_id || `evt-${i}`}
                className="terminal-line"
                style={{ borderLeftColor: typeColor }}
                onClick={() => onEventClick?.(ev)}
              >
                <span className="terminal-time">{formatTime(ev.ts)}</span>
                <span className="terminal-type" style={{ color: typeColor }}>
                  [{typeLabel}]
                </span>
                <span className="terminal-sender">{formatAddr(ev.sender)}</span>
                <span className="terminal-arrow">→</span>
                <span className="terminal-receiver">
                  {ev.receiver ? formatAddr(ev.receiver) : 'ESCROW'}
                </span>
                <span className="terminal-amount" style={{ color: typeColor }}>
                  {formatAmount(ev.amount)} ALGO
                </span>
              </div>
            );
          })
        )}
      </div>
    </div>
  );
}
