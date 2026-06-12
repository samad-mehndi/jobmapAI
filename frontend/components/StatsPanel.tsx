'use client';

import {
  BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer,
  PieChart, Pie, Cell, Legend
} from 'recharts';

const COLORS = ['#3B82F6', '#8B5CF6', '#EC4899', '#10B981', '#F59E0B'];

interface Props {
  stats: any;
}

export default function StatsPanel({ stats }: Props) {
  if (!stats) return (
    <div className="p-4 text-gray-400 text-sm">Loading stats...</div>
  );

  return (
    <div className="p-4 text-white">
      <h2 className="text-lg font-semibold mb-4">DFW Tech Job Market</h2>

      <div className="mb-6">
        <div className="text-xs text-gray-400 mb-2">Top Hiring Companies</div>
        <ResponsiveContainer width="100%" height={160}>
          <BarChart data={stats.top_companies} layout="vertical">
            <XAxis type="number" tick={{ fill: '#9CA3AF', fontSize: 10 }} />
            <YAxis dataKey="name" type="category" tick={{ fill: '#9CA3AF', fontSize: 10 }} width={80} />
            <Tooltip contentStyle={{ background: '#1F2937', border: 'none', color: '#fff' }} />
            <Bar dataKey="job_count" fill="#3B82F6" radius={[0, 4, 4, 0]} />
          </BarChart>
        </ResponsiveContainer>
      </div>

      <div className="mb-6">
        <div className="text-xs text-gray-400 mb-2">Most In-Demand Skills</div>
        <ResponsiveContainer width="100%" height={160}>
          <BarChart data={stats.top_skills} layout="vertical">
            <XAxis type="number" tick={{ fill: '#9CA3AF', fontSize: 10 }} />
            <YAxis dataKey="name" type="category" tick={{ fill: '#9CA3AF', fontSize: 10 }} width={80} />
            <Tooltip contentStyle={{ background: '#1F2937', border: 'none', color: '#fff' }} />
            <Bar dataKey="count" fill="#8B5CF6" radius={[0, 4, 4, 0]} />
          </BarChart>
        </ResponsiveContainer>
      </div>

      <div className="mb-6">
        <div className="text-xs text-gray-400 mb-2">Remote vs Onsite vs Hybrid</div>
        <ResponsiveContainer width="100%" height={140}>
          <PieChart>
            <Pie
              data={stats.remote_breakdown}
              dataKey="count"
              nameKey="remote_type"
              cx="50%"
              cy="50%"
              outerRadius={45}
            >
              {stats.remote_breakdown.map((_: any, i: number) => (
                <Cell key={i} fill={COLORS[i % COLORS.length]} />
              ))}
            </Pie>
            <Legend
              formatter={(value) => (
                <span style={{ color: '#9CA3AF', fontSize: 11 }}>{value}</span>
              )}
            />
            <Tooltip contentStyle={{ background: '#1F2937', border: 'none', color: '#fff' }} />
          </PieChart>
        </ResponsiveContainer>
      </div>

      <div>
        <div className="text-xs text-gray-400 mb-2">Seniority Breakdown</div>
        <div className="space-y-2">
          {stats.seniority_breakdown.map((item: any, i: number) => (
            <div key={i} className="flex justify-between items-center">
              <span className="text-sm text-gray-300 capitalize">{item.seniority}</span>
              <span className="text-sm font-medium text-blue-400">{item.count} jobs</span>
            </div>
          ))}
        </div>
      </div>

      <div className="mt-6 text-xs text-gray-500 text-center">
        Click any circle on the map to see company details
      </div>
    </div>
  );
}