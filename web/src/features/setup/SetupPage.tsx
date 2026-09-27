import { useState } from 'react';
import { useNavigate } from '@tanstack/react-router';
import { useQuery } from '@tanstack/react-query';
import { Trans } from '@lingui/react/macro';
import { commoditiesQuery, marketsQuery } from '../../queries/index.ts';
import { usePrefs } from '../../stores/prefs.ts';
import { LANGS, LANG_LABEL } from '../../i18n/locales.ts';
import { cropName } from '../price-detail/PairView.tsx';
import { distanceKm } from '../../domain/geo.ts';
import { Block } from '../../ui/Skeleton.tsx';

const option = 'tap flex w-full items-center justify-between rule-b px-4 text-left text-base';

/** First run: language → crop → mandi. About 3 taps, no login, no network beyond reference data. */
export function SetupPage() {
  const navigate = useNavigate();
  const { lang, setLang, district, pinPair } = usePrefs();
  const [step, setStep] = useState<0 | 1 | 2>(0);
  const [crop, setCrop] = useState<string | null>(null);
  const [here, setHere] = useState<{ lat: number; lng: number } | null>(null);
  const [locating, setLocating] = useState(false);
  const commodities = useQuery(commoditiesQuery());
  const markets = useQuery(marketsQuery(district));

  const locate = () => {
    if (!navigator.geolocation) return;
    setLocating(true);
    navigator.geolocation.getCurrentPosition(
      (p) => { setHere({ lat: p.coords.latitude, lng: p.coords.longitude }); setLocating(false); },
      () => setLocating(false),
      { timeout: 8000, maximumAge: 600_000 },
    );
  };

  const sortedMarkets = (markets.data ?? [])
    .map((m) => ({ ...m, km: here ? Math.round(distanceKm(here, m)) : null }))
    .sort((a, b) => (a.km ?? 0) - (b.km ?? 0) || a.name.localeCompare(b.name));

  return (
    <div className="mx-auto max-w-lg">
      <p className="px-4 pt-4 text-xs text-ink-2 tabular"><Trans>Step {step + 1} of 3</Trans></p>
      {step === 0 && (
        <>
          <h1 className="px-4 pt-1 pb-3 text-lg font-semibold"><Trans>Choose your language</Trans></h1>
          <div className="rule-t">
            {LANGS.map((l) => (
              <button key={l} lang={l} className={option} onClick={() => { setLang(l); setStep(1); }}>
                <span className={lang === l ? 'font-semibold' : ''}>{LANG_LABEL[l]}</span><span aria-hidden>›</span>
              </button>
            ))}
          </div>
        </>
      )}
      {step === 1 && (
        <>
          <h1 className="px-4 pt-1 pb-3 text-lg font-semibold"><Trans>Which crop do you sell?</Trans></h1>
          <div className="rule-t">
            {commodities.isPending ? <Block h={200} /> : (commodities.data ?? []).map((c) => (
              <button key={c.id} className={option} onClick={() => { setCrop(c.id); setStep(2); }}>
                <span>{cropName(c, lang)}</span><span aria-hidden>›</span>
              </button>
            ))}
          </div>
        </>
      )}
      {step === 2 && crop && (
        <>
          <h1 className="px-4 pt-1 pb-3 text-lg font-semibold"><Trans>Which mandi do you sell at?</Trans></h1>
          {!here && (
            <div className="px-4 pb-3">
              <button onClick={locate} disabled={locating} className="tap w-full rounded border border-ink px-4 font-semibold">
                {locating ? <Trans>Finding your location…</Trans> : <Trans>Sort by distance from me</Trans>}
              </button>
            </div>
          )}
          <div className="rule-t">
            {markets.isPending ? <Block h={200} /> : sortedMarkets.map((m) => (
              <button key={m.id} className={option} onClick={() => { pinPair({ commodityId: crop, marketId: m.id }); navigate({ to: '/' }); }}>
                <span>{m.name}{m.taluka && <span className="text-sm text-ink-2"> · {m.taluka}</span>}</span>
                <span className="tabular text-sm text-ink-2">{m.km != null ? `${m.km} km` : '›'}</span>
              </button>
            ))}
          </div>
        </>
      )}
    </div>
  );
}
