import React, { useEffect, useRef } from 'react';
import type { PaymentEvent } from './AlgorandStream';

interface AxiomTerminalProps {
  events: PaymentEvent[];
  onEventClick: (event: PaymentEvent) => void;
}

export const AxiomTerminal: React.FC<AxiomTerminalProps> = ({ events, onEventClick }) => {
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [events]);

  return (
    <div className="terminal-container">
      <div className="terminal-header" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <div>
          <span>Live Feed</span>
          <span className="event-count" style={{ marginLeft: '1rem' }}>{events.length} Events</span>
        </div>
        <button
          onClick={async () => {
            try {
              await fetch('http://localhost:8000/api/v1/trigger-agent', { method: 'POST' });
            } catch (e) {
              console.error('Trigger failed', e);
            }
          }}
          style={{
            background: 'var(--color-primary)',
            color: '#fff',
            border: 'none',
            padding: '4px 12px',
            borderRadius: '4px',
            cursor: 'pointer',
            fontSize: '0.8rem',
            fontWeight: 'bold'
          }}
        >
          Simulate Payment
        </button>
      </div>

      <div className="terminal-log">
        {events.slice(-200).map((ev, i) => {
          const time = new Date(ev.ts ? ev.ts * 1000 : Date.now()).toLocaleTimeString();
          const senderShort = ev.sender.substring(0, 8);
          let typeColor = 'var(--color-primary)';

          if (ev.type === 'BLOCK') typeColor = 'var(--color-danger)';
          else if (ev.type === 'WARNING' || ev.type === 'WARN') typeColor = 'var(--color-warning)';
          else if (ev.type === 'QUARANTINE') typeColor = 'var(--color-warning)';
          else if (ev.type === 'DRIFT') typeColor = 'var(--color-purple)';
          else if (ev.type === 'EXPIRED') typeColor = '#94a3b8';

          return (
            <div
              key={i}
              className="terminal-line"
              style={{ borderLeftColor: typeColor }}
              onClick={() => onEventClick(ev)}
            >
              <span className="terminal-time">{time}</span>
              <span className="terminal-type" style={{ color: typeColor }}>
                {ev.type}
              </span>
              <span className="terminal-sender">{senderShort}</span>
              <span style={{ color: 'var(--text-muted)' }}>→</span>
              <span>CORE</span>
              <span className="terminal-amount" style={{ color: typeColor }}>
                {ev.amount ? (ev.amount / 1_000_000).toFixed(2) : 0} ALGO
              </span>
            </div>
          );
        })}
        <div ref={bottomRef} />
      </div>
    </div>
  );
};
