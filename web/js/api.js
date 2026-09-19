// 极简 API 客户端
export class ApiError extends Error {
  constructor(message, status, data) {
    super(message);
    this.status = status;
    this.data = data;
  }
}

let unauthorizedHandler = null;
export function onUnauthorized(fn) { unauthorizedHandler = fn; }

async function request(method, path, { body, params } = {}) {
  const url = new URL(path, location.origin);
  if (params) {
    for (const [k, v] of Object.entries(params)) {
      if (v === undefined || v === null || v === '') continue;
      url.searchParams.set(k, v);
    }
  }
  const res = await fetch(url, {
    method,
    headers: body ? { 'Content-Type': 'application/json' } : undefined,
    body: body ? JSON.stringify(body) : undefined,
    credentials: 'same-origin',
  });

  if (res.status === 401) {
    unauthorizedHandler?.();
    throw new ApiError('登录已失效', 401);
  }

  const text = await res.text();
  let data = null;
  if (text) {
    try { data = JSON.parse(text); } catch { data = { detail: text }; }
  }
  if (!res.ok) {
    const msg = (data && (data.detail || data.message)) || `请求失败（${res.status}）`;
    throw new ApiError(typeof msg === 'string' ? msg : JSON.stringify(msg), res.status, data);
  }
  return data;
}

export const api = {
  get:   (p, params) => request('GET', p, { params }),
  post:  (p, body)   => request('POST', p, { body }),
  patch: (p, body)   => request('PATCH', p, { body }),
  put:   (p, body)   => request('PUT', p, { body }),
  del:   (p, params) => request('DELETE', p, { params }),
};
