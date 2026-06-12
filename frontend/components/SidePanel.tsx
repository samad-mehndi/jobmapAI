'use client';

interface Job {
  title: string;
  url: string;
  seniority: string;
  remote_type: string;
  salary_min: number;
  salary_max: number;
}

interface Props {
  company: any;
  onClose: () => void;
}

const seniorityColor: Record<string, string> = {
  entry: 'bg-green-900 text-green-300',
  mid: 'bg-blue-900 text-blue-300',
  senior: 'bg-purple-900 text-purple-300',
  lead: 'bg-pink-900 text-pink-300',
};

const remoteColor: Record<string, string> = {
  remote: 'bg-teal-900 text-teal-300',
  hybrid: 'bg-yellow-900 text-yellow-300',
  onsite: 'bg-gray-700 text-gray-300',
};

export default function SidePanel({ company, onClose }: Props) {
  const jobs: Job[] = Array.isArray(company.jobs)
    ? company.jobs
    : JSON.parse(company.jobs || '[]');

  const topSkills: string[] = Array.isArray(company.top_skills)
    ? company.top_skills
    : JSON.parse(company.top_skills || '[]');

  return (
    <div className="p-4 text-white h-full flex flex-col">

      <div className="flex justify-between items-start mb-4">
        <div>
          <h2 className="text-lg font-semibold">{company.company_name}</h2>
          <p className="text-xs text-gray-400 mt-0.5">{jobs.length} open positions</p>
        </div>
        <button
          onClick={onClose}
          className="text-gray-400 hover:text-white text-lg leading-none px-1"
        >
          x
        </button>
      </div>

      {company.avg_salary_min && (
        <div className="mb-4 p-3 bg-gray-800 rounded-lg">
          <div className="text-xs text-gray-400 mb-1">Average Salary Range</div>
          <div className="text-green-400 font-medium">
            ${Number(company.avg_salary_min).toLocaleString()} — ${Number(company.avg_salary_max).toLocaleString()}
          </div>
        </div>
      )}

      {topSkills.length > 0 && (
        <div className="mb-4">
          <div className="text-xs text-gray-400 mb-2">Top Skills Required</div>
          <div className="flex flex-wrap gap-1.5">
            {topSkills.map((skill: string, i: number) => (
              <span key={i} className="px-2 py-0.5 bg-purple-900 text-purple-200 rounded text-xs">
                {skill}
              </span>
            ))}
          </div>
        </div>
      )}

      <div className="text-xs text-gray-400 mb-2">Open Roles — click to apply</div>
      <div className="flex-1 overflow-y-auto space-y-2">
        {jobs.map((job: Job, i: number) => (
          <a
            key={i}
            href={job.url || '#'}
            target="_blank"
            rel="noopener noreferrer"
            className="block p-3 bg-gray-800 rounded-lg hover:bg-gray-700 transition-colors group cursor-pointer border border-transparent hover:border-blue-500"
          >
            <div className="flex justify-between items-start gap-2">
              <span className="text-sm text-white group-hover:text-blue-400 transition-colors leading-tight">
                {job.title}
              </span>
              <span className="text-gray-500 group-hover:text-blue-400 text-xs flex-shrink-0 mt-0.5">
                Apply
              </span>
            </div>
            <div className="flex gap-1.5 mt-2 flex-wrap">
              {job.seniority && (
                <span className={`px-1.5 py-0.5 rounded text-xs ${seniorityColor[job.seniority] || 'bg-gray-700 text-gray-300'}`}>
                  {job.seniority}
                </span>
              )}
              {job.remote_type && (
                <span className={`px-1.5 py-0.5 rounded text-xs ${remoteColor[job.remote_type] || 'bg-gray-700 text-gray-300'}`}>
                  {job.remote_type}
                </span>
              )}
              {job.salary_min && (
                <span className="px-1.5 py-0.5 rounded text-xs bg-gray-700 text-green-400">
                  ${Number(job.salary_min).toLocaleString()}+
                </span>
              )}
            </div>
          </a>
        ))}
      </div>

    </div>
  );
}