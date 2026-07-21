/** Date-input value -> ISO string the API accepts.
 *
 * Noon UTC keeps a backdated domain date on the same calendar day in every
 * timezone the operator is likely to view it from — shared by the interview
 * timeline and offer forms so the convention can't drift.
 */
export function toIso(value: string): string | null {
  if (!value) return null
  return new Date(`${value}T12:00:00Z`).toISOString()
}
