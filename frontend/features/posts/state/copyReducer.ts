export type CopyState = { copiedField: string | null; error: string | null };
export type CopyEvent =
  | { type: "copySucceeded"; field: string }
  | { type: "copyFailed" };

export const initialCopyState: CopyState = { copiedField: null, error: null };

export function copyReducer(state: CopyState, event: CopyEvent): CopyState {
  switch (event.type) {
    case "copySucceeded":
      return { copiedField: event.field, error: null };
    case "copyFailed":
      return { ...state, error: "URLをコピーできませんでした。URLを選択してコピーしてください。" };
  }
}
