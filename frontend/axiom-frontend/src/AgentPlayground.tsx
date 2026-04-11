import { useState, useEffect, useCallback } from 'react';
import { fetchAgents, spawnAgent, dispatchAgent, fetchState } from './AlgorandStream';
import type { AgentSnapshot, PaymentEvent } from './AlgorandStream';

interface AgentInfo {
  name: string;
  role: string;
  address: string;
  task?: string;
  mock?: boolean;
}

const SCENARIOS = [
  { key: 'market_data', title: '📊 Market Data', desc: 'High-value query (Happy Path)', color: '#00FF7F' },
  { key: 'weather_data', title: '☁️ Weather Query', desc: 'Small payment (Daily Ops)', color: '#00BFFF' },
  { key: 'spam_attack', title: '🔴 Burst Spam', desc: 'Rapid fire (Anomaly Trap)', color: '#FF4444' },
  { key: 'massive_transfer', title: '🟣 Massive Transfer', desc: 'Exceeds threshold (Consensus)', color: '#9B59B6' },
];

export default function AgentPlayground({ events }: { events: PaymentEvent[] }) {
  const [agents, setAgents] = useState<AgentInfo[]>([]);
  const [selectedAgent, setSelectedAgent] = useState<string | null>(null);
  const [nameInput, setNameInput] = useState('');
  const [apiKeyInput, setApiKeyInput] = useState('');
  const [spawning, setSpawning] = useState(false);
  const [dispatching, setDispatching] = useState<string | null>(null);
  const [statusMsg, setStatusMsg] = useState('');
  const [agentSnapshots, setAgentSnapshots] = useState<Record<string, AgentSnapshot>>({});

  // Poll agents from backend
  const refreshAgents = useCallback(async () => {
    try {
      const [agentsRes, stateRes] = await Promise.all([
        fetchAgents(),
        fetchState()
      ]);
      if (agentsRes.agents) {
        setAgents(agentsRes.agents);
        // Auto-select first agent if none selected
        if (!selectedAgent && agentsRes.agents.length > 0) {
          setSelectedAgent(agentsRes.agents[0].name);
        }
      }
      if (stateRes.agents) {
        setAgentSnapshots(stateRes.agents);
      }
    } catch {
      // Backend offline — show empty
    }
  }, [selectedAgent]);

  useEffect(() => {
    refreshAgents();
    const interval = setInterval(refreshAgents, 5000);
    return () => clearInterval(interval);
  }, [refreshAgents]);

  const handleSpawn = useCallback(async () => {
    const name = nameInput.trim();
    if (!name) return;

    setSpawning(true);
    setStatusMsg('');

    try {
      const res = await spawnAgent(name, 'researcher', apiKeyInput.trim() || undefined);
      if (res.status === 'ok' && res.agent) {
        setAgents((prev) => {
          const exists = prev.find((a) => a.name === res.agent.name);
          if (exists) return prev.map((a) => a.name === res.agent.name ? res.agent : a);
          return [...prev, res.agent];
        });
        setSelectedAgent(res.agent.name);
        setNameInput('');
        setApiKeyInput('');
        setStatusMsg(`✓ ${name} spawned`);
      } else {
        setStatusMsg(`✗ Failed: ${res.error || 'unknown error'}`);
      }
    } catch (e: any) {
      setStatusMsg(`✗ Backend offline: ${e.message}`);
    } finally {
      setSpawning(false);
      setTimeout(() => setStatusMsg(''), 3000);
    }
  }, [nameInput, apiKeyInput]);

  const handleDispatch = useCallback(async (scenario: string) => {
    if (!selectedAgent) {
      setStatusMsg('Select an agent first');
      setTimeout(() => setStatusMsg(''), 2000);
      return;
    }

    setDispatching(scenario);
    setStatusMsg('');

    try {
      const res = await dispatchAgent(selectedAgent, scenario);
      if (res.status === 'dispatched') {
        setStatusMsg(`✓ ${scenario} dispatched to ${selectedAgent}`);
      } else {
        setStatusMsg(`✗ ${res.error || 'dispatch failed'}`);
      }
    } catch (e: any) {
      setStatusMsg(`✗ Backend: ${e.message}`);
    } finally {
      setDispatching(null);
      setTimeout(() => setStatusMsg(''), 3000);
    }
  }, [selectedAgent]);

  return (
    <div className="agent-playground">
      <div className="playground-title">Agent Control Center</div>

      {/* Agent Grid */}
      {agents.length > 0 ? (
        <div className="agent-grid">
          {agents.map((agent) => (
            <div
              key={agent.name}
              className={`agent-card ${selectedAgent === agent.name ? 'selected' : ''} ${agent.mock ? 'mock' : ''}`}
              onClick={() => setSelectedAgent(agent.name)}
            >
              <div className="agent-card-name">{agent.name}</div>
              <div className="agent-card-role">{agent.role}</div>
              <div className="agent-card-addr">
                {agent.address?.slice(0, 8)}…
              </div>
            </div>
          ))}
        </div>
      ) : (
        <div className="no-agents-msg">No agents spawned yet</div>
      )}

      {/* Behavioral DNA Profile */}
      {selectedAgent && (
        <div style={{ marginBottom: 15, padding: 12, background: 'rgba(0,0,0,0.3)', borderRadius: 6, border: '1px solid rgba(0,255,127,0.2)' }}>
          <div style={{ fontSize: 10, color: 'var(--text-dim)', marginBottom: 8, fontFamily: 'var(--font-mono)' }}>
            BEHAVIORAL DNA PROFILE
          </div>
          {(() => {
            const addr = agents.find(a => a.name === selectedAgent)?.address || '';
            // Use the pure on-chain backend state
            const snap = agentSnapshots[addr] || {
              address: addr,
              reputation_score: 1000,
              tier: 1,
              dna_drift: 0,
              policy_status: 'active',
              payments_made: 0,
              payments_blocked: 0
            };
            
            return (
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '8px 4px' }}>
                <div>
                  <div style={{ fontSize: 9, color: '#888', textTransform: 'uppercase' }}>Reputation</div>
                  <div style={{ fontSize: 12, color: snap.reputation_score >= 500 ? '#00FF7F' : '#FFD700', fontFamily: 'var(--font-mono)' }}>{snap.reputation_score}/1000</div>
                </div>
                <div>
                  <div style={{ fontSize: 9, color: '#888', textTransform: 'uppercase' }}>Risk Tier</div>
                  <div style={{ fontSize: 12, color: '#00BFFF', fontFamily: 'var(--font-mono)' }}>Tier {snap.tier}</div>
                </div>
                <div>
                  <div style={{ fontSize: 9, color: '#888', textTransform: 'uppercase' }}>Structural Drift</div>
                  <div style={{ fontSize: 12, color: snap.dna_drift > 0.2 ? '#FF4444' : '#00FF7F', fontFamily: 'var(--font-mono)' }}>{(snap.dna_drift * 100).toFixed(1)}%</div>
                </div>
                <div>
                  <div style={{ fontSize: 9, color: '#888', textTransform: 'uppercase' }}>Blocked Ratio</div>
                  <div style={{ fontSize: 12, color: snap.payments_blocked > 0 ? '#FF8C00' : '#888', fontFamily: 'var(--font-mono)' }}>
                    {snap.payments_blocked} / {snap.payments_made + snap.payments_blocked}
                  </div>
                </div>
              </div>
            );
          })()}
        </div>
      )}

      {/* Spawn Form */}
      <div className="spawn-form">
        <input
          type="text"
          placeholder="Agent name"
          value={nameInput}
          onChange={(e) => setNameInput(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && handleSpawn()}
        />
        <input
          type="text"
          placeholder="Groq API Key (optional — mock if empty)"
          value={apiKeyInput}
          onChange={(e) => setApiKeyInput(e.target.value)}
        />
        <button
          className="btn-spawn"
          onClick={handleSpawn}
          disabled={spawning || !nameInput.trim()}
        >
          {spawning ? '◌ Spawning...' : '+ SPAWN AGENT'}
        </button>
      </div>

      {/* Status Message */}
      {statusMsg && (
        <div style={{
          fontSize: 11,
          fontFamily: 'var(--font-mono)',
          color: statusMsg.startsWith('✓') ? '#00FF7F' : statusMsg.startsWith('✗') ? '#FF4444' : 'var(--text-muted)',
          marginBottom: 10,
          padding: '4px 8px',
          background: statusMsg.startsWith('✓')
            ? 'rgba(0,255,127,0.06)'
            : statusMsg.startsWith('✗')
              ? 'rgba(255,68,68,0.06)'
              : 'transparent',
          borderRadius: 3,
        }}>
          {statusMsg}
        </div>
      )}

      {/* Scenario Dispatch Buttons */}
      {selectedAgent && (
        <>
          <div style={{
            fontSize: 10,
            color: 'var(--text-dim)',
            marginBottom: 6,
            fontFamily: 'var(--font-mono)',
            letterSpacing: 0.5,
          }}>
            DISPATCH → {selectedAgent}
          </div>
          <div className="scenario-grid">
            {SCENARIOS.map((s) => (
              <button
                key={s.key}
                className="scenario-btn"
                onClick={() => handleDispatch(s.key)}
                disabled={dispatching === s.key}
                style={{ opacity: dispatching === s.key ? 0.5 : 1 }}
              >
                <span className="scenario-title">{s.title}</span>
                <span className="scenario-desc">{s.desc}</span>
              </button>
            ))}
          </div>
        </>
      )}
    </div>
  );
}
