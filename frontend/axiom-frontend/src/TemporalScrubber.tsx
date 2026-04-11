import { useEffect, useRef, useState, useCallback } from 'react';

interface Props {
  currentRound: number;
  minRound: number;
  maxRound: number;
  onRoundChange: (round: number) => void;
}

export default function TemporalScrubber({
  currentRound,
  minRound,
  maxRound,
  onRoundChange,
}: Props) {
  const [sliderValue, setSliderValue] = useState(currentRound || maxRound);
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const isLive = currentRound >= maxRound - 1 || currentRound === 0;

  // Sync slider when round changes externally
  useEffect(() => {
    if (currentRound > 0) {
      setSliderValue(currentRound);
    }
  }, [currentRound]);

  const handleSliderChange = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      const val = Number(e.target.value);
      setSliderValue(val);

      // Debounce the round change callback
      if (debounceRef.current) clearTimeout(debounceRef.current);
      debounceRef.current = setTimeout(() => {
        onRoundChange(val);
      }, 300);
    },
    [onRoundChange]
  );

  const handleLiveClick = useCallback(() => {
    setSliderValue(maxRound);
    onRoundChange(maxRound);
  }, [maxRound, onRoundChange]);

  const effectiveMin = minRound || Math.max(0, maxRound - 10000);
  const effectiveMax = maxRound || 1;

  return (
    <div className="scrubber-container">
      <button
        className={`btn-live ${isLive ? 'active' : ''}`}
        onClick={handleLiveClick}
      >
        {isLive && <span className="live-dot" />}
        LIVE
      </button>

      <span className="round-display">
        Round {sliderValue > 0 ? sliderValue.toLocaleString() : '—'}
      </span>

      {!isLive && (
        <span className="historical-badge">
          ◷ HISTORICAL
        </span>
      )}

      <input
        type="range"
        className="scrubber-range"
        min={effectiveMin}
        max={effectiveMax}
        value={sliderValue || effectiveMax}
        onChange={handleSliderChange}
      />
    </div>
  );
}
