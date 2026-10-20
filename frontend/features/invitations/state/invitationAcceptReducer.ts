export type InvitationAcceptState = {
  password: string;
  isPasswordVisible: boolean;
  isPending: boolean;
  passwordError: string | null;
  formError: string | null;
  isLinkInvalid: boolean;
};

export type InvitationAcceptEvent =
  | { type: "passwordChanged"; password: string }
  | { type: "passwordVisibilityToggled" }
  | { type: "submitStarted" }
  | { type: "validationFailed"; passwordError: string }
  | { type: "linkRejected" }
  | { type: "submitFailed"; message: string };

export const PASSWORD_RULE =
  "12～128文字で、空白を除く半角英数字・記号だけを使い、英大文字・英小文字・数字・記号をそれぞれ1文字以上含めてください";

export function createInitialInvitationAcceptState(hasToken: boolean): InvitationAcceptState {
  return {
    password: "",
    isPasswordVisible: false,
    isPending: false,
    passwordError: null,
    formError: null,
    isLinkInvalid: !hasToken,
  };
}

// サーバーと同じ条件。最終的な判定はAPIが行う（API_DESIGN 11.3）。
export function validateNewPassword(password: string): string | null {
  if (password.length === 0) {
    return "パスワードを入力してください";
  }
  if (password.length > 128) {
    return "パスワードは128文字以内で入力してください";
  }
  const valid =
    password.length >= 12 &&
    /^[\x21-\x7e]+$/.test(password) &&
    /[A-Z]/.test(password) &&
    /[a-z]/.test(password) &&
    /[0-9]/.test(password) &&
    /[^A-Za-z0-9]/.test(password);
  return valid ? null : `パスワードは${PASSWORD_RULE}`;
}

export function invitationAcceptReducer(
  state: InvitationAcceptState,
  event: InvitationAcceptEvent,
): InvitationAcceptState {
  switch (event.type) {
    case "passwordChanged":
      return {
        ...state,
        password: event.password,
        passwordError: state.passwordError ? validateNewPassword(event.password) : null,
      };
    case "passwordVisibilityToggled":
      return { ...state, isPasswordVisible: !state.isPasswordVisible };
    case "submitStarted":
      return { ...state, isPending: true, passwordError: null, formError: null };
    case "validationFailed":
      return { ...state, isPending: false, passwordError: event.passwordError };
    case "linkRejected":
      return { ...state, isPending: false, isLinkInvalid: true };
    case "submitFailed":
      return { ...state, isPending: false, formError: event.message };
  }
}
