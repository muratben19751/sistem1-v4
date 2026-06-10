import { ReactNode } from 'react';

interface Props {
  children: ReactNode;
  className?: string;
  title?: ReactNode;
  action?: ReactNode;
}

export default function Card({ children, className = '', title, action }: Props) {
  return (
    <div className={`bg-gray-900 rounded-lg border border-gray-800 ${className}`}>
      {(title || action) && (
        <div className="flex items-center justify-between px-4 py-3 border-b border-gray-800">
          {title && <h3 className="text-sm font-medium text-gray-300">{title}</h3>}
          {action}
        </div>
      )}
      {children}
    </div>
  );
}
