import { useState } from 'react';
import { useNavigate } from '@tanstack/react-router';
import { useQuery } from '@tanstack/react-query';
import { Trans, useLingui } from '@lingui/react/macro';
import { commoditiesQuery, marketsQuery } from '../../queries/index.ts';
import { usePrefs } from '../../stores/prefs.ts';
import { LANGS, LANG_LABEL } from '../../i18n/locales.ts';
import { cropName } from '../price-detail/PairView.tsx';
import { distanceKm } from '../../domain/geo.ts';
import { Block } from '../../ui/Skeleton.tsx';
import { CropIcon } from '../../ui/CropIcons.tsx';

/** Step progress dots */
function StepDots({ current }: { current: 0 | 1 | 2 }) {
  return (
    <div className="flex items-center gap-2" aria-hidden>
      {[0, 1, 2].map((i) => (
        <div
          key={i}
          className="rounded-full transition-all"
          style={{
            width: i === current ? 20 : 8,
            height: 8,
            background: i === current ? 'white' : 'rgba(255,255,255,0.3)',
          }}
        />
      ))}
    </div>
  );
}

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
  const { t } = useLingui();

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

  const stepTitles = [
    t`Choose your language`,
    t`Which crop do you sell?`,
    t`Which mandi do you use?`,
  ];

  return (
    <div className="min-h-dvh flex flex-col">

      {/* ── DARK HERO TOP PANEL ──────────────────────────────────── */}
      <div
        className="px-4 pt-8 pb-6"
        style={{ background: 'linear-gradient(135deg, #0F0E0C 0%, #1C1A17 50%, #0F0E0C 100%)' }}
      >
        {/* Logo */}
        <div className="flex items-center gap-3 mb-6">
          <div
            className="flex size-12 items-center justify-center rounded-xl"
            style={{ background: 'var(--color-accent)' }}
            aria-hidden
          >
            <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="white" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M12 2L12 22"/><path d="M5 7 Q8 4 12 6 Q16 4 19 7"/>
              <path d="M5 11 Q8 8 12 10 Q16 8 19 11"/>
              <path d="M5 15 Q8 12 12 14 Q16 12 19 15"/>
            </svg>
          </div>
          <div>
            <p className="text-lg font-bold text-white leading-tight"><Trans>Krishi Bazaar</Trans></p>
            <p className="text-xs text-white/50"><Trans>APMC Mandi Intelligence</Trans></p>
          </div>
        </div>

        {/* Step heading */}
        <h1 className="text-xl font-semibold text-white mb-3">
          {stepTitles[step]}
        </h1>

        {/* Progress dots + step label */}
        <div className="flex items-center justify-between">
          <StepDots current={step} />
          <p className="text-xs text-white/50 uppercase tracking-wider">
            <Trans>Step {step + 1} of 3</Trans>
          </p>
        </div>
      </div>

      {/* ── CONTENT CARD (paper surface, rounded top corners) ─────── */}
      <div
        className="flex-1 bg-paper rounded-t-2xl -mt-4 relative z-10"
        style={{ boxShadow: '0 -4px 20px rgba(0,0,0,0.12)' }}
      >
        <div className="mx-auto max-w-lg px-0 pt-4 pb-8">

          {/* STEP 0: Language */}
          {step === 0 && (
            <div className="pt-2">
              {LANGS.map((l) => (
                <button
                  key={l}
                  lang={l}
                  className="tap flex w-full items-center justify-between rule-b px-6 text-left text-base hover:bg-paper-2 transition-colors"
                  onClick={() => { setLang(l); setStep(1); }}
                >
                  <div>
                    <span className={`text-base ${lang === l ? 'font-bold text-accent' : 'font-medium text-ink'}`}>
                      {LANG_LABEL[l]}
                    </span>
                    {lang === l && (
                      <span className="ml-2 text-xs font-semibold px-1.5 py-0.5 rounded-sm" style={{ background: 'var(--color-accent-tint)', color: 'var(--color-accent)' }}>
                        <Trans>Current</Trans>
                      </span>
                    )}
                  </div>
                  {lang === l ? (
                    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="var(--color-accent)" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
                      <path d="M20 6L9 17l-5-5"/>
                    </svg>
                  ) : (
                    <span aria-hidden className="text-ink-2">›</span>
                  )}
                </button>
              ))}
            </div>
          )}

          {/* STEP 1: Crop selection with icons */}
          {step === 1 && (
            <div className="pt-2">
              {commodities.isPending ? (
                <div className="space-y-2 px-4 pt-2">
                  {[0, 1, 2, 3].map((i) => <Block key={i} h={56} />)}
                </div>
              ) : (commodities.data ?? []).map((c) => (
                <button
                  key={c.id}
                  className="tap flex w-full items-center gap-4 rule-b px-6 text-left hover:bg-paper-2 transition-colors"
                  onClick={() => { setCrop(c.id); setStep(2); }}
                >
                  {/* Crop icon box */}
                  <div
                    className="flex shrink-0 size-10 items-center justify-center rounded-xl"
                    style={{ background: 'var(--color-accent-tint)' }}
                    aria-hidden
                  >
                    <CropIcon
                      commodityId={c.id}
                      size={20}
                      stroke="var(--color-accent)"
                    />
                  </div>
                  <div className="flex-1">
                    <p className="font-semibold text-ink">{cropName(c, lang)}</p>
                    <p className="text-xs text-ink-2">{c.name_en !== cropName(c, lang) ? c.name_en : ''}</p>
                  </div>
                  <span aria-hidden className="text-ink-2">›</span>
                </button>
              ))}
            </div>
          )}

          {/* STEP 2: Mandi selection */}
          {step === 2 && crop && (
            <div className="pt-2">
              {/* Location sort button */}
              {!here && (
                <div className="px-6 py-3 border-b border-rule">
                  <button
                    onClick={locate}
                    disabled={locating}
                    className="tap w-full flex items-center justify-center gap-2 rounded-xl border border-rule font-semibold text-sm text-ink-2 hover:bg-paper-2 transition-colors"
                  >
                    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="var(--color-accent)" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
                      <path d="M21 10c0 7-9 13-9 13s-9-6-9-13a9 9 0 0 1 18 0z"/><circle cx="12" cy="10" r="3"/>
                    </svg>
                    {locating ? <Trans>Finding your location…</Trans> : <Trans>Sort by distance from me</Trans>}
                  </button>
                </div>
              )}

              {markets.isPending ? (
                <div className="space-y-2 px-4 pt-2">
                  {[0, 1, 2, 3, 4].map((i) => <Block key={i} h={56} />)}
                </div>
              ) : sortedMarkets.map((m) => (
                <button
                  key={m.id}
                  className="tap flex w-full items-center justify-between rule-b px-6 text-left hover:bg-paper-2 transition-colors"
                  onClick={() => { pinPair({ commodityId: crop, marketId: m.id }); navigate({ to: '/' }); }}
                >
                  <div>
                    <span className="font-semibold text-ink">{m.name}</span>
                    {m.taluka && (
                      <span className="text-sm text-ink-2"> · {m.taluka}</span>
                    )}
                  </div>
                  <div className="flex items-center gap-2">
                    {m.km != null && (
                      <span
                        className="tabular text-xs font-semibold px-1.5 py-0.5 rounded-sm"
                        style={{ background: 'var(--color-paper-2)', color: 'var(--color-ink-2)' }}
                      >
                        {m.km} km
                      </span>
                    )}
                    <span aria-hidden className="text-ink-2">›</span>
                  </div>
                </button>
              ))}
            </div>
          )}

          {/* Back button */}
          {step > 0 && (
            <div className="px-6 pt-4">
              <button
                className="tap flex items-center gap-2 text-sm text-ink-2 hover:text-ink transition-colors"
                onClick={() => setStep((s) => (s - 1) as 0 | 1 | 2)}
              >
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
                  <path d="m15 18-6-6 6-6"/>
                </svg>
                <Trans>Back</Trans>
              </button>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
