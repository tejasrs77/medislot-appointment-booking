let refreshFlight: Promise<Response> | null = null;
export function csrf() { return decodeURIComponent(document.cookie.split('; ').find(c=>c.startsWith('csrf='))?.slice(5) || ''); }
export async function api<T = any>(path:string, options:RequestInit = {}, retry=true):Promise<T> {
  const response = await fetch('/api/v1'+path,{...options,credentials:'include',headers:{'Content-Type':'application/json','X-CSRF-Token':csrf(),...options.headers}});
  if(response.status===401 && retry && !['/auth/login','/auth/register','/auth/refresh','/auth/logout'].includes(path)) {
    refreshFlight ??= fetch('/api/v1/auth/refresh',{method:'POST',credentials:'include',headers:{'X-CSRF-Token':csrf()}}).finally(()=>{refreshFlight=null;});
    if((await refreshFlight).ok) return api<T>(path,options,false);
  }
  const body=await response.json();
  if(!response.ok) throw new Error(body.error?.fields?.map((f:any)=>f.message).join('; ') || body.error?.message || 'Request failed');
  return body as T;
}
export const send = <T=any>(path:string,method:string,data?:unknown,headers?:Record<string,string>) => api<T>(path,{method,body:data===undefined?undefined:JSON.stringify(data),headers});
export const localDate = (offset=0) => { const d=new Date(); d.setDate(d.getDate()+offset); return `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}-${String(d.getDate()).padStart(2,'0')}`; };
export const dateTime = (value:string,zone:string) => new Intl.DateTimeFormat('en-IN',{dateStyle:'medium',timeStyle:'short',timeZone:zone}).format(new Date(value));
export const slotTime = (value:string,zone:string) => new Intl.DateTimeFormat('en-IN',{hour:'numeric',minute:'2-digit',timeZone:zone}).format(new Date(value));
