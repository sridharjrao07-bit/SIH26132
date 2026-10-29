interface TrendIndicatorProps {
  value: number | null;
  compact?: boolean;
}

export function TrendIndicator({ value, compact = false }: TrendIndicatorProps) {
  if (value == null || Math.abs(value) < 0.05) {
    return <span className="trend trend-neutral" aria-label="No meaningful change">— Steady</span>;
  }

  const positive = value > 0;
  return (
    <span className={`trend ${positive ? 'trend-up' : 'trend-down'} ${compact ? 'trend-compact' : ''}`}>
      <span aria-hidden>{positive ? '▲' : '▼'}</span>
      {Math.abs(value).toFixed(1)}%
    </span>
  );
}
