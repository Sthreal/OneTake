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

export async function apiRequest<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...init?.headers,
    },
  });

  const body = (await response.json().catch(() => null)) as
    | { data?: T; error?: { code?: string; message?: string; retryable?: boolean } }
    | null;

  if (!response.ok) {
    throw new ApiError(body?.error?.message ?? `请求失败（${response.status}）`, {
      code: body?.error?.code,
      status: response.status,
      retryable: body?.error?.retryable,
    });
  }

  return body?.data as T;
}