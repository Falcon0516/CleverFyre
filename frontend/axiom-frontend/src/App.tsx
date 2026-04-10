import { useState } from 'react';
import { useAlgorandStream } from './AlgorandStream';
import type { PaymentEvent } from './AlgorandStream';
import { NetworkGraph } from './NetworkGraph';
import { AxiomTerminal } from './AxiomTerminal';
import { SystemVitals } from './SystemVitals';
import { TemporalScrubber } from './TemporalScrubber';
import { IntentModal } from './IntentModal';

function App() {
  const { events } = useAlgorandStream();
  const [selectedTxId, setSelectedTxId] = useState<string | null>(null);
  const [historicalRound, setHistoricalRound] = useState<number | null>(null);
  const [currentRound, setCurrentRound] = useState<number>(28041337);

  const handleNodeClick = (addr: string) => {
    console.log('Node clicked', addr);
  };

  const handleEdgeClick = (txId: string) => {
    setSelectedTxId(txId);
  };

  const handleEventClick = (ev: PaymentEvent) => {
    setSelectedTxId(ev.tx_id);
  };

  const handleRoundChange = (round: number) => {
    setHistoricalRound(round);
    setCurrentRound(round);
  };

  return (
    <div className="axiom-app">
      <div className="glass-panel app-header">
        <div className="header-brand">AXIOM Dashboard</div>
        <div className="header-round">Block Round: {currentRound.toLocaleString()}</div>
        <div className="header-status">
          LOCALNET
          <div className="status-dot"></div>
        </div>
      </div>
      
      <div className="main-layout">
        <div className="glass-panel panel left-panel">
          <NetworkGraph 
            events={events} 
            onNodeClick={handleNodeClick} 
            onEdgeClick={handleEdgeClick}
            historicalRound={historicalRound}
          />
        </div>
        <div className="glass-panel panel center-panel">
          <AxiomTerminal events={events} onEventClick={handleEventClick} />
        </div>
        <div className="glass-panel panel right-panel">
          <SystemVitals 
            onApprove={(id) => console.log('Approve', id)}
            onReject={(id) => console.log('Reject', id)}
          />
        </div>
      </div>
      
      <div className="glass-panel bottom-panel">
        <TemporalScrubber 
          currentRound={currentRound}
          minRound={28000000}
          maxRound={28041337}
          onRoundChange={handleRoundChange}
        />
      </div>
      
      {selectedTxId && (
        <IntentModal txId={selectedTxId} onClose={() => setSelectedTxId(null)} />
      )}
    </div>
  );
}

export default App;
