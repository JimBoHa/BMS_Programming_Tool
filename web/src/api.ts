import {
  decodeSourceResponse,
  prepareSourceRequest,
  sourceRequestStringify,
} from "./programSource";
let token = "";
export async function initSession() {
  const session = await api("/session");
  token = session.token;
  return session;
}
export async function api(
  path: string,
  body?: unknown,
  method?: string,
): Promise<any> {
  return (await request(path, body, method)).json();
}
/** Best-effort small lifecycle requests can finish while their document unloads. */
export async function apiKeepalive(path: string, body: unknown): Promise<any> {
  return (await request(path, body, undefined, { keepalive: true })).json();
}
export type JsonDocument<T = any> = { data: T; blob: Blob };
/** Keep authoritative JSON bytes when their numeric spelling is evidence. */
export async function apiJsonDocument<T = any>(
  path: string,
  body?: unknown,
): Promise<JsonDocument<T>> {
  const response = await request(path, body);
  const blob = await response.blob();
  return { data: JSON.parse(await blob.text()) as T, blob };
}
type RequestOptions = {
  program?: boolean;
  sourceResponse?: boolean;
  keepalive?: boolean;
};
export async function programApi(
  path: string,
  body?: unknown,
  method?: string,
  sourceResponse = false,
): Promise<any> {
  const response = await request(path, body, method, {
    program: true,
    sourceResponse,
  });
  const data = await response.json();
  return sourceResponse ? decodeSourceResponse(data) : data;
}
export const sourceApi = (path: string, body?: unknown, method?: string) =>
  programApi(path, body, method, true);
export async function programJsonDocument<T = any>(
  path: string,
  body?: unknown,
): Promise<JsonDocument<T>> {
  const response = await request(path, body, undefined, { program: true });
  const blob = await response.blob();
  return { data: JSON.parse(await blob.text()) as T, blob };
}
export async function programDownload(
  path: string,
  body: unknown,
  filename: string,
  shouldSave?: () => boolean,
) {
  const response = await request(path, body, undefined, { program: true });
  const blob = await response.blob();
  if (shouldSave && !shouldSave()) return false;
  saveBlob(blob, filename);
  return true;
}
async function request(
  path: string,
  body?: unknown,
  method?: string,
  options: RequestOptions = {},
) {
  const headers: Record<string, string> = {};
  if (token) headers["X-Studio-Token"] = token;
  if (options.sourceResponse) headers["X-Studio-Program-Source"] = "true";
  if (body !== undefined && !(body instanceof FormData))
    headers["Content-Type"] = "application/json";
  const response = await fetch("/api" + path, {
    method: method || (body === undefined ? "GET" : "POST"),
    headers,
    keepalive: options.keepalive,
    body:
      body === undefined
        ? undefined
        : body instanceof FormData
          ? body
          : options.program
            ? sourceRequestStringify(await prepareSourceRequest(body))
            : JSON.stringify(body),
  });
  if (!response.ok) {
    let message;
    try {
      const b = await response.json();
      message =
        typeof b.detail === "string" ? b.detail : JSON.stringify(b.detail);
    } catch {
      message = response.statusText;
    }
    throw new Error(message);
  }
  return response;
}
export async function download(
  path: string,
  body: unknown,
  filename: string,
  shouldSave?: () => boolean,
) {
  const response = await fetch("/api" + path, {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-Studio-Token": token },
    body: JSON.stringify(body),
  });
  if (!response.ok) {
    const data = await response.json();
    throw new Error(
      typeof data.detail === "string"
        ? data.detail
        : JSON.stringify(data.detail),
    );
  }
  const blob = await response.blob();
  if (shouldSave && !shouldSave()) return false;
  saveBlob(blob, filename);
  return true;
}
export async function downloadGet(
  path: string,
  filename: string,
  shouldSave?: () => boolean,
) {
  const response = await fetch("/api" + path, {
    headers: { "X-Studio-Token": token },
  });
  if (!response.ok) {
    let message = response.statusText;
    try {
      const data = await response.json();
      message =
        typeof data.detail === "string"
          ? data.detail
          : JSON.stringify(data.detail);
    } catch {
      /* Keep the HTTP failure if its body is not JSON. */
    }
    throw new Error(message);
  }
  const blob = await response.blob();
  if (shouldSave && !shouldSave()) return false;
  saveBlob(blob, filename);
  return true;
}
export function saveBlob(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
