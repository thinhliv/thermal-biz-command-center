import { useCallback, useEffect, useState } from 'react';

/** Chế độ TV kiosk: bật/tắt toàn màn hình và theo dõi trạng thái thật của trình duyệt. */
export function useFullscreen(): { active: boolean; toggle: () => void } {
  const [active, setActive] = useState(false);

  useEffect(() => {
    const sync = () => setActive(document.fullscreenElement !== null);
    document.addEventListener('fullscreenchange', sync);
    sync();
    return () => document.removeEventListener('fullscreenchange', sync);
  }, []);

  const toggle = useCallback(() => {
    if (document.fullscreenElement) void document.exitFullscreen();
    else void document.documentElement.requestFullscreen();
  }, []);

  return { active, toggle };
}
