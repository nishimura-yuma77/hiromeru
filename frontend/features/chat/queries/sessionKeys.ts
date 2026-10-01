export const sessionKeys = {
  list: () => ["sessions", "list"] as const,
  history: (id: number, before?: number) => ["sessions", "history", id, before ?? null] as const,
  turn: (id: number, turnId: number) => ["sessions", "turn", id, turnId] as const,
};
