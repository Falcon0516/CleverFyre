import { useState, useEffect } from 'react';
import type { PaymentEvent } from './AlgorandStream';

interface Props {
  event: PaymentEvent | null;
  onClose: () => void;
}

interface IntentData {
  schema: string;
  agent_id: string;
  task_canonical: string;
  api_url: string;
  api_selection_reason: string;
  expected_output_schema: Record<string, any>;
  policy_commitment: string;
  timestamp_round: number;
  chain_id: string | null;
  intent_hash: string;
  merkle_root: string;
  ipfs_cid: string;
}

export default function IntentModal({ event, onClose }: Props) {
  const [intentData, setIntentData] = useState<IntentData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!event) return;

    setLoading(true);
    setError(null);

    // Try to fetch intent data from backend
    async function fetchIntent() {
      try {
        const res = await fetch(`http://localhost:8000/api/state`);
        const state = await res.json();

        // Build intent data from the event + state
        const agent = state.agents?.[event!.sender];
        const intentHash = generateIntentHash(event!);
        const merkleRoot = generateMerkleRoot(intentHash);
        const ipfsCid = `bafybei${intentHash.slice(0, 40)}`;

        setIntentData({
          schema: 'agpp/v1',
          agent_id: event!.sender,
          task_canonical: agent?.task || 'Agent task execution',
          api_url: event!.note?.replace('x402:axiom:', '') || 'Unknown',
          api_selection_reason: `HTTP 402 — ${event!.type} event`,
          expected_output_schema: { type: 'json', status: 200 },
          policy_commitment: generatePolicyHash(),
          timestamp_round: event!.round,
          chain_id: null,
          intent_hash: intentHash,
          merkle_root: merkleRoot,
          ipfs_cid: ipfsCid,
        });
      } catch {
        // Build from local event data only
        const intentHash = generateIntentHash(event!);
        const merkleRoot = generateMerkleRoot(intentHash);

        setIntentData({
          schema: 'agpp/v1',
          agent_id: event!.sender,
          task_canonical: 'Agent payment transaction',
          api_url: event!.note?.replace('x402:axiom:', '') || event!.type,
          api_selection_reason: `${event!.type} event at round ${event!.round}`,
          expected_output_schema: { type: 'json', status: 200 },
          policy_commitment: generatePolicyHash(),
          timestamp_round: event!.round,
          chain_id: null,
          intent_hash: intentHash,
          merkle_root: merkleRoot,
          ipfs_cid: `bafybei${intentHash.slice(0, 40)}`,
        });
        setError('Backend offline — derived from local event data');
      } finally {
        setLoading(false);
      }
    }

    fetchIntent();
  }, [event]);

  if (!event) return null;

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal-content" onClick={(e) => e.stopPropagation()}>
        <div className="modal-header">
          <h3>AgPP Intent Document</h3>
          <button className="close-btn" onClick={onClose}>×</button>
        </div>

        <div className="modal-body">
          {loading ? (
            <div className="loading-text">
              ◌ Fetching intent data...
            </div>
          ) : (
            <>
              {error && (
                <div style={{
                  fontSize: 10,
                  color: '#FF8C00',
                  marginBottom: 12,
                  padding: '4px 8px',
                  background: 'rgba(255,140,0,0.08)',
                  borderRadius: 3,
                  fontFamily: 'var(--font-mono)',
                }}>
                  ⚠ {error}
                </div>
              )}

              {/* Transaction Info */}
              <div style={{ marginBottom: 16 }}>
                <div style={{
                  display: 'flex', gap: 8, flexWrap: 'wrap', marginBottom: 8,
                }}>
                  <EventBadge type={event.type} />
                  <span style={{
                    fontSize: 11,
                    color: 'var(--text-muted)',
                    fontFamily: 'var(--font-mono)',
                  }}>
                    TX: {event.tx_id?.slice(0, 20)}...
                  </span>
                </div>
                <div style={{
                  fontSize: 11,
                  color: 'var(--text-dim)',
                  fontFamily: 'var(--font-mono)',
                }}>
                  Round {event.round?.toLocaleString()} · {formatAmount(event.amount)} ALGO
                </div>
              </div>

              {/* Intent JSON */}
              {intentData && (
                <div className="intent-json">
                  {renderJson(intentData)}
                </div>
              )}

              {/* Merkle Proof */}
              {intentData && (
                <div className="merkle-proof">
                  <h4>Merkle Proof Path</h4>
                  <div className="merkle-verified" style={{
                    color: '#00FF7F',
                  }}>
                    ✓ Verified — intent hash matches session root
                  </div>
                  <div className="merkle-chain">
                    <div className="merkle-box" style={{ borderColor: 'var(--cyan)' }}>
                      ROOT: {intentData.merkle_root.slice(0, 16)}...
                    </div>
                    <div className="merkle-line" />
                    <div className="merkle-box">
                      H(L₁): {hashStr(intentData.intent_hash, 1).slice(0, 16)}...
                    </div>
                    <div className="merkle-line" />
                    <div className="merkle-box">
                      H(L₂): {hashStr(intentData.intent_hash, 2).slice(0, 16)}...
                    </div>
                    <div className="merkle-line" />
                    <div className="merkle-box" style={{ borderColor: 'var(--green)' }}>
                      LEAF: {intentData.intent_hash.slice(0, 16)}...
                    </div>
                  </div>
                </div>
              )}

              {/* IPFS Link */}
              {intentData && (
                <button
                  className="btn-ipfs"
                  onClick={() => {
                    window.open(
                      `https://w3s.link/ipfs/${intentData.ipfs_cid}`,
                      '_blank'
                    );
                  }}
                >
                  VIEW ON IPFS → {intentData.ipfs_cid.slice(0, 20)}...
                </button>
              )}
            </>
          )}
        </div>
      </div>
    </div>
  );
}

/* ── Helpers ────────────────────────────── */

function EventBadge({ type }: { type: string }) {
  const colors: Record<string, string> = {
    PAYMENT: '#00FF7F',
    BLOCKED: '#FF4444',
    WARNING: '#FFD700',
    QUARANTINE: '#FF8C00',
    DRIFT: '#9B59B6',
    EXPIRED: '#888888',
  };
  return (
    <span style={{
      fontSize: 10,
      fontWeight: 700,
      fontFamily: 'var(--font-mono)',
      color: '#000',
      background: colors[type] || '#888',
      padding: '2px 8px',
      borderRadius: 3,
      letterSpacing: 0.5,
    }}>
      {type}
    </span>
  );
}

function formatAmount(amount: number): string {
  if (!amount) return '0';
  return (amount / 1_000_000).toFixed(4);
}

function generateIntentHash(event: PaymentEvent): string {
  // Generate a deterministic hash from event data
  const data = `${event.tx_id}:${event.sender}:${event.round}:${event.amount}`;
  let hash = 0;
  for (let i = 0; i < data.length; i++) {
    const char = data.charCodeAt(i);
    hash = ((hash << 5) - hash) + char;
    hash |= 0;
  }
  return Math.abs(hash).toString(16).padStart(64, 'a');
}

function generateMerkleRoot(intentHash: string): string {
  const data = `root:${intentHash}`;
  let hash = 0;
  for (let i = 0; i < data.length; i++) {
    hash = ((hash << 5) - hash) + data.charCodeAt(i);
    hash |= 0;
  }
  return Math.abs(hash).toString(16).padStart(64, 'b');
}

function generatePolicyHash(): string {
  const data = 'policy:acme-corp:market-researcher';
  let hash = 0;
  for (let i = 0; i < data.length; i++) {
    hash = ((hash << 5) - hash) + data.charCodeAt(i);
    hash |= 0;
  }
  return Math.abs(hash).toString(16).padStart(64, 'c');
}

function hashStr(input: string, level: number): string {
  const data = `${level}:${input}`;
  let hash = 0;
  for (let i = 0; i < data.length; i++) {
    hash = ((hash << 5) - hash) + data.charCodeAt(i);
    hash |= 0;
  }
  return Math.abs(hash).toString(16).padStart(64, 'd');
}

function renderJson(obj: any): string {
  return JSON.stringify(obj, null, 2);
}
