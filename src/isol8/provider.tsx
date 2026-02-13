import React, { createContext, useEffect, useMemo } from 'react';
import { Isol8Client, Isol8ClientConfig } from './client';

export const Isol8Context = createContext<Isol8Client | null>(null);

interface Isol8ProviderProps {
  config: Isol8ClientConfig;
  children: React.ReactNode;
}

export function Isol8Provider({ config, children }: Isol8ProviderProps) {
  const client = useMemo(() => new Isol8Client(config), [config]);

  useEffect(() => {
    client.connect();
    return () => client.disconnect();
  }, [client]);

  return <Isol8Context.Provider value={client}>{children}</Isol8Context.Provider>;
}
