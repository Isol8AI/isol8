import { useCallback, useEffect, useState } from 'react';
import { useAuth } from '@clerk/clerk-react';

export interface ApartmentAgent {
  agent_id: string;
  agent_name: string;
  display_name: string;
  character: string | null;
  current_location: string | null;
  current_activity: string | null;
  mood: string | null;
  energy: number;
  status_message: string | null;
  position_x: number;
  position_y: number;
  is_active: boolean;
}

export interface ActivityEvent {
  agent_name: string;
  display_name: string;
  event_type: string;
  description: string;
  location: string | null;
  timestamp: string;
}

export interface ApartmentData {
  agents: ApartmentAgent[];
  activity: ActivityEvent[];
}

const API_URL =
  (typeof import.meta !== 'undefined' && (import.meta as any).env?.VITE_BACKEND_URL) ??
  'http://localhost:8000/api/v1';

export function useApartment() {
  const { getToken, isSignedIn } = useAuth();
  const [data, setData] = useState<ApartmentData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchApartment = useCallback(async () => {
    if (!isSignedIn) {
      setData(null);
      setLoading(false);
      return;
    }

    try {
      const token = await getToken();
      const res = await fetch(`${API_URL}/town/apartment`, {
        headers: token ? { Authorization: `Bearer ${token}` } : {},
      });

      if (!res.ok) {
        if (res.status === 401) {
          setError('Not authenticated');
        } else {
          setError(`Failed to fetch apartment data (${res.status})`);
        }
        setData(null);
        setLoading(false);
        return;
      }

      const json = await res.json();
      setData(json);
      setError(null);
    } catch (err) {
      setError('Failed to connect to server');
      setData(null);
    } finally {
      setLoading(false);
    }
  }, [getToken, isSignedIn]);

  useEffect(() => {
    void fetchApartment();
    // Refresh every 10 seconds
    const interval = setInterval(fetchApartment, 10_000);
    return () => clearInterval(interval);
  }, [fetchApartment]);

  return { data, loading, error, refresh: fetchApartment };
}
