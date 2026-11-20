import {defineConfig,devices} from '@playwright/test';
export default defineConfig({testDir:'./e2e',workers:1,fullyParallel:false,timeout:180000,expect:{timeout:15000},reporter:[['list'],['html',{open:'never'}]],use:{baseURL:'http://localhost:5174',trace:'retain-on-failure',screenshot:'only-on-failure',...devices['Desktop Chrome'],channel:'chrome'},projects:[{name:'chromium'}]});



