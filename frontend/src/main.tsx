import React from 'react';
import ReactDOM from 'react-dom/client';
import {BrowserRouter,Route,Routes} from 'react-router-dom';
import {QueryClient,QueryClientProvider} from '@tanstack/react-query';
import {AuthProvider,ErrorBoundary,Layout,Protected,ToastProvider} from './components';
import {AuthPage,Landing} from './pages/Public';
import {DoctorDetail,Doctors} from './pages/Doctors';
import {AppointmentDetail,AppointmentList} from './pages/Appointments';
import {Analytics,Dashboard} from './pages/Dashboard';
import {AdminDoctors,Clinics,Profile,SchedulePage} from './pages/Management';
import './styles.css';

const client=new QueryClient({defaultOptions:{queries:{retry:1,refetchOnWindowFocus:true}}});
ReactDOM.createRoot(document.getElementById('root')!).render(
 <React.StrictMode><ErrorBoundary><QueryClientProvider client={client}><BrowserRouter><AuthProvider><ToastProvider>
 <Routes><Route element={<Layout/>}>
  <Route index element={<Landing/>}/><Route path="login" element={<AuthPage/>}/><Route path="register" element={<AuthPage registerMode/>}/>
  <Route path="doctors" element={<Doctors/>}/><Route path="doctors/:id" element={<DoctorDetail/>}/>
  <Route element={<Protected/>}><Route path="dashboard" element={<Dashboard/>}/><Route path="appointments" element={<AppointmentList/>}/><Route path="appointments/:id" element={<AppointmentDetail/>}/><Route path="profile" element={<Profile/>}/></Route>
  <Route element={<Protected roles={['DOCTOR']}/>}><Route path="schedule" element={<SchedulePage/>}/><Route path="queue" element={<AppointmentList queue/>}/></Route>
  <Route element={<Protected roles={['ADMIN']}/>}><Route path="admin/doctors" element={<AdminDoctors/>}/><Route path="admin/clinics" element={<Clinics/>}/><Route path="admin/analytics" element={<Analytics/>}/></Route>
  <Route path="*" element={<div className="empty"><h1>Page not found</h1><a href="/">Return home</a></div>}/>
 </Route></Routes>
 </ToastProvider></AuthProvider></BrowserRouter></QueryClientProvider></ErrorBoundary></React.StrictMode>
);
