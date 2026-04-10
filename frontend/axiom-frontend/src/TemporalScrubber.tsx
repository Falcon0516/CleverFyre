import React, { useState, useEffect } from 'react';

interface TemporalScrubberProps {
  currentRound: number;
  minRound: number;
  maxRound: number;
  onRoundChange: (round: number) => void;
}

export const TemporalScrubber: React.FC<TemporalScrubberProps> = ({
  currentRound,
  minRound,
  maxRound,
  onRoundChange,
}) => {
  const [val, setVal] = useState(currentRound);

  useEffect(() => {
    setVal(currentRound);
  }, [currentRound]);

  const handleChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const newVal = parseInt(e.target.value);
    setVal(newVal);
    setTimeout(() => {
      onRoundChange(newVal);
    }, 150);
  };

  const isLive = val >= maxRound;
  const percentage = ((val - minRound) / Math.max(1, (maxRound - minRound))) * 100;

  return (
    <div className="scrubber-container" style={{background: 'transparent', height: '100%', display: 'flex', flexDirection: 'column', justifyContent: 'center'}}>
      <div className="scrubber-controls">
        <div className="scrubber-controls-left">
          <button
            className={`btn-live-btn interactive ${isLive ? 'active' : ''}`}
            onClick={() => onRoundChange(maxRound)}
          >
            Live {isLive && <span className="active-dot"></span>}
          </button>
          
          <div className="round-display">
            Round {val.toLocaleString()}
          </div>
          {!isLive && <span className="historical-label">⏱ Historical</span>}
        </div>
      </div>

      <input
        type="range"
        min={minRound}
        max={maxRound}
        value={val}
        onChange={handleChange}
        className="scrubber-range"
        style={{
          background: `linear-gradient(to right, var(--color-primary) ${percentage}%, rgba(0,0,0,0.05) ${percentage}%)`
        }}
      />
    </div>
  );
};
