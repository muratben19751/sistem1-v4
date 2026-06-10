import { useEffect } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import { useIsPhone } from '../hooks/useMediaQuery';
import { isForceDesktop } from './forceDesktop';

export default function MobileRedirect() {
  const isPhone = useIsPhone();
  const location = useLocation();
  const navigate = useNavigate();

  useEffect(() => {
    if (!isPhone) return;
    if (location.pathname.startsWith('/m')) return;
    if (isForceDesktop()) return;
    navigate('/m', { replace: true });
  }, [isPhone, location.pathname, navigate]);

  return null;
}
