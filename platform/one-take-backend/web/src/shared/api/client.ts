export class ApiError extends Error {
  code: string;
  status: number;
  retryable: boolean;

  constructor(message: string, options: { code?: string; status: number; retryable?: boolean }) {
    super(message);
    this.name = "ApiError";
    this.code = options.code ?? "API_ERROR";
    this.status = options.status;
    this.retryable = options.retryable ?? false;
  }
}

/** FastAPI 自带的**参数校验**错误体是 `{"detail":[…]}`（没有 `error.message`）。
 *
 * 不翻译的话，前端只能兜底成「请求失败（422）」这种零信息文案 —— 2026-10-15 用户就被它糊了一次：
 * 真正的原因（url 为空 / 超过 2048 字符）一个字都没露出来。这里翻成人能读的一行；翻译不了返回 null。
 */
export function validationMessage(status: number, detail: unknown): string | null {
  if (typeof detail === "string" && detail.trim()) return `参数不合法（${status}）：${detail.trim()}`;
  if (Array.isArray(detail) && detail.length > 0) {
    const parts = detail.slice(0, 3).map((item) => {
      const record = item as { loc?: unknown; msg?: unknown };
      const field = Array.isArray(record.loc)
        ? record.loc.filter((part) => part !== "body").join(".")
        : "";
      const message = typeof record.msg === "string" && record.msg ? record.msg : "字段不合法";
      return field ? `${field}：${message}` : message;
    });
    return `参数不合法（${status}）：${parts.join("；")}`;
  }
  return null;
}

export async function apiRequest<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...init?.headers,
    },
  });

  const body = (await response.json().catch(() => null)) as
    | {
        data?: T;
        error?: { code?: string; message?: string; retryable?: boolean };
        detail?: unknown;
      }
    | null;

  if (!response.ok) {
    throw new ApiError(
      body?.error?.message ??
        validationMessage(response.status, body?.detail) ??
        `请求失败（${response.status}）`,
      {
        code: body?.error?.code,
        status: response.status,
        retryable: body?.error?.retryable,
      },
    );
  }

  return body?.data as T;
}