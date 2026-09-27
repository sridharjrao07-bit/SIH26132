import { Trans, useLingui } from '@lingui/react/macro';
import { AccuracyCard } from '../trust/AccuracyCard.tsx';
import { METHODS } from '../trust/methods.ts';
import { Section } from '../../ui/Section.tsx';

export function ForecastsAboutPage() {
  const { i18n } = useLingui();
  const shown = ['moving_avg', 'blend', 'feature_ols', 'holt_winters', 'gbm'];
  return (
    <div className="mx-auto max-w-2xl">
      <div className="rule-b px-4 pt-4 pb-3">
        <h1 className="text-lg font-semibold"><Trans>How forecasts work</Trans></h1>
      </div>
      <Section><AccuracyCard /></Section>
      <Section title={<Trans>What the chart shows</Trans>}>
        <ul className="space-y-2 text-sm">
          <li><Trans>Solid line: real mandi prices (modal price, ₹ per quintal).</Trans></li>
          <li><Trans>Dashed line: the model’s forecast for the next few days.</Trans></li>
          <li><Trans>Shaded area: the likely range. The real price can still fall outside it.</Trans></li>
          <li><Trans>Bars below: how much produce arrived at the mandi. More arrivals often mean lower prices.</Trans></li>
        </ul>
      </Section>
      <Section title={<Trans>Models we use</Trans>}>
        <dl className="space-y-3 text-sm">
          {shown.map((k) => (
            <div key={k}>
              <dt className="font-semibold">{i18n._(METHODS[k].label)}</dt>
              <dd className="text-ink-2">{i18n._(METHODS[k].about)}</dd>
            </div>
          ))}
        </dl>
        <p className="mt-4 text-sm">
          <Trans>A more complex model is used only if it beats a simple one on real past prices. Every forecast names the model that made it.</Trans>
        </p>
      </Section>
      <Section title={<Trans>Where the advice comes from</Trans>}>
        <p className="text-sm">
          <Trans>Sell / Hold / Wait is decided by the server from mandi arrivals, nearby storage and the forecast. The app shows the advice exactly as the server gives it.</Trans>
        </p>
      </Section>
    </div>
  );
}
