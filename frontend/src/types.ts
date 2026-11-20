export type User = {id:number;name:string;email:string;role:'PATIENT'|'DOCTOR'|'ADMIN';doctor_status?:string};
export type Clinic = {id:number;name:string;location:string;timezone:string};
export type Doctor = {id:number;name:string;specialization_id:number;specialization:string;qualifications:string;experience:number;fee:number;biography:string;status:string;clinics:Clinic[]};
export type Appointment = {id:number;doctor_id:number;clinic_id:number;patient_name:string;doctor_name:string;clinic_name:string;timezone:string;starts_at:string;ends_at:string;status:string;history?:{status:string;occurred_at:string}[]};
export type Slot = {starts_at:string;ends_at:string;clinic_id:number;timezone:string};
export type Catalog = {clinics:Clinic[];specializations:{id:number;name:string}[]};
export type Rule = {clinic_id:number;weekday:number;start_minute:number;end_minute:number;duration:number};
export type Page<T> = {items:T[];total:number;page:number};
