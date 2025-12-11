import React from 'react';
import ReactDOM from 'react-dom/client';
import App from './App';
import './styles.css';

console.log('🚀 Frontend starting up...');
console.log('  - React version:', React.version);
console.log('  - Document ready state:', document.readyState);
console.log('  - Root element exists:', !!document.getElementById('root'));

ReactDOM.createRoot(document.getElementById('root') as HTMLElement).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
);

console.log('✅ Frontend initialized');
