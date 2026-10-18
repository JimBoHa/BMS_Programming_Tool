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
  const headers: Record<string, string> = {};
  if (token) headers["X-Studio-Token"] = token;
  if (body !== undefined && !(body instanceof FormData))
    headers["Content-Type"] = "application/json";
  const response = await fetch("/api" + path, {
    method: method || (body === undefined ? "GET" : "POST"),
    headers,
    body:
      body === undefined
        ? undefined
        : body instanceof FormData
          ? body
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
  return response.json();
}
export async function download(path: string, body: unknown, filename: string) {
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
  saveBlob(await response.blob(), filename);
}
export function saveBlob(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
