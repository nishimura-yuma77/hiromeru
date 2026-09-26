export type MemoryDeleteState = {
  selectedId: number | null;
  isPending: boolean;
  error: string | null;
  deletedId: number | null;
};

export type MemoryDeleteEvent =
  | { type: "confirmationOpened"; memoryId: number }
  | { type: "confirmationClosed" }
  | { type: "deleteStarted" }
  | { type: "deleteSucceeded"; memoryId: number }
  | { type: "deleteFailed"; message: string };

export const initialMemoryDeleteState: MemoryDeleteState = {
  selectedId: null,
  isPending: false,
  error: null,
  deletedId: null,
};

export function memoryDeleteReducer(
  state: MemoryDeleteState,
  event: MemoryDeleteEvent,
): MemoryDeleteState {
  switch (event.type) {
    case "confirmationOpened":
      return { ...state, selectedId: event.memoryId, error: null };
    case "confirmationClosed":
      return { ...state, selectedId: null, error: null };
    case "deleteStarted":
      return { ...state, isPending: true, error: null };
    case "deleteSucceeded":
      return { selectedId: null, isPending: false, error: null, deletedId: event.memoryId };
    case "deleteFailed":
      return { ...state, isPending: false, error: event.message };
  }
}
