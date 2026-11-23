/** Typed API client for Haularr backend. */

const API_BASE = '/api/v1';

let authToken: string | null = null;

export function setAuthToken(token: string | null) {
  authToken = token;
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
    const error = await response.json().catch(() => ({ detail: response.statusText }));
    throw new Error(error.detail || `HTTP ${response.status}`);
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
    list: () => api.get<any[]>('/sources'),
    get: (id: string) => api.get<any>(`/sources/${id}`),
    create: (data: any) => api.post<any>('/sources', data),
    update: (id: string, data: any) => api.patch<any>(`/sources/${id}`, data),
    delete: (id: string) => api.delete(`/sources/${id}`),
    testConfig: (data: { adapter_type: string; connection_config: Record<string, any>; credential: string }) =>
      api.post<any>('/sources/test-config', data),
    test: (id: string) => api.post<any>(`/sources/${id}/test`),
    scan: (id: string) => api.post<any>(`/sources/${id}/scan`),
    completeOnboarding: (id: string) => api.post<any>(`/sources/${id}/complete-onboarding`),
    labels: {
      list: (sourceId: string) => api.get<any[]>(`/sources/${sourceId}/labels`),
      create: (sourceId: string, data: any) => api.post<any>(`/sources/${sourceId}/labels`, data),
      update: (sourceId: string, ruleId: string, data: any) =>
        api.patch<any>(`/sources/${sourceId}/labels/${ruleId}`, data),
      delete: (sourceId: string, ruleId: string) =>
        api.delete(`/sources/${sourceId}/labels/${ruleId}`),
    },
  },
  sourceItems: {
    list: (params?: Record<string, string>) => {
      const qs = params ? '?' + new URLSearchParams(params).toString() : '';
      return api.get<{ items: any[]; total: number; offset: number; limit: number }>(`/source-items${qs}`);
    },
    get: (id: string) => api.get<any>(`/source-items/${id}`),
    recheck: (id: string) => api.post<any>(`/source-items/${id}/recheck`),
    ignore: (id: string) => api.post<any>(`/source-items/${id}/ignore`),
    queue: (id: string, force: boolean = false) =>
      api.post<{ job_id: string; status: string; stage: string }>(`/source-items/${id}/queue`, { force_transfer: force }),
    bulkQueue: (ids: string[], force: boolean = false) =>
      api.post<any>('/source-items/bulk-queue', { source_item_ids: ids, force_transfer: force }),
  },
  jobs: {
    list: (params?: Record<string, string>) => {
      const qs = params ? '?' + new URLSearchParams(params).toString() : '';
      return api.get<{ items: any[]; total: number; offset: number; limit: number }>(`/jobs${qs}`);
    },
    get: (id: string) => api.get<any>(`/jobs/${id}`),
    events: (id: string) => api.get<any[]>(`/jobs/${id}/events`),
    pause: (id: string) => api.post<any>(`/jobs/${id}/pause`),
    resume: (id: string) => api.post<any>(`/jobs/${id}/resume`),
    retry: (id: string) => api.post<any>(`/jobs/${id}/retry`),
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
    list: () => api.get<any[]>('/libraries'),
    get: (id: string) => api.get<any>(`/libraries/${id}`),
    create: (data: any) => api.post<any>('/libraries', data),
    update: (id: string, data: any) => api.patch<any>(`/libraries/${id}`, data),
    delete: (id: string) => api.delete(`/libraries/${id}`),
    test: (id: string) => api.post<any>(`/libraries/${id}/test`),
  },
  settings: {
    get: () => api.get<any>('/settings'),
    patch: (data: any) => api.patch<any>('/settings', data),
  },
  dashboard: {
    get: () => api.get<any>('/dashboard'),
  },
};
