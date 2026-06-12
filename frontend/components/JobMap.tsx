'use client';

import { useEffect, useRef, useState } from 'react';
import mapboxgl from 'mapbox-gl';
import 'mapbox-gl/dist/mapbox-gl.css';
import StatsPanel from './StatsPanel';
import SidePanel from './SidePanel';
import ResumePanel from './ResumePanel';

mapboxgl.accessToken = process.env.NEXT_PUBLIC_MAPBOX_TOKEN!;

const API = 'http://localhost:8000/api';

export default function JobMap() {
  const mapContainer = useRef<HTMLDivElement>(null);
  const map = useRef<mapboxgl.Map | null>(null);
  const [selectedCompany, setSelectedCompany] = useState<any>(null);
  const [stats, setStats] = useState<any>(null);
  const [role, setRole] = useState('');
  const [jobCount, setJobCount] = useState(0);
  const [view, setView] = useState<'stats' | 'resume'>('stats');
  const [matchedJobIds, setMatchedJobIds] = useState<Set<number>>(new Set());
  const [resumeData, setResumeData] = useState<any>(null);
  const [uploading, setUploading] = useState(false);

  useEffect(() => {
    fetch(`${API}/jobs/stats`).then(r => r.json()).then(setStats);
  }, []);

  useEffect(() => {
    if (map.current || !mapContainer.current) return;
    map.current = new mapboxgl.Map({
      container: mapContainer.current,
      style: 'mapbox://styles/mapbox/dark-v11',
      center: [-96.7297, 32.9483],
      zoom: 10
    });
    map.current.on('load', () => { loadJobs(); });
  }, []);

  const loadJobs = async (roleFilter = '') => {
    const url = `${API}/jobs/map?lat=32.9483&lng=-96.7297&radius_miles=40${roleFilter ? `&role=${roleFilter}` : ''}`;
    const data = await fetch(url).then(r => r.json());
    setJobCount(data.total);
    if (!map.current) return;

    if (map.current.getSource('jobs')) {
      map.current.removeLayer('job-circles');
      map.current.removeLayer('job-labels');
      map.current.removeSource('jobs');
    }

    map.current.addSource('jobs', { type: 'geojson', data });

    map.current.addLayer({
      id: 'job-circles',
      type: 'circle',
      source: 'jobs',
      paint: {
        'circle-radius': [
          'interpolate', ['linear'], ['get', 'job_count'],
          1, 12, 2, 18, 3, 26, 5, 34, 10, 44
        ],
        'circle-color': [
          'interpolate', ['linear'], ['get', 'job_count'],
          1, '#3B82F6', 3, '#8B5CF6', 5, '#EC4899'
        ],
        'circle-opacity': 0.85,
        'circle-stroke-width': 2,
        'circle-stroke-color': '#ffffff'
      }
    });

    map.current.addLayer({
      id: 'job-labels',
      type: 'symbol',
      source: 'jobs',
      layout: {
        'text-field': ['get', 'job_count'],
        'text-size': 11,
        'text-font': ['DIN Offc Pro Bold', 'Arial Unicode MS Bold']
      },
      paint: { 'text-color': '#ffffff' }
    });

    map.current.on('click', 'job-circles', (e) => {
      const props = e.features?.[0]?.properties;
      if (props) {
        setSelectedCompany({
          ...props,
          jobs: JSON.parse(props.jobs || '[]'),
          top_skills: JSON.parse(props.top_skills || '[]')
        });
      }
    });

    map.current.on('mouseenter', 'job-circles', () => {
      if (map.current) map.current.getCanvas().style.cursor = 'pointer';
    });
    map.current.on('mouseleave', 'job-circles', () => {
      if (map.current) map.current.getCanvas().style.cursor = '';
    });
  };

  const showMatchedJobs = (matches: any[]) => {
    if (!map.current) return;

    const ids = new Set<number>(matches.map((m: any) => m.job_id));
    setMatchedJobIds(ids);

    // Add match layer on top
    if (map.current.getLayer('matched-circles')) {
      map.current.removeLayer('matched-circles');
      map.current.removeLayer('matched-labels');
      map.current.removeSource('matched-jobs');
    }

    const geojson = {
      type: 'FeatureCollection' as const,
      features: matches
        .filter(m => m.lat && m.lng)
        .map(m => ({
          type: 'Feature' as const,
          geometry: { type: 'Point' as const, coordinates: [m.lng, m.lat] },
          properties: {
            job_id: m.job_id,
            title: m.title,
            company_name: m.company_name,
            match_score: m.match_score,
            matched_skills: m.matched_skills,
            missing_skills: m.missing_skills,
            source_url: m.source_url,
            seniority: m.seniority,
            remote_type: m.remote_type,
            salary_min: m.salary_min
          }
        }))
    };

    map.current.addSource('matched-jobs', { type: 'geojson', data: geojson });

    map.current.addLayer({
      id: 'matched-circles',
      type: 'circle',
      source: 'matched-jobs',
      paint: {
        'circle-radius': [
          'interpolate', ['linear'], ['get', 'match_score'],
          30, 14, 60, 22, 80, 30, 100, 38
        ],
        'circle-color': [
          'interpolate', ['linear'], ['get', 'match_score'],
          30, '#10B981', 70, '#34D399', 90, '#6EE7B7'
        ],
        'circle-opacity': 0.9,
        'circle-stroke-width': 2.5,
        'circle-stroke-color': '#ffffff'
      }
    });

    map.current.addLayer({
      id: 'matched-labels',
      type: 'symbol',
      source: 'matched-jobs',
      layout: {
        'text-field': ['concat', ['to-string', ['get', 'match_score']], '%'],
        'text-size': 10,
        'text-font': ['DIN Offc Pro Bold', 'Arial Unicode MS Bold']
      },
      paint: { 'text-color': '#ffffff' }
    });

    map.current.on('click', 'matched-circles', (e) => {
      const props = e.features?.[0]?.properties;
      if (props) {
        setSelectedCompany({
          company_name: props.company_name,
          job_count: 1,
          avg_salary_min: props.salary_min,
          match_score: props.match_score,
          top_skills: JSON.parse(props.matched_skills || '[]'),
          jobs: [JSON.parse(JSON.stringify({
            title: props.title,
            url: props.source_url,
            seniority: props.seniority,
            remote_type: props.remote_type,
            salary_min: props.salary_min,
            match_score: props.match_score,
            matched_skills: JSON.parse(props.matched_skills || '[]'),
            missing_skills: JSON.parse(props.missing_skills || '[]')
          }))]
        });
      }
    });

    map.current.on('mouseenter', 'matched-circles', () => {
      if (map.current) map.current.getCanvas().style.cursor = 'pointer';
    });
    map.current.on('mouseleave', 'matched-circles', () => {
      if (map.current) map.current.getCanvas().style.cursor = '';
    });
  };

  const handleResumeUpload = async (file: File) => {
    setUploading(true);
    const formData = new FormData();
    formData.append('file', file);
    try {
      const res = await fetch(`${API}/resume/match`, {
        method: 'POST',
        body: formData
      });
      if (!res.ok) {
        const err = await res.json();
        alert(`Error: ${err.detail}`);
        return;
      }
      const data = await res.json();
      setResumeData(data);
      setView('resume');
      showMatchedJobs(data.matches);
    } catch (e) {
      alert('Failed to process resume. Make sure the backend is running.');
    } finally {
      setUploading(false);
    }
  };

  const handleSearch = (e: React.FormEvent) => {
    e.preventDefault();
    loadJobs(role);
  };

  const clearResume = () => {
    setResumeData(null);
    setMatchedJobIds(new Set());
    setView('stats');
    if (map.current) {
      if (map.current.getLayer('matched-circles')) map.current.removeLayer('matched-circles');
      if (map.current.getLayer('matched-labels')) map.current.removeLayer('matched-labels');
      if (map.current.getSource('matched-jobs')) map.current.removeSource('matched-jobs');
    }
  };

  return (
    <div className="flex h-screen w-screen bg-gray-950">
      <div className="flex-1 relative">
        {/* Search bar */}
        <div className="absolute top-4 left-4 z-10 flex gap-2">
          <form onSubmit={handleSearch} className="flex gap-2">
            <input
              type="text"
              value={role}
              onChange={e => setRole(e.target.value)}
              placeholder="Search role... e.g. AI Engineer"
              className="w-72 px-4 py-2 rounded-lg bg-gray-900 text-white border border-gray-700 text-sm focus:outline-none focus:border-blue-500"
            />
            <button type="submit" className="px-4 py-2 bg-blue-600 text-white rounded-lg text-sm hover:bg-blue-700">
              Search
            </button>
            {role && (
              <button type="button" onClick={() => { setRole(''); loadJobs(''); }}
                className="px-4 py-2 bg-gray-700 text-white rounded-lg text-sm hover:bg-gray-600">
                Clear
              </button>
            )}
          </form>
        </div>

        {/* Top right badges */}
        <div className="absolute top-4 right-4 z-10 flex gap-2 items-center">
          {resumeData && (
            <div className="bg-green-900 text-green-300 px-3 py-1 rounded-full text-sm border border-green-700">
              {resumeData.matches.length} matches found
            </div>
          )}
          <div className="bg-gray-900 text-white px-3 py-1 rounded-full text-sm border border-gray-700">
            {jobCount} companies hiring
          </div>
        </div>

        {/* Upload resume button */}
        {!resumeData && (
          <div className="absolute bottom-8 left-1/2 -translate-x-1/2 z-10">
            <label className={`flex items-center gap-2 px-6 py-3 rounded-full text-sm font-medium cursor-pointer border transition-all
              ${uploading
                ? 'bg-gray-800 text-gray-400 border-gray-600 cursor-not-allowed'
                : 'bg-blue-600 text-white border-blue-500 hover:bg-blue-700'
              }`}>
              <input
                type="file"
                accept=".pdf"
                className="hidden"
                disabled={uploading}
                onChange={e => {
                  const file = e.target.files?.[0];
                  if (file) handleResumeUpload(file);
                }}
              />
              {uploading ? 'Analyzing resume... (2-3 min)' : 'Upload Resume to Find Matches'}
            </label>
          </div>
        )}

        {/* Clear resume button */}
        {resumeData && (
          <div className="absolute bottom-8 left-1/2 -translate-x-1/2 z-10">
            <button
              onClick={clearResume}
              className="px-6 py-3 rounded-full text-sm font-medium bg-gray-800 text-gray-300 border border-gray-600 hover:bg-gray-700"
            >
              Clear Resume
            </button>
          </div>
        )}

        <div ref={mapContainer} className="w-full h-full" />
      </div>

      {/* Right panel */}
      <div className="w-80 flex flex-col bg-gray-900 border-l border-gray-800 overflow-y-auto">
        {selectedCompany ? (
          <SidePanel company={selectedCompany} onClose={() => setSelectedCompany(null)} />
        ) : view === 'resume' && resumeData ? (
          <ResumePanel data={resumeData} onJobClick={(match) => {
            setSelectedCompany({
              company_name: match.company_name,
              job_count: 1,
              avg_salary_min: match.salary_min,
              top_skills: match.matched_skills,
              jobs: [{
                title: match.title,
                url: match.source_url,
                seniority: match.seniority,
                remote_type: match.remote_type,
                salary_min: match.salary_min
              }]
            });
          }} />
        ) : (
          <StatsPanel stats={stats} />
        )}
      </div>
    </div>
  );
}