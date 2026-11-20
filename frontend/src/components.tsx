import {Component, createContext, useContext, useEffect, useRef, useState, type ReactNode} from 'react';
import {useQuery, useQueryClient} from '@tanstack/react-query';
import {Link, Navigate, Outlet, useLocation, useNavigate} from 'react-router-dom';
import {Activity, CalendarDays, LayoutDashboard, LogOut, Menu, Search, Settings, ShieldCheck, Stethoscope, Users, X} from 'lucide-react';
import {api, send} from './api';
import type {User} from './types';

const AuthContext=createContext<{user:User|null;loading:boolean;reload:()=>Promise<unknown>}>({user:null,loading:true,reload:async()=>{}});
export function AuthProvider({children}:{children:ReactNode}) {
 const query=useQuery({queryKey:['me'],queryFn:async()=>{try{return await api<User>('/auth/me');}catch{return null;}},retry:false,staleTime:60000});
 return <AuthContext.Provider value={{user:query.data??null,loading:query.isPending,reload:query.refetch}}>{children}</AuthContext.Provider>;
}
export const useAuth=()=>useContext(AuthContext);
const ToastContext=createContext<(s:string)=>void>(()=>{});
export function ToastProvider({children}:{children:ReactNode}) {const [message,setMessage]=useState('');useEffect(()=>{if(message){const timer=setTimeout(()=>setMessage(''),5000);return()=>clearTimeout(timer);}},[message]);return <ToastContext.Provider value={setMessage}>{children}{message&&<div className="toast" role="status">{message}<button aria-label="Dismiss notification" onClick={()=>setMessage('')}><X size={18}/></button></div>}</ToastContext.Provider>;}
export const useToast=()=>useContext(ToastContext);
export function Loading(){return <div aria-label="Loading" className="skeletons"><div/><div/><div/></div>;}
export function ErrorBox({error}:{error:unknown}){return error?<p className="error" role="alert">{error instanceof Error?error.message:String(error)}</p>:null;}
export function Empty({title='Nothing here yet',children}:{title?:string;children?:ReactNode}){return <div className="empty"><CalendarDays size={32}/><h3>{title}</h3><p>{children??'Your appointments will appear here when you book a visit.'}</p></div>;}
export function Badge({status}:{status:string}){return <span className={'badge '+status.toLowerCase()}>{status.replaceAll('_',' ')}</span>;}
export function PageTitle({eyebrow,title,description,children}:{eyebrow?:string;title:string;description?:string;children?:ReactNode}){return <div className="page-title"><div><p className="eyebrow">{eyebrow??'YOUR CARE, CONNECTED'}</p><h1>{title}</h1>{description&&<p>{description}</p>}</div>{children}</div>;}
export function Pagination({page,total,size=20,onChange}:{page:number;total:number;size?:number;onChange:(p:number)=>void}) {return <div className="pagination"><span>{total} results · Page {page} of {Math.max(1,Math.ceil(total/size))}</span><button className="secondary" disabled={page===1} onClick={()=>onChange(page-1)}>Previous</button><button className="secondary" disabled={page*size>=total} onClick={()=>onChange(page+1)}>Next</button></div>;}
export function Confirm({title,children,onCancel,onConfirm,busy}:{title:string;children:ReactNode;onCancel:()=>void;onConfirm:()=>void;busy:boolean}) {
 const ref=useRef<HTMLDialogElement>(null);
 useEffect(()=>{ref.current?.showModal();const el=ref.current;return()=>el?.close();},[]);
 return <dialog ref={ref} onCancel={e=>{e.preventDefault();if(!busy)onCancel();}}><h2>{title}</h2><p>{children}</p><div className="actions"><button className="secondary" disabled={busy} onClick={onCancel}>Keep appointment</button><button disabled={busy} onClick={onConfirm}>{busy?'Saving…':'Confirm cancellation'}</button></div></dialog>;
}
export function Protected({roles}:{roles?:string[]}) {const {user,loading}=useAuth();const location=useLocation();if(loading)return <Loading/>;if(!user)return <Navigate to="/login" state={{from:location.pathname+location.search}} replace/>;if(roles&&!roles.includes(user.role))return <Navigate to="/dashboard" replace/>;return <Outlet/>;}
export function Layout(){const {user,reload}=useAuth();const navigate=useNavigate();const client=useQueryClient();const toast=useToast();const location=useLocation();const [open,setOpen]=useState(false);const links=user?[
 ['/dashboard','Overview',LayoutDashboard],['/appointments','Appointments',CalendarDays],
 ...(user.role==='PATIENT'?[['/doctors','Find a doctor',Search]]:[]),
 ...(user.role==='DOCTOR'?[['/schedule','My availability',CalendarDays],['/queue','Patient queue',Users]]:[]),
 ...(user.role==='ADMIN'?[['/admin/doctors','Doctor management',Stethoscope],['/admin/clinics','Clinics',ShieldCheck],['/admin/analytics','Analytics',Activity]]:[]),
 ['/profile','My profile',Settings]
 ]:[];
 async function logout(){try{await send('/auth/logout','POST');client.clear();await reload();navigate('/');}catch(e){toast((e as Error).message);}}
 return <div className={user?'app-shell':'public-shell'}><a className="skip" href="#main">Skip to content</a><header className="topbar"><Link className="brand" to={user?'/dashboard':'/'}><span className="brand-mark"><Activity size={24}/></span>MediSlot<span className="brand-dot">.</span></Link><nav aria-label="Main navigation">{!user&&<><Link to="/doctors">Find a doctor</Link><Link to="/login">Sign in</Link><Link className="button" to="/register">Get started</Link></>}{user&&<><span className="top-role">{user.role.toLowerCase()} workspace</span><span className="avatar small">{user.name.slice(0,1)}</span><span className="username">{user.name}</span><button className="icon-button mobile-menu" aria-label="Toggle navigation" onClick={()=>setOpen(!open)}><Menu/></button></>}</nav></header>{user&&<aside className={open?'sidebar open':'sidebar'}><p className="nav-label">WORKSPACE</p><nav aria-label="Workspace navigation">{links.map(([path,label,Icon])=>{const I=Icon as typeof Activity;return <Link key={path as string} className={location.pathname===path?'active':''} to={path as string} onClick={()=>setOpen(false)}><I size={19}/>{label as string}</Link>;})}</nav><div className="sidebar-bottom"><div className="demo-note"><ShieldCheck size={20}/><strong>Development workspace</strong><p>Fictional people. Real scheduling.</p></div><button className="logout" onClick={logout}><LogOut size={18}/> Sign out</button></div></aside>}<main id="main"><Outlet/></main><footer>© {new Date().getFullYear()} MediSlot · Synthetic demonstration data</footer></div>;
}
export class ErrorBoundary extends Component<{children:ReactNode},{failed:boolean}>{state={failed:false};static getDerivedStateFromError(){return {failed:true};}render(){return this.state.failed?<div className="empty"><h1>Something went wrong</h1><p>Reload to reconnect to your workspace.</p><button onClick={()=>window.location.reload()}>Reload application</button></div>:this.props.children;}}
