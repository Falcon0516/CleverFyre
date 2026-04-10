import React, { useEffect, useState } from 'react';

interface IntentModalProps {
  txId: string;
  onClose: () => void;
}

export const IntentModal: React.FC<IntentModalProps> = ({ txId, onClose }) => {
  const [intentData, setIntentData] = useState<any>(null);

  useEffect(() => {
    setTimeout(() => {
      setIntentData({
        schema: "agpp/v1",
        agent_id: "ABCDEFGHIJKLMNOPQRSTUVWXYZ",
        task_canonical: "Gather Q3 2026 semiconductor supply chain disruption data",
        api_url: "https://financialmodelingprep.com/api/v3/quote/AAPL",
        api_selection_reason: "auto-selected via semantic routing",
        expected_output_schema: { status: "string", responseCode: 200 },
        policy_commitment: true,
        timestamp_round: 28041337
      });
    }, 300); // Speed up mock retrieval to feel snappy
  }, [txId]);

  const syntaxHighlight = (json: string) => {
    json = json.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
    return json.replace(/("(\\u[a-zA-Z0-9]{4}|\\[^u]|[^\\"])*"(\s*:)?|\b(true|false|null)\b|-?\d+(?:\.\d*)?(?:[eE][+\-]?\d+)?)/g, function (match) {
        let cls = 'json-number';
        if (/^"/.test(match)) {
            if (/:$/.test(match)) {
                cls = 'json-key';
            } else {
                cls = 'json-string';
            }
        } else if (/true|false/.test(match)) {
            cls = 'json-boolean';
        }
        return '<span class="' + cls + '">' + match + '</span>';
    });
  };

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal-content" onClick={(e) => e.stopPropagation()}>
        <div className="modal-header">
          <h3>AgPP Intent Record</h3>
          <button className="close-btn interactive" onClick={onClose}>&times;</button>
        </div>
        <div className="modal-body">
          {intentData ? (
            <pre 
              className="intent-json"
              dangerouslySetInnerHTML={{ __html: syntaxHighlight(JSON.stringify(intentData, null, 2)) }}
            />
          ) : (
            <div style={{color: 'var(--text-muted)'}}>Fetching records from IPFS...</div>
          )}
          
          <div className="merkle-proof">
            <h4 style={{color: 'var(--text-main)', marginBottom: '12px', marginTop: 0, fontSize: '15px'}}>Merkle Verification</h4>
            <div style={{fontSize: '14px', fontWeight: '500'}}>Status: <span style={{color: 'var(--color-success)', fontWeight: '700'}}>VERIFIED ON ALGORAND</span></div>
            
            <div className="merkle-chain" style={{alignItems: 'flex-start'}}>
              <div className="merkle-box">TX_HASH: {txId.substring(0,16)}...</div>
              <div className="merkle-line" style={{marginLeft: '24px'}}></div>
              <div className="merkle-box">LEAF: a8b3...9f21</div>
              <div className="merkle-line" style={{marginLeft: '24px'}}></div>
              <div className="merkle-box">ROOT: e9d5...4c00</div>
            </div>
          </div>
          
          <button className="btn-ipfs interactive" onClick={() => window.open('https://ipfs.io', '_blank')}>View Verification Data</button>
        </div>
      </div>
    </div>
  );
};
