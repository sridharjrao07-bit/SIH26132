import { Navigate, useNavigate, useSearch } from '@tanstack/react-router';
import { usePrefs } from '../../stores/prefs.ts';
import { PairView } from '../price-detail/PairView.tsx';

/** Today = the farmer's saved pair, no navigation before the answer. */
export function TodayPage() {
  const pair = usePrefs((s) => s.pinnedPairs[0]);
  const pinPair = usePrefs((s) => s.pinPair);
  const { range = 30 } = useSearch({ from: '/' });
  const navigate = useNavigate({ from: '/' });
  if (!pair) return <Navigate to="/setup" />;
  return (
    <PairView
      pair={pair}
      range={range}
      onPairChange={pinPair}                    // switching on Today updates the saved pair
      onRangeChange={(r) => navigate({ search: { range: r === 30 ? undefined : r }, replace: true })}
    />
  );
}
