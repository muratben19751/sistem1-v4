import { ReactNode } from 'react';

interface Props {
  title: string;
  children: ReactNode;
}

export default function PageLayout({ title, children }: Props) {
  return (
    <div className="p-6">
      <h2 className="text-xl font-semibold text-white mb-6">{title}</h2>
      {children}
    </div>
  );
}
