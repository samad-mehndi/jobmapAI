'use client';

import dynamic from 'next/dynamic';

const JobMap = dynamic(() => import('@/components/JobMap'), { ssr: false });

export default function Home() {
  return (
    <main className="h-screen w-screen overflow-hidden">
      <JobMap />
    </main>
  );
}