import React from 'react';
import {createRoot} from 'react-dom/client';
import './style.css';
import {useAppController} from './chat/useAppController';
import {AppView} from './components/AppView';
export {MessageProgress} from './components/MessageProgress';
export function App(){const controller=useAppController();return <AppView {...controller}/>;}
createRoot(document.getElementById('root')!).render(<React.StrictMode><App/></React.StrictMode>);
