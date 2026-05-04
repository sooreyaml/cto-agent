const TTL_MS = 60 * 60 * 1000;
const seen = new Map<string, number>();

function prune(now: number) {
  for (const [id, t] of seen) {
    if (now - t > TTL_MS) seen.delete(id);
  }
}

/** @returns true if this event_id was already seen (duplicate delivery). */
export function isDuplicateSlackEvent(eventId: string): boolean {
  const now = Date.now();
  prune(now);
  if (seen.has(eventId)) return true;
  seen.set(eventId, now);
  return false;
}
