export type CopyState = { copiedField: string | null; pendingField: string | null; error: string | null };
export type CopyEvent =
  | { type: "copyStarted"; field: string }
  | { type: "copySucceeded"; field: string }
  | { type: "copyFailed" };

export const initialCopyState: CopyState = { copiedField: null, pendingField: null, error: null };

export function copyReducer(state: CopyState, event: CopyEvent): CopyState {
  switch (event.type) {
    case "copyStarted":
      return { copiedField: null, pendingField: event.field, error: null };
    case "copySucceeded":
      return { copiedField: event.field, pendingField: null, error: null };
    case "copyFailed":
      return { ...state, pendingField: null, error: "URLをコピーできませんでした。URLを選択してコピーしてください。" };
  }
}
