export type LoginState = {
  email: string;
  password: string;
  isPasswordVisible: boolean;
  isPending: boolean;
  emailError: string | null;
  passwordError: string | null;
  formError: string | null;
  shouldReload: boolean;
  hasCredentialError: boolean;
};

export type LoginEvent =
  | { type: "emailChanged"; email: string }
  | { type: "passwordChanged"; password: string }
  | { type: "passwordVisibilityToggled" }
  | { type: "loginStarted" }
  | { type: "validationFailed"; emailError: string | null; passwordError: string | null }
  | { type: "credentialsRejected" }
  | { type: "loginFailed"; message: string; shouldReload: boolean };

export function createInitialLoginState(initialFormError: string | null): LoginState {
  return {
    email: "",
    password: "",
    isPasswordVisible: false,
    isPending: false,
    emailError: null,
    passwordError: null,
    formError: initialFormError,
    shouldReload: initialFormError !== null,
    hasCredentialError: false,
  };
}

export function validateEmail(email: string): string | null {
  if (email.length === 0) {
    return "メールアドレスを入力してください";
  }
  if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) {
    return "メールアドレスの形式で入力してください";
  }
  return null;
}

export function validatePassword(password: string): string | null {
  return password.length === 0 ? "パスワードを入力してください" : null;
}

export function loginReducer(state: LoginState, event: LoginEvent): LoginState {
  switch (event.type) {
    case "emailChanged":
      return {
        ...state,
        email: event.email,
        emailError:
          state.hasCredentialError || state.emailError === null
            ? state.emailError
            : validateEmail(event.email.trim()),
      };
    case "passwordChanged":
      return {
        ...state,
        password: event.password,
        passwordError:
          state.hasCredentialError || state.passwordError === null
            ? state.passwordError
            : validatePassword(event.password),
      };
    case "passwordVisibilityToggled":
      return { ...state, isPasswordVisible: !state.isPasswordVisible };
    case "loginStarted":
      return {
        ...state,
        isPending: true,
        emailError: null,
        passwordError: null,
        formError: null,
        shouldReload: false,
        hasCredentialError: false,
      };
    case "validationFailed":
      return {
        ...state,
        isPending: false,
        emailError: event.emailError,
        passwordError: event.passwordError,
      };
    case "credentialsRejected":
      return {
        ...state,
        isPending: false,
        emailError: "メールアドレスまたはパスワードが正しくありません",
        passwordError: "メールアドレスまたはパスワードが正しくありません",
        hasCredentialError: true,
      };
    case "loginFailed":
      return {
        ...state,
        isPending: false,
        formError: event.message,
        shouldReload: event.shouldReload,
      };
  }
}
