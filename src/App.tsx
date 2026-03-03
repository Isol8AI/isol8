import { Routes, Route } from 'react-router-dom';
import Town from './pages/Town.tsx';
import Apartment from './pages/Apartment.tsx';

export default function App() {
  return (
    <Routes>
      <Route path="/" element={<Town />} />
      <Route path="/apartment" element={<Apartment />} />
    </Routes>
  );
}
