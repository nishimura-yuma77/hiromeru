export type ApiErrorKind = "http" | "network" | "timeout" | "parse";

export type ApiFieldError = {
  field: string | null;
  code: string;
  message: string;
};

type ApiErrorOptions = {
  kind: ApiErrorKind;
  message: string;
  status?: number;
  code?: string;
  retryable?: boolean;
  agentTurnId?: number | null;
  fieldErrors?: ApiFieldError[];
};

export class ApiError extends Error {
  readonly kind: ApiErrorKind;
  readonly status: number | null;
  readonly code: string;
  readonly retryable: boolean;
  readonly agentTurnId: number | null;
  readonly fieldErrors: ApiFieldError[];

  constructor(options: ApiErrorOptions) {
    super(options.message);
    this.name = "ApiError";
    this.kind = options.kind;
    this.status = options.status ?? null;
    this.code = options.code ?? "UNKNOWN_ERROR";
    this.retryable = options.retryable ?? false;
    this.agentTurnId = options.agentTurnId ?? null;
    this.fieldErrors = options.fieldErrors ?? [];
  }
}

export type ApiDataParser<T> = (input: unknown) => T;

function isRecord(input: unknown): input is Record<string, unknown> {
  return typeof input === "object" && input !== null && !Array.isArray(input);
}

function parseFieldErrors(input: unknown): ApiFieldError[] {
  if (!Array.isArray(input)) {
    return [];
  }

  return input.flatMap((fieldError) => {
    if (
      !isRecord(fieldError) ||
      (typeof fieldError.field !== "string" && fieldError.field !== null) ||
      typeof fieldError.code !== "string" ||
      typeof fieldError.message !== "string"
    ) {
      return [];
    }

    return [{ field: fieldError.field, code: fieldError.code, message: fieldError.message }];
  });
}

export function parseApiEnvelope<T>(
  input: unknown,
  status: number,
  parseData: ApiDataParser<T>,
): T {
  if (!isRecord(input) || typeof input.success !== "boolean") {
    throw new ApiError({ kind: "parse", message: "APIレスポンスを読み取れませんでした。", status });
  }

  if (input.success === false) {
    const error = input.error;
    if (!isRecord(error) || typeof error.code !== "string" || typeof error.message !== "string") {
      throw new ApiError({ kind: "parse", message: "APIエラーを読み取れませんでした。", status });
    }

    throw new ApiError({
      kind: "http",
      status,
      code: error.code,
      message: error.message,
      retryable: error.retryable === true,
      agentTurnId: typeof error.agent_turn_id === "number" ? error.agent_turn_id : null,
      fieldErrors: parseFieldErrors(error.field_errors),
    });
  }

  if (input.error !== null) {
    throw new ApiError({ kind: "parse", message: "APIレスポンスの形式が正しくありません。", status });
  }

  try {
    return parseData(input.data);
  } catch (error) {
    if (error instanceof ApiError) {
      throw error;
    }
    throw new ApiError({ kind: "parse", message: "APIデータを読み取れませんでした。", status });
  }
}

export async function parseApiResponse<T>(
  response: Response,
  parseData: ApiDataParser<T>,
): Promise<T> {
  let body: unknown;
  try {
    body = await response.json();
  } catch {
    if (!response.ok) {
      throw new ApiError({
        kind: "http",
        status: response.status,
        code: "HTTP_ERROR",
        message: "APIリクエストに失敗しました。",
      });
    }
    throw new ApiError({ kind: "parse", status: response.status, message: "APIレスポンスを読み取れませんでした。" });
  }

  return parseApiEnvelope(body, response.status, parseData);
}

export function normalizeFetchError(error: unknown): ApiError {
  if (error instanceof ApiError) {
    return error;
  }
  if (error instanceof DOMException && (error.name === "TimeoutError" || error.name === "AbortError")) {
    return new ApiError({ kind: "timeout", message: "APIリクエストがタイムアウトしました。" });
  }
  return new ApiError({ kind: "network", message: "APIへ接続できませんでした。" });
}
