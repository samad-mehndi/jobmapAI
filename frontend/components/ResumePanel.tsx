'use client';

interface Match {
  job_id: number;
  title: string;
  company_name: string;
  match_score: number;
  seniority: string;
  remote_type: string;
  salary_min: number;
  matched_skills: string[];
  missing_skills: string[];
  source_url: string;
}

interface Props {
  data: {
    resume_skills: string[];
    resume_seniority: string;
    target_roles: string[];
    total_jobs_scored: number;
    new_jobs_fetched: number;
    matches: Match[];
  };
  onJobClick: (match: Match) => void;
}

export default function ResumePanel({ data, onJobClick }: Props) {
  return (
    <div className="p-4 text-white flex flex-col h-full">

      <div className="mb-4">
        <h2 className="text-lg font-semibold text-green-400">Resume Matches</h2>
        <p className="text-xs text-gray-400 mt-1">
          Scored {data.total_jobs_scored} jobs
          {data.new_jobs_fetched > 0 && ` + fetched ${data.new_jobs_fetched} new jobs for you`}
        </p>
      </div>

      <div className="mb-4">
        <div className="text-xs text-gray-400 mb-1">Your target roles</div>
        <div className="flex flex-wrap gap-1.5">
          {data.target_roles.map((role, i) => (
            <span key={i} className="px-2 py-0.5 bg-blue-900 text-blue-300 rounded text-xs">
              {role}
            </span>
          ))}
        </div>
      </div>

      <div className="mb-4">
        <div className="text-xs text-gray-400 mb-1">Skills on your resume</div>
        <div className="flex flex-wrap gap-1.5">
          {data.resume_skills.slice(0, 12).map((skill, i) => (
            <span key={i} className="px-2 py-0.5 bg-gray-800 text-gray-300 rounded text-xs">
              {skill}
            </span>
          ))}
        </div>
      </div>

      <div className="text-xs text-gray-400 mb-2">
        Top matches — green circles on map
      </div>

      <div className="flex-1 overflow-y-auto space-y-2">
        {data.matches.map((match, i) => (
          <div
            key={i}
            onClick={() => onJobClick(match)}
            className="p-3 bg-gray-800 rounded-lg cursor-pointer hover:bg-gray-700 border border-transparent hover:border-green-700 transition-colors"
          >
            <div className="flex justify-between items-start gap-2 mb-1">
              <span className="text-sm text-white leading-tight">{match.title}</span>
              <span
                className={`text-xs font-bold flex-shrink-0 px-1.5 py-0.5 rounded ${
                  match.match_score >= 70
                    ? 'bg-green-900 text-green-300'
                    : match.match_score >= 50
                    ? 'bg-yellow-900 text-yellow-300'
                    : 'bg-gray-700 text-gray-400'
                }`}
              >
                {match.match_score}%
              </span>
            </div>

            <div className="text-xs text-gray-400 mb-2">{match.company_name}</div>

            {match.matched_skills.length > 0 && (
              <div className="flex flex-wrap gap-1 mb-1">
                {match.matched_skills.slice(0, 4).map((s, j) => (
                  <span key={j} className="px-1.5 py-0.5 bg-green-900 text-green-300 rounded text-xs">
                    {s}
                  </span>
                ))}
              </div>
            )}

            {match.missing_skills.length > 0 && (
              <div className="flex flex-wrap gap-1 mb-1">
                {match.missing_skills.slice(0, 3).map((s, j) => (
                  <span key={j} className="px-1.5 py-0.5 bg-red-950 text-red-400 rounded text-xs">
                    -{s}
                  </span>
                ))}
              </div>
            )}

            {match.source_url && (
              <a
                href={match.source_url}
                target="_blank"
                rel="noopener noreferrer"
                onClick={(e) => e.stopPropagation()}
                className="mt-2 block text-xs text-blue-400 hover:text-blue-300"
              >
                Apply
              </a>
            )}
          </div>
        ))}
      </div>

    </div>
  );
}