'use client';

import { useEffect, useRef, useState } from 'react';
import mapboxgl from 'mapbox-gl';
import 'mapbox-gl/dist/mapbox-gl.css';
import StatsPanel from './StatsPanel';
import SidePanel from './SidePanel';

mapboxgl.accessToken = process.env.NEXT_PUBLIC_MAPBOX_TOKEN!;

const API = 'http://localhost:8000/api';

export default function JobMap() {
  const mapContainer = useRef<HTMLDivElement>(null);
  const map = useRef<mapboxgl.Map | null>(null);
  const [selectedCompany, setSelectedCompany] = useState<any>(null);
  const [stats, setStats] = useState<any>(null);
  const [role, setRole] = useState('');
  const [jobCount, setJobCount] = useState(0);

  // Fetch stats once on load
  useEffect(() => {
    fetch(`${API}/jobs/stats`)
      .then(r => r.json())
      .then(setStats);
  }, []);

  // Initialize map
  useEffect(() => {
    if (map.current || !mapContainer.current) return;

    map.current = new mapboxgl.Map({
      container: mapContainer.current,
      style: 'mapbox://styles/mapbox/dark-v11',
      center: [-96.7297, 32.9483], // Richardson, TX
      zoom: 10
    });

    map.current.on('load', () => {
      loadJobs();
    });
  }, []);

  const loadJobs = async (roleFilter = '') => {
    const url = `${API}/jobs/map?lat=32.9483&lng=-96.7297&radius_miles=40${roleFilter ? `&role=${roleFilter}` : ''}`;
    const data = await fetch(url).then(r => r.json());
    setJobCount(data.total);

    if (!map.current) return;

    // Remove existing layers
    if (map.current.getSource('jobs')) {
      map.current.removeLayer('job-circles');
      map.current.removeLayer('job-labels');
      map.current.removeSource('jobs');
    }

    map.current.addSource('jobs', {
      type: 'geojson',
      data: data
    });

    // Circle layer — size proportional to job count
    map.current.addLayer({
      id: 'job-circles',
      type: 'circle',
      source: 'jobs',
      paint: {
        'circle-radius': [
          'interpolate', ['linear'],
          ['get', 'job_count'],
          1, 8,
          10, 20,
          30, 36,
          50, 50
        ],
        'circle-color': [
          'interpolate', ['linear'],
          ['get', 'job_count'],
          1, '#3B82F6',
          15, '#8B5CF6',
          30, '#EC4899'
        ],
        'circle-opacity': 0.85,
        'circle-stroke-width': 2,
        'circle-stroke-color': '#ffffff'
      }
    });

    // Job count labels
    map.current.addLayer({
      id: 'job-labels',
      type: 'symbol',
      source: 'jobs',
      layout: {
        'text-field': ['get', 'job_count'],
        'text-size': 11,
        'text-font': ['DIN Offc Pro Bold', 'Arial Unicode MS Bold']
      },
      paint: {
        'text-color': '#ffffff'
      }
    });

    // Click handler
    map.current.on('click', 'job-circles', (e) => {
      const props = e.features?.[0]?.properties;
      if (props) {
        setSelectedCompany({
          ...props,
          job_titles: JSON.parse(props.job_titles || '[]'),
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

  const handleSearch = (e: React.FormEvent) => {
    e.preventDefault();
    loadJobs(role);
  };

  return (
    <div className="flex h-screen w-screen bg-gray-950">
      {/* Left: Map */}
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
            <button
              type="submit"
              className="px-4 py-2 bg-blue-600 text-white rounded-lg text-sm hover:bg-blue-700"
            >
              Search
            </button>
            {role && (
              <button
                type="button"
                onClick={() => { setRole(''); loadJobs(''); }}
                className="px-4 py-2 bg-gray-700 text-white rounded-lg text-sm hover:bg-gray-600"
              >
                Clear
              </button>
            )}
          </form>
        </div>

        {/* Job count badge */}
        <div className="absolute top-4 right-4 z-10 bg-gray-900 text-white px-3 py-1 rounded-full text-sm border border-gray-700">
          {jobCount} companies hiring
        </div>

        <div ref={mapContainer} className="w-full h-full" />
      </div>

      {/* Right: Panels */}
      <div className="w-80 flex flex-col bg-gray-900 border-l border-gray-800 overflow-y-auto">
        {selectedCompany ? (
          <SidePanel company={selectedCompany} onClose={() => setSelectedCompany(null)} />
        ) : (
          <StatsPanel stats={stats} />
        )}
      </div>
    </div>
  );
}