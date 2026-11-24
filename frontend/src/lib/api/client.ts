/** Typed API client for Haularr backend. */

const API_BASE = '/api/v1';

import { goto } from '$app/navigation';

const TOKEN_KEY = 'haularr_token';

function loadToken(): string | null {
  try {
    return localStorage.getItem(TOKEN_KEY);
  } catch {
    return null;
  }
}

let authToken: string | null = loadToken();

export function getAuthToken() {
  return authToken;
}

export function setAuthToken(token: string | null) {
  authToken = token;
  try {
    if (token) localStorage.setItem(TOKEN_KEY, token);
    else localStorage.removeItem(TOKEN_KEY);
  } catch {
    /* storage unavailable: token lives in memory only */
  }
}

function getHeaders(): Record<string, string> {
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
  };
  if (authToken) {
    headers['Authorization'] = `Bearer ${authToken}`;
  }
  return headers;
}

async function apiFetch<T>(
  path: string,
  options: RequestInit = {},
): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    ...options,
    headers: { ...getHeaders(), ...options.headers },
  });
  if (!response.ok) {
    if (response.status === 401 && !path.startsWith('/auth/')) {
      setAuthToken(null);
      goto('/login/');
    }
    const error = await response.json().catch(() => ({ detail: response.statusText }));
    const d = error.detail;
    const msg = Array.isArray(d)
      ? d.map((x: any) => x?.msg ?? JSON.stringify(x)).join('; ')
      : typeof d === 'string'
        ? d
        : d
          ? JSON.stringify(d)
          : '';
    throw new Error(msg || `HTTP ${response.status}`);
  }
  if (response.status === 204) {
    return {} as T;
  }
  return response.json();
}

export const api = {
  get: <T>(path: string) => apiFetch<T>(path, { method: 'GET' }),
  post: <T>(path: string, body?: unknown) =>
    apiFetch<T>(path, {
      method: 'POST',
      body: body ? JSON.stringify(body) : undefined,
    }),
  patch: <T>(path: string, body?: unknown) =>
    apiFetch<T>(path, {
      method: 'PATCH',
      body: body ? JSON.stringify(body) : undefined,
    }),
  delete: <T>(path: string) => apiFetch<T>(path, { method: 'DELETE' }),
};

export interface PathMapping { source_prefix: string; remote_prefix: string }
/** Fetch config as returned by the API (password never returned). */
export interface Fetch {
  host: string;
  port: number;
  username: string;
  tls_verify: boolean;
  path_mappings: PathMapping[];
  has_password: boolean;
}
/** Fetch config as sent on POST/PATCH (password required). */
export type FetchInput = Omit<Fetch, 'has_password'> & { password: string };

export interface Source {
  id: string;
  name: string;
  adapter_type: string;
  enabled: boolean;
  connection_config: Record<string, any>;
  has_credential: boolean;
  default_transfer_id: string | null;
  poll_interval: number;
  onboarding_state: string;
  initial_scan_at: string | null;
  last_scan_at: string | null;
  last_scan_error: string | null;
  created_at: string | null;
  fetch: Fetch | null;
}

export interface LabelRule {
  id: string;
  source_id: string;
  label: string;
  priority: number;
  enabled: boolean;
  automatic_processing: boolean;
  temporary_directory: string;
  completed_directory: string;
  library_instance_id: string | null;
  transfer_override_id: string | null;
  retention_days: number | null;
}

export interface Library {
  id: string;
  name: string;
  adapter_type: string;
  base_url: string;
  api_key_secret_ref: string | null;
  enabled: boolean;
  options: Record<string, any>;
}

/** Library as sent on POST/PATCH; api_key_secret_ref carries the raw key (omit on PATCH to keep). */
export interface LibraryInput {
  name: string;
  adapter_type: 'sonarr' | 'radarr';
  base_url: string;
  api_key_secret_ref: string;
  enabled?: boolean;
  options?: Record<string, any>;
}

export interface Job {
  id: string;
  status: string;
  error_code?: string | null;
  error_detail?: string | null;
  stage: string;
  title: string | null;
  library_name: string | null;
  config_snapshot: Record<string, any>;
  created_at: string | null;
  ended_at: string | null;
}

export interface LogEntry {
  timestamp: string;
  level: string;
  logger: string;
  message: string;
  exception?: string | null;
}

export interface LogsResponse {
  entries: LogEntry[];
  total: number;
  capacity: number;
}

type Page<T> = { items: T[]; total: number; offset: number; limit: number };

function qs(params: Record<string, string | number | undefined>): string {
  const p = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) if (v !== undefined && v !== '') p.set(k, String(v));
  const s = p.toString();
  return s ? '?' + s : '';
}

// API endpoints
export const endpoints = {
  health: () => api.get<{ status: string; database: string; version: string }>('/health'),
  auth: {
    login: (username: string, password: string) =>
      api.post<{ access_token: string; token_type: string; username: string }>('/auth/login', { username, password }),
    setup: (username: string, password: string) =>
      api.post<{ access_token: string; token_type: string; username: string }>('/auth/setup', { username, password }),
    me: () => api.get<{ username: string }>('/auth/me'),
  },
  sources: {
    list: () => api.get<Source[]>('/sources'),
    get: (id: string) => api.get<Source>(`/sources/${id}`),
    create: (data: Record<string, any> & { fetch?: FetchInput }) => api.post<Source>('/sources', data),
    update: (id: string, data: Record<string, any> & { fetch?: FetchInput }) =>
      api.patch<Source>(`/sources/${id}`, data),
    delete: (id: string) => api.delete(`/sources/${id}`),
    testConfig: (data: { adapter_type: string; connection_config: Record<string, any>; credential: string }) =>
      api.post<any>('/sources/test-config', data),
    test: (id: string) => api.post<any>(`/sources/${id}/test`),
    fetchTest: (data: FetchInput & { source_id?: string }) => api.post<any>('/sources/fetch-test', data),
    scan: (id: string) => api.post<any>(`/sources/${id}/scan`),
    completeOnboarding: (id: string) => api.post<any>(`/sources/${id}/complete-onboarding`),
    labels: {
      list: (sourceId: string) => api.get<LabelRule[]>(`/sources/${sourceId}/labels`),
      create: (sourceId: string, data: Partial<LabelRule>) =>
        api.post<LabelRule>(`/sources/${sourceId}/labels`, data),
      update: (sourceId: string, ruleId: string, data: Partial<LabelRule>) =>
        api.patch<LabelRule>(`/sources/${sourceId}/labels/${ruleId}`, data),
      delete: (sourceId: string, ruleId: string) =>
        api.delete(`/sources/${sourceId}/labels/${ruleId}`),
    },
  },
  sourceItems: {
    list: (params?: Record<string, string>) =>
      api.get<Page<any>>(`/source-items${qs(params ?? {})}`),
    skipped: (p: { offset?: number; limit?: number } = {}) =>
      api.get<Page<any>>(
        `/source-items${qs({ eligibility: 'already_available', has_job: 'false', ...p })}`,
      ),
    get: (id: string) => api.get<any>(`/source-items/${id}`),
    recheck: (id: string) => api.post<any>(`/source-items/${id}/recheck`),
    ignore: (id: string) => api.post<any>(`/source-items/${id}/ignore`),
    queue: (id: string, force: boolean = false) =>
      api.post<{ job_id: string; status: string; stage: string }>(`/source-items/${id}/queue`, { force_transfer: force }),
    bulkQueue: (ids: string[], force: boolean = false) =>
      api.post<any>('/source-items/bulk-queue', { source_item_ids: ids, force_transfer: force }),
  },
  jobs: {
    list: (p: { status?: string[]; sort?: 'newest' | 'attention'; offset?: number; limit?: number } = {}) =>
      api.get<Page<Job>>(`/jobs${qs({ ...p, status: p.status?.join(',') })}`),
    get: (id: string) => api.get<Job>(`/jobs/${id}`),
    events: (id: string) => api.get<any[]>(`/jobs/${id}/events`),
    pause: (id: string) => api.post<any>(`/jobs/${id}/pause`),
    resume: (id: string) => api.post<any>(`/jobs/${id}/resume`),
    retry: (id: string) => api.post<any>(`/jobs/${id}/retry`),
    restart: (id: string) => api.post<any>(`/jobs/${id}/restart`),
    cancel: (id: string) => api.post<any>(`/jobs/${id}/cancel`),
    retryImport: (id: string) => api.post<any>(`/jobs/${id}/retry-import`),
  },
  transfers: {
    list: () => api.get<any[]>('/transfers'),
    get: (id: string) => api.get<any>(`/transfers/${id}`),
    create: (data: any) => api.post<any>('/transfers', data),
    update: (id: string, data: any) => api.patch<any>(`/transfers/${id}`, data),
    delete: (id: string) => api.delete(`/transfers/${id}`),
    test: (id: string) => api.post<any>(`/transfers/${id}/test`),
    addEndpoint: (id: string, data: any) => api.post<any>(`/transfers/${id}/endpoints`, data),
  },
  libraries: {
    list: () => api.get<Library[]>('/libraries'),
    get: (id: string) => api.get<Library>(`/libraries/${id}`),
    create: (data: LibraryInput) => api.post<Library>('/libraries', data),
    update: (id: string, data: Partial<Omit<LibraryInput, 'adapter_type'>>) =>
      api.patch<Library>(`/libraries/${id}`, data),
    delete: (id: string) => api.delete(`/libraries/${id}`),
    test: (id: string) => api.post<any>(`/libraries/${id}/test`),
    testConfig: (data: { adapter_type: string; base_url: string; api_key: string; library_id?: string }) =>
      api.post<any>('/libraries/test-config', data),
  },
  settings: {
    get: () => api.get<any>('/settings'),
    patch: (data: any) => api.patch<any>('/settings', data),
    update: (data: any) => api.patch<any>('/settings', data),
  },
  config: {
    export: () => api.get<unknown>('/config/export'),
  },
  dashboard: {
    get: () => api.get<any>('/dashboard'),
  },
  logs: {
    list: (p: { level?: string; search?: string; limit?: number } = {}) =>
      api.get<LogsResponse>(`/logs${qs(p)}`),
  },
};
