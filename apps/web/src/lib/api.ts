const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
export interface CursorPage<T> {
  items: T[];
  next_cursor: string | null;
}
export async function request<T>(path:string, init?:RequestInit):Promise<T> {
  const isFormData = typeof FormData !== "undefined" && init?.body instanceof FormData;
  const res=await fetch(`${API}${path}`,{
    ...init,
    credentials:"include",
    headers:{...(isFormData ? {} : {"Content-Type":"application/json"}),...(init?.headers||{})},
  });
  if(!res.ok){
    let detail="请求失败";
    try { detail=(await res.json()).detail||detail; } catch { detail=`请求失败（HTTP ${res.status}）`; }
    throw new Error(detail);
  }
  return res.json() as Promise<T>;
}
export const apiUrl=API;
