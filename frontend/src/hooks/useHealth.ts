import { useEffect, useState } from 'react';
import { getHealth } from '../api/client';
import type { HealthResponse } from '../types';

export function useHealth() {
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let active = true;
    getHealth()
      .then((h) => {
        if (active) setHealth(h);
      })
      .catch(() => {
        if (active) setFailed(true);
      });
    return () => {
      active = false;
    };
  }, []);

  return { health, failed };
}
