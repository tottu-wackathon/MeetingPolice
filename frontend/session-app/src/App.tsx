import { BrowserRouter, Route, Routes } from 'react-router-dom';
import { SessionPage } from './pages/SessionPage';
import { PocPage } from './pages/PocPage';
import { PocSatominPage } from './pages/PocSatominPage';
import { ResultPage } from './pages/ResultPage';

function App() {
  console.log('📱 App component rendering...');
  console.log('  - Current URL:', window.location.href);
  console.log('  - User Agent:', navigator.userAgent);
  
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<SessionPage />} />
        <Route path="/session/:meetingId" element={<SessionPage />} />
        <Route path="/poc" element={<PocPage />} />
        <Route path="/poc_satomin" element={<PocSatominPage />} />
        <Route path="/result" element={<ResultPage />} />
      </Routes>
    </BrowserRouter>
  );
}

export default App;
