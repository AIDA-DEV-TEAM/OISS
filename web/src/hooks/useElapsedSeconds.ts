import { useEffect, useState } from 'react';

/** Whole seconds since `running` became true; 0 while it is false. */
export function useElapsedSeconds(running: boolean): number {
  const [seconds, setSeconds] = useState(0);

  useEffect(() => {
    setSeconds(0);
    if (!running) return undefined;
    const started = Date.now();
    const timer = setInterval(() => {
      setSeconds(Math.floor((Date.now() - started) / 1000));
    }, 1000);
    return () => clearInterval(timer);
  }, [running]);

  return seconds;
}
