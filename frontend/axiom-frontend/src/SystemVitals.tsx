import { useEffect, useState, useCallback, useRef } from 'react';
import type { PaymentEvent, BackendState, AgentSnapshot } from './AlgorandStream';
import { fetchState } from './AlgorandStream';

interface Props {
  events: PaymentEvent[];
  onApprove?: (escrowId: string) => void;
  onReject?: (escrowId: string) => void;
}

interface VitalData {
  agentsActive: number;
  policiesExpiring: number;
  quarantineQueue: number;
  dnaDriftAlerts: number;
  missionDrift: number;
  consensusPending: { id: string; collected: number; required: number }[];
  dmsCountdowns: { address: string; roundsLeft: number }[];
  agents: Record<string, AgentSnapshot>;
  lastRound: number;
  isLoading: boolean;
  error: string | null;
}

export default function SystemVitals({ events, onApprove, onReject }: Props) {
  const [vitals, setVitals] = useState<VitalData>({
    agentsActive: 0,
    policiesExpiring: 0,
    quarantineQueue: 0,
    dnaDriftAlerts: 0,
    missionDrift: 0,
    consensusPending: [],
    dmsCountdowns: [],
    agents: {},
    lastRound: 0,
    isLoading: true,
    error: null,
  });

  const [resolvedIds, setResolvedIds] = useState<Set<string>>(new Set());
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const handleLocalApprove = (txId: string) => {
    setResolvedIds(prev => new Set([...prev, txId]));
    onApprove?.(txId);
  };

  const handleLocalReject = (txId: string) => {
    setResolvedIds(prev => new Set([...prev, txId]));
    onReject?.(txId);
  };

  const refreshState = useCallback(async () => {
    try {
      const state: BackendState = await fetchState();
      const agents = state.agents || {};
      const agentList = Object.values(agents);

      // Compute vitals from real data
      const expiring = agentList.filter(
        (a) => a.policy_status === 'expiring' || a.policy_status === 'warning'
      ).length;

      const driftAlerts = agentList.filter(
        (a) => a.dna_drift > 0.3
      ).length;

      // Prefer the live WebSocket events array since it includes injected attack events
      // which aren't yet mined into the Algorand blockchain (which state.events reads)
      const uniqueEvents = Array.from(new Map([...(state.events || []), ...events].map(e => [e.tx_id, e])).values());

      const quarantinedEvents = uniqueEvents.filter(
        (e: any) => e.type === 'QUARANTINE' && !resolvedIds.has(e.tx_id)
      );
      const quarantined = quarantinedEvents.length;

      const blocked = uniqueEvents.filter(
        (e: any) => e.type === 'BLOCKED'
      ).length;

      // DMS countdowns from agents with expiring policies
      const dmsCountdowns = agentList
        .filter(a => a.policy_status !== 'active' || a.payments_blocked > 0)
        .slice(0, 5)
        .map(a => ({
          address: a.address,
          roundsLeft: Math.max(0, 360 - (a.payments_made + a.payments_blocked) % 360),
        }));

      setVitals({
        agentsActive: agentList.length,
        policiesExpiring: expiring,
        quarantineQueue: quarantined,
        dnaDriftAlerts: driftAlerts,
        missionDrift: blocked,
        consensusPending: [],
        dmsCountdowns,
        agents,
        lastRound: state.round || 0,
        isLoading: false,
        error: null,
      });
    } catch (e: any) {
      // On backend failure, derive counts purely from local events
      const uniqueSenders = new Set(events.map(ev => ev.sender));
      const quarantined = events.filter(e => e.type === 'QUARANTINE').length;
      const driftCount = events.filter(e => e.type === 'DRIFT').length;
      const blockedCount = events.filter(e => e.type === 'BLOCKED').length;
      const expiredCount = events.filter(e => e.type === 'EXPIRED').length;

      setVitals({
        agentsActive: uniqueSenders.size,
        policiesExpiring: expiredCount,
        quarantineQueue: quarantined,
        dnaDriftAlerts: driftCount,
        missionDrift: blockedCount,
        consensusPending: [],
        dmsCountdowns: [],
        agents: {},
        lastRound: events.length > 0 ? events[events.length - 1].round : 0,
        isLoading: false,
        error: 'Backend offline — showing local event counts',
      });
    }
  }, [events]);

  // Poll backend every 5 seconds
  useEffect(() => {
    refreshState();
    intervalRef.current = setInterval(refreshState, 5000);
    return () => {
      if (intervalRef.current) clearInterval(intervalRef.current);
    };
  }, [refreshState]);

  // Also refresh when events change significantly
  useEffect(() => {
    if (events.length > 0 && events.length % 5 === 0) {
      refreshState();
    }
  }, [events.length, refreshState]);

  const { agentsActive, policiesExpiring, quarantineQueue, dnaDriftAlerts,
    missionDrift, consensusPending, dmsCountdowns } = vitals;

  return (
    <div className="vitals-container">
      <div className="vitals-title">System Vitals</div>

      {vitals.error && (
        <div style={{
          fontSize: 10,
          color: '#FF8C00',
          marginBottom: 12,
          padding: '4px 8px',
          background: 'rgba(255,140,0,0.08)',
          borderRadius: 3,
          fontFamily: 'var(--font-mono)',
        }}>
          ⚠ {vitals.error}
        </div>
      )}

      {/* Core Counts */}
      <div className="vital-row">
        <span className="vital-label">Agents Active</span>
        <span className="vital-value vital-cyan">{agentsActive}</span>
      </div>

      <div className="vital-row">
        <span className="vital-label">Policies Expiring</span>
        <span className={`vital-value ${policiesExpiring > 0 ? 'vital-red' : 'vital-green'}`}>
          {policiesExpiring}
        </span>
      </div>

      <div className="vital-row">
        <span className="vital-label">Quarantine Queue</span>
        <span className={`vital-value ${quarantineQueue > 0 ? 'vital-gold' : 'vital-green'}`}>
          {quarantineQueue}
          {quarantineQueue > 0 && (
            <span style={{
              display: 'inline-block',
              width: 6, height: 6,
              background: '#FFD700',
              borderRadius: '50%',
              marginLeft: 6,
              animation: 'pulse-dot 1s infinite',
            }} />
          )}
        </span>
      </div>

      <div className="vital-row">
        <span className="vital-label">DNA Drift Alerts</span>
        <span className={`vital-value ${dnaDriftAlerts > 0 ? 'vital-purple' : 'vital-green'}`}>
          {dnaDriftAlerts}
        </span>
      </div>

      <div className="vital-row">
        <span className="vital-label">Blocked Events</span>
        <span className={`vital-value ${missionDrift > 0 ? 'vital-red' : 'vital-green'}`}>
          {missionDrift}
        </span>
      </div>

      <div className="vital-row">
        <span className="vital-label">Total Events</span>
        <span className="vital-value vital-cyan">{events.length}</span>
      </div>

      {/* Dead Man's Switch */}
      {dmsCountdowns.length > 0 && (
        <>
          <div className="vital-section-title">Dead Man's Switch</div>
          {dmsCountdowns.map((dms) => (
            <div
              key={dms.address}
              className={`dms-card ${dms.roundsLeft < 120 ? 'critical' : ''}`}
            >
              <div>
                <div className="dms-addr">
                  {dms.address.slice(0, 10)}...
                </div>
              </div>
              <div className={`dms-time ${dms.roundsLeft < 120 ? 'critical' : 'vital-cyan'}`}>
                {dms.roundsLeft} rnds
              </div>
            </div>
          ))}
        </>
      )}

      {/* Quarantine Queue Items */}
      {quarantineQueue > 0 && (
        <>
          <div className="vital-section-title">Quarantine Review</div>
          {events
            .filter(e => e.type === 'QUARANTINE' && !resolvedIds.has(e.tx_id))
            .slice(-3)
            .map((ev, i) => (
              <div key={`q-${ev.tx_id || i}`} className="quarantine-item">
                <div style={{ fontSize: 10, color: 'var(--text-muted)' }}>
                  {ev.sender?.slice(0, 8)}... →{' '}
                  {formatAmount(ev.amount)} ALGO
                </div>
                <div>
                  <button
                    className="btn-sm btn-approve"
                    onClick={() => handleLocalApprove(ev.tx_id)}
                  >
                    ✓
                  </button>
                  <button
                    className="btn-sm btn-reject"
                    onClick={() => handleLocalReject(ev.tx_id)}
                  >
                    ✗
                  </button>
                </div>
              </div>
            ))}
        </>
      )}

      {/* Consensus Pending */}
      {consensusPending.length > 0 && (
        <>
          <div className="vital-section-title">Consensus Pending</div>
          {consensusPending.map((cp) => (
            <div key={cp.id} style={{ marginBottom: 8 }}>
              <div style={{ fontSize: 10, color: 'var(--text-muted)', marginBottom: 4 }}>
                {cp.id.slice(0, 16)}... ({cp.collected}/{cp.required} peers)
              </div>
              <div className="consensus-bar">
                <div
                  className="consensus-fill"
                  style={{ width: `${(cp.collected / cp.required) * 100}%` }}
                />
              </div>
            </div>
          ))}
        </>
      )}
    </div>
  );
}

function formatAmount(amount: number): string {
  if (!amount) return '0';
  const algo = amount / 1_000_000;
  return algo.toFixed(4);
}
