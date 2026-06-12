interface Props {
  company: any;
  onClose: () => void;
}

export default function SidePanel({ company, onClose }: Props) {
  return (
    <div className="p-4 text-white">
      <div className="flex justify-between items-start mb-4">
        <h2 className="text-lg font-semibold">{company.company_name}</h2>
        <button onClick={onClose} className="text-gray-400 hover:text-white text-xl">x</button>
      </div>

      <div className="bg-blue-600 rounded-lg p-3 mb-4 text-center">
        <div className="text-3xl font-bold">{company.job_count}</div>
        <div className="text-sm text-blue-200">open positions</div>
      </div>

      {company.avg_salary_min && (
        <div className="mb-4 p-3 bg-gray-800 rounded-lg">
          <div className="text-xs text-gray-400 mb-1">Salary Range</div>
          <div className="text-green-400 font-medium">
            ${Number(company.avg_salary_min).toLocaleString()} — ${Number(company.avg_salary_max).toLocaleString()}
          </div>
        </div>
      )}

      <div className="mb-4">
        <div className="text-xs text-gray-400 mb-2">Open Roles</div>
        <div className="space-y-1">
          {company.job_titles.map((title: string, i: number) => (
            <div key={i} className="text-sm text-gray-300 bg-gray-800 px-3 py-2 rounded">
              {title}
            </div>
          ))}
        </div>
      </div>

      {company.top_skills.length > 0 && (
        <div>
          <div className="text-xs text-gray-400 mb-2">Top Skills Required</div>
          <div className="flex flex-wrap gap-2">
            {company.top_skills.map((skill: string, i: number) => (
              <span key={i} className="px-2 py-1 bg-purple-900 text-purple-200 rounded text-xs">
                {skill}
              </span>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}