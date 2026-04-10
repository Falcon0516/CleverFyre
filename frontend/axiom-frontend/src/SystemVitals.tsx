import React, { useEffect, useState } from 'react';

interface SystemVitalsProps {
  onApprove: (escrowId: string) => void;
  onReject: (escrowId: string) => void;
}

export const SystemVitals: React.FC<SystemVitalsProps> = ({ onApprove, onReject }) => {
  const [agents, setAgents] = useState(0);
  const [expiring, setExpiring] = useState(0);
  const [quarantineQueue, setQuarantineQueue] = useState(0);
  const [dnaAlerts, setDnaAlerts] = useState(0);
  const [missionDrift, setMissionDrift] = useState(0);
  const [dmsSeconds, setDmsSeconds] = useState(131); // 02:11

  useEffect(() => {
    const fetchState = async () => {
      try {
        const res = await fetch('http://localhost:8000/api/state?round=0');
        const data = await res.json();
        setAgents(Object.keys(data.agents || {}).length);
      } catch {
        setAgents(3);
        setExpiring(1);
        setQuarantineQueue(1);
        setDnaAlerts(1);
        setMissionDrift(0);
      }
    };

    fetchState();
    const interval = setInterval(fetchState, 5000);
    return () => clearInterval(interval);
  }, []);

  useEffect(() => {
    const timer = setInterval(() => {
      setDmsSeconds(prev => (prev > 0 ? prev - 1 : 0));
    }, 1000);
    return () => clearInterval(timer);
  }, []);

  const dmsMin = Math.floor(dmsSeconds / 60).toString().padStart(2, '0');
  const dmsSec = (dmsSeconds % 60).toString().padStart(2, '0');
  const isDmsCritical = dmsSeconds < 60;

  return (
    <div className="vitals-container">
      <h2>System Vitals</h2>
      
      <div className="vital-row">
        <div className="vital-item">
          <span className="vital-label">Active Agents</span>
          <span className="vital-value text-cyan">{agents || '--'}</span>
        </div>
      </div>
      
      <div className="vital-row">
        <div className="vital-item">
          <span className="vital-label">Policies Expiring</span>
          <span>
            <span className={`vital-value ${expiring > 0 ? 'text-red' : ''}`}>{expiring || '--'}</span>
            {expiring > 0 && <span className="blink-dot"></span>}
          </span>
        </div>
      </div>
      
      <div className="vital-row">
        <div className="vital-item">
          <span className="vital-label">Quarantine Queue</span>
          <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
            <span className="vital-value text-gold">{quarantineQueue || '--'}</span>
            {quarantineQueue > 0 && <button className="btn-review interactive" onClick={() => onApprove('mock-escrow')}>REVIEW</button>}
          </div>
        </div>
      </div>
      
      <div className="vital-row">
        <div className="vital-item">
          <span className="vital-label">DNA Drift Alerts</span>
          <span className="vital-value text-purple">{dnaAlerts || '--'}</span>
        </div>
      </div>
      
      <div className="vital-row">
        <div className="vital-item">
          <span className="vital-label">Mission Drift</span>
          <span className="vital-value">{missionDrift || '--'}</span>
        </div>
      </div>

      <div className="vital-row">
        <span className="vital-label" style={{ marginBottom: '8px' }}>Consensus Pending (tx_8f...)</span>
        <div className="vital-item">
          <span style={{ fontSize: '13px', fontWeight: '600' }}>2/3 Approvals</span>
          <div>
            <button className="btn-approve interactive" onClick={() => onApprove('1')}>Approve</button>
            <button className="btn-reject interactive" onClick={() => onReject('1')}>Reject</button>
          </div>
        </div>
        <div className="consensus-bar-bg">
          <div className="consensus-bar-fill" style={{ width: '66.6%' }}></div>
        </div>
      </div>
      
      <div className="vital-row" style={{borderBottom: 'none'}}>
        <span className="vital-label">Dead Man Switch</span>
        <div className={`dms-box ${isDmsCritical ? 'dms-alert' : ''}`}>
          <div style={{display: 'flex', flexDirection: 'column'}}>
            <span style={{fontSize: '14px', fontWeight: '600', color: isDmsCritical ? 'var(--color-danger)' : 'var(--text-main)'}}>Agent 1</span>
            <span style={{fontSize: '12px', color: 'var(--text-muted)', fontFamily: 'var(--font-mono)'}}>0XF8A...99</span>
          </div>
          <span className={`vital-value ${isDmsCritical ? 'dms-text-alert' : ''}`} style={{ fontFamily: 'var(--font-mono)'}}>{dmsMin}:{dmsSec}</span>
        </div>
      </div>
    </div>
  );
};
