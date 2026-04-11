import { useState, useCallback } from 'react';
import { useAlgorandStream, fetchState } from './AlgorandStream';
import type { PaymentEvent } from './AlgorandStream';
import NetworkGraph from './NetworkGraph';
import AxiomTerminal from './AxiomTerminal';
import SystemVitals from './SystemVitals';
import TemporalScrubber from './TemporalScrubber';
import IntentModal from './IntentModal';
import AgentPlayground from './AgentPlayground';

export default function App() {
  const { events, isConnected, currentRound } = useAlgorandStream();
  const [historicalRound, setHistoricalRound] = useState<number | null>(null);
  const [selectedEvent, setSelectedEvent] = useState<PaymentEvent | null>(null);
  const [historicalEvents, setHistoricalEvents] = useState<PaymentEvent[]>([]);

  // Determine which events to display
  const displayEvents = historicalRound && historicalRound > 0
    ? historicalEvents
    : events;

  // Determine the round to display
  const displayRound = historicalRound && historicalRound > 0
    ? historicalRound
    : currentRound || (events.length > 0 ? events[events.length - 1].round : 0);

  // Min/max round for scrubber
  const minRound = events.length > 0 ? events[0].round : 0;
  const maxRound = currentRound || (events.length > 0 ? events[events.length - 1].round : 0);

  // Handle temporal scrubber round change
  const handleRoundChange = useCallback(async (round: number) => {
    if (round >= maxRound - 1 || round === 0) {
      // Snap to live mode
      setHistoricalRound(null);
      setHistoricalEvents([]);
      return;
    }

    setHistoricalRound(round);

    // Fetch historical state from backend
    try {
      const state = await fetchState(round);
      if (state.events) {
        setHistoricalEvents(state.events);
      }
    } catch (e) {
      console.error('[AXIOM] Temporal fetch failed:', e);
    }
  }, [maxRound]);

  const handleNodeClick = useCallback((addr: string) => {
    console.log('[AXIOM] Node clicked:', addr);
  }, []);

  const handleEdgeClick = useCallback((event: PaymentEvent) => {
    setSelectedEvent(event);
  }, []);

  const handleEventClick = useCallback((event: PaymentEvent) => {
    setSelectedEvent(event);
  }, []);

  const handleApprove = useCallback((escrowId: string) => {
    console.log('[AXIOM] Approve quarantine:', escrowId);
    // TODO: POST to backend /api/v1/approve
  }, []);

  const handleReject = useCallback((escrowId: string) => {
    console.log('[AXIOM] Reject quarantine:', escrowId);
    // TODO: POST to backend /api/v1/reject
  }, []);

  return (
    <div className="axiom-app">
      {/* Header */}
      <header className="app-header">
        <div className="header-brand">AXIOM</div>
        <div className="header-round">
          {displayRound > 0
            ? `Block ${displayRound.toLocaleString()}`
            : 'Awaiting blocks…'}
        </div>
        <div className={`header-status ${isConnected ? 'connected' : 'disconnected'}`}>
          <span className={`status-dot ${isConnected ? '' : 'off'}`} />
          {isConnected ? 'STREAMING' : 'OFFLINE'}
        </div>
      </header>

      {/* Main 3-Panel Layout */}
      <div className="main-layout">
        {/* LEFT — Network Graph */}
        <div className="panel left-panel">
          <NetworkGraph
            events={displayEvents}
            onNodeClick={handleNodeClick}
            onEdgeClick={handleEdgeClick}
            historicalRound={historicalRound}
          />
        </div>

        {/* CENTER — Live Feed Terminal */}
        <div className="panel center-panel">
          <AxiomTerminal
            events={displayEvents}
            onEventClick={handleEventClick}
          />
        </div>

        {/* RIGHT — System Vitals + Agent Playground */}
        <div className="panel right-panel">
          <SystemVitals
            events={events}
            onApprove={handleApprove}
            onReject={handleReject}
          />
          <AgentPlayground events={events} />
        </div>
      </div>

      {/* Bottom — Temporal Scrubber */}
      <div className="bottom-panel">
        <TemporalScrubber
          currentRound={displayRound}
          minRound={minRound}
          maxRound={maxRound}
          onRoundChange={handleRoundChange}
        />
      </div>

      {/* Intent Modal */}
      {selectedEvent && (
        <IntentModal
          event={selectedEvent}
          onClose={() => setSelectedEvent(null)}
        />
      )}
    </div>
  );
}
