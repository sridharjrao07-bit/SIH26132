// Calendar math on ISO dates in UTC, so a user's timezone can't shift a day.
export const toDay = (iso: string) => Date.UTC(+iso.slice(0, 4), +iso.slice(5, 7) - 1, +iso.slice(8, 10));
export const daysBetween = (a: string, b: string) => Math.round((toDay(b) - toDay(a)) / 86_400_000);
/** Today in IST as YYYY-MM-DD: the backend's calendar (app/utils/tz.py). */
export function istToday(now = new Date()): string {
  return new Date(now.getTime() + 330 * 60_000).toISOString().slice(0, 10);
}
