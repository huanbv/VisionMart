import axios, {
  AxiosError,
  AxiosInstance,
  AxiosRequestConfig,
  InternalAxiosRequestConfig,
} from "axios";

const ACCESS_KEY = "vm.access_token";
const REFRESH_KEY = "vm.refresh_token";

export const tokenStore = {
  getAccess: () => localStorage.getItem(ACCESS_KEY),
  getRefresh: () => localStorage.getItem(REFRESH_KEY),
  set: (access: string, refresh: string) => {
    localStorage.setItem(ACCESS_KEY, access);
    localStorage.setItem(REFRESH_KEY, refresh);
  },
  clear: () => {
    localStorage.removeItem(ACCESS_KEY);
    localStorage.removeItem(REFRESH_KEY);
  },
};

const baseURL = import.meta.env.VITE_API_BASE_URL ?? "/api/v1";

/**
 * Timeout cho request tải file lên.
 *
 * 15 giây (mặc định bên dưới) là hợp lý cho API thường, nhưng QUÁ NGẮN cho
 * upload: một video demo 116 MB trên đường truyền hộ gia đình cần hàng
 * chục giây tới vài phút. Khi axios hết giờ, nó huỷ kết nối và nginx ghi
 * 499 (client closed request) — backend thậm chí CHƯA nhận được request,
 * nên log server sạch trơn và lỗi trông như "tải lên thất bại" không rõ
 * nguyên nhân. Đã gặp đúng tình huống này trên production.
 *
 * 10 phút đủ cho 200 MB (giới hạn phía server) ở tốc độ chậm.
 */
export const UPLOAD_TIMEOUT_MS = 10 * 60 * 1000;

export const apiClient: AxiosInstance = axios.create({
  baseURL,
  timeout: 15000,
});

apiClient.interceptors.request.use((config: InternalAxiosRequestConfig) => {
  const token = tokenStore.getAccess();
  if (token) {
    config.headers.set("Authorization", `Bearer ${token}`);
  }
  return config;
});

type RetriableConfig = AxiosRequestConfig & { _retry?: boolean };

let refreshPromise: Promise<string> | null = null;

function refreshAccessTokenOnce(): Promise<string> {
  if (!refreshPromise) {
    refreshPromise = refreshAccessToken().finally(() => {
      refreshPromise = null;
    });
  }
  return refreshPromise;
}

async function refreshAccessToken(): Promise<string> {
  const refresh = tokenStore.getRefresh();
  if (!refresh) throw new Error("No refresh token");
  const resp = await axios.post(`${baseURL}/auth/refresh`, {
    refresh_token: refresh,
  });
  tokenStore.set(resp.data.access_token, resp.data.refresh_token);
  return resp.data.access_token as string;
}

export async function ensureAccessTokenFresh(): Promise<void> {
  if (!tokenStore.getRefresh()) return;
  await refreshAccessTokenOnce();
}

/** Turn FastAPI/axios error payloads into a single user-facing string. */
export function formatApiErrorDetail(error: unknown, fallback: string): string {
  if (!error || typeof error !== "object" || !("response" in error)) return fallback;
  const detail = (error as { response?: { data?: { detail?: unknown } } }).response?.data
    ?.detail;
  if (typeof detail === "string" && detail.trim()) return detail;
  if (Array.isArray(detail)) {
    const parts = detail
      .map((item) => {
        if (item && typeof item === "object" && "msg" in item) {
          return String((item as { msg: unknown }).msg);
        }
        return String(item);
      })
      .filter(Boolean);
    if (parts.length) return parts.join("; ");
  }
  if (error instanceof AxiosError && error.message) return error.message;
  return fallback;
}

apiClient.interceptors.response.use(
  (r) => r,
  async (error: AxiosError) => {
    const original = error.config as RetriableConfig | undefined;
    const status = error.response?.status;
    if (status !== 401 || !original || original._retry) {
      return Promise.reject(error);
    }
    if (original.url?.includes("/auth/login") || original.url?.includes("/auth/refresh")) {
      return Promise.reject(error);
    }
    original._retry = true;
    try {
      const newToken = await refreshAccessTokenOnce();
      original.headers = original.headers ?? {};
      (original.headers as Record<string, string>)["Authorization"] = `Bearer ${newToken}`;
      return apiClient.request(original);
    } catch (refreshErr) {
      tokenStore.clear();
      window.location.assign("/login");
      return Promise.reject(refreshErr);
    }
  },
);
