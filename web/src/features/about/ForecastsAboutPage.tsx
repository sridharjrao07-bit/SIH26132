import { Trans, useLingui } from '@lingui/react/macro';
import { AccuracyCard } from '../trust/AccuracyCard.tsx';
import { METHODS } from '../trust/methods.ts';
import { Section } from '../../ui/Section.tsx';

export function ForecastsAboutPage() {
  const { i18n } = useLingui();
  const shown = ['moving_avg', 'blend', 'feature_ols', 'holt_winters', 'gbm'];
  return (
    <div className="mx-auto max-w-2xl px-4 py-8 md:py-12">
      <div className="border-b-2 border-ink pb-6 mb-8">
        <h1 className="text-3xl md:text-4xl font-bold tracking-tight"><Trans>How forecasts work</Trans></h1>
      </div>
      
      <Section className="!px-0 !py-6 !border-b-0"><AccuracyCard /></Section>
      
      <Section title={<Trans>What the chart shows</Trans>} className="!px-0 !border-b-2">
        <ul className="space-y-4 text-base md:text-lg leading-relaxed md:leading-loose">
          <li className="flex gap-4">
            <span className="shrink-0 w-4 h-0 border-b-2 border-ink mt-3"></span>
            <span><Trans>Solid line: real mandi prices (modal price, ₹ per quintal).</Trans></span>
          </li>
          <li className="flex gap-4">
            <span className="shrink-0 w-4 h-0 border-b-2 border-ink border-dashed mt-3"></span>
            <span><Trans>Dashed line: the model’s forecast for the next few days.</Trans></span>
          </li>
          <li className="flex gap-4">
            <span className="shrink-0 w-4 h-4 bg-ink/10 border border-ink/20 mt-1.5 rounded-sm"></span>
            <span><Trans>Shaded area: the likely range. The real price can still fall outside it.</Trans></span>
          </li>
          <li className="flex gap-4">
            <span className="shrink-0 w-4 h-4 bg-ink mt-1.5 rounded-sm"></span>
            <span><Trans>Bars below: how much produce arrived at the mandi. More arrivals often mean lower prices.</Trans></span>
          </li>
        </ul>
      </Section>

      <Section title={<Trans>Models we use</Trans>} className="!px-0 !border-b-2">
        <dl className="space-y-8 text-base md:text-lg leading-relaxed md:leading-loose">
          {shown.map((k) => (
            <div key={k} className="border-l-4 border-rule pl-4">
              <dt className="font-semibold text-lg md:text-xl text-ink mb-1">{i18n._(METHODS[k].label)}</dt>
              <dd className="text-ink-2">{i18n._(METHODS[k].about)}</dd>
            </div>
          ))}
        </dl>
        <p className="mt-8 text-base md:text-lg leading-relaxed font-medium bg-paper-2 p-4 md:p-6 rounded-sm border-l-4 border-ink">
          <Trans>A more complex model is used only if it beats a simple one on real past prices. Every forecast names the model that made it.</Trans>
        </p>
      </Section>

      <Section title={<Trans>Where the advice comes from</Trans>} className="!px-0 !border-b-0">
        <p className="text-base md:text-lg leading-relaxed md:leading-loose">
          <Trans>Sell / Hold / Wait is decided by the server from mandi arrivals, nearby storage and the forecast. The app shows the advice exactly as the server gives it.</Trans>
        </p>
      </Section>
    </div>
  );
}
