import { useNavigate, useParams, useSearch } from '@tanstack/react-router';
import { Trans } from '@lingui/react/macro';
import { usePrefs } from '../../stores/prefs.ts';
import { PairView } from './PairView.tsx';

export function PairDetailPage() {
  const { crop, market } = useParams({ from: '/c/$crop/m/$market' });
  const { range = 30 } = useSearch({ from: '/c/$crop/m/$market' });
  const navigate = useNavigate({ from: '/c/$crop/m/$market' });
  const pinned = usePrefs((s) => s.pinnedPairs[0]);
  const pinPair = usePrefs((s) => s.pinPair);
  const isPinned = pinned?.commodityId === crop && pinned?.marketId === market;
  return (
    <>
      <PairView
        pair={{ commodityId: crop, marketId: market }}
        range={range}
        onPairChange={(p) => navigate({ to: '/c/$crop/m/$market', params: { crop: p.commodityId, market: p.marketId }, search: { range } })}
        onRangeChange={(r) => navigate({ search: { range: r === 30 ? undefined : r }, replace: true })}
      />
      {!isPinned && (
        <div className="px-4 py-4">
          <button className="tap w-full rounded border border-rule px-4 text-sm" onClick={() => { pinPair({ commodityId: crop, marketId: market }); navigate({ to: '/' }); }}>
            <Trans>Show this on my Today screen</Trans>
          </button>
        </div>
      )}
    </>
  );
}
