import React, { useEffect, useState } from 'react';
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Line,
  LineChart,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';
import { Activity, BarChart3, CheckCircle2, Database, Play, Sparkles, XCircle } from 'lucide-react';

const API_BASE = (import.meta.env.VITE_API_URL || 'http://localhost:8000').replace(/\/+$/, '');

const SAMPLE_QUESTIONS = [
  'Top 5 product categories by revenue',
  'Top 5 customers by total order revenue in 1997',
  'Monthly revenue trend ordered by month ascending',
  'Total number of orders handled by each employee with full name',
  'What is the weather in Hyderabad today?',
];

const PIE_COLORS = ['#38bdf8', '#22c55e', '#f59e0b', '#a78bfa', '#f472b6', '#34d399'];

function ChartRenderer({ chart, rows }) {
  if (!chart || !rows || rows.length === 0) {
    return <div className='mono' style={{ color: 'var(--muted)', fontSize: 13 }}>No chart data</div>;
  }

  const type = chart.type;
  const xKey = chart.x;
  const yKeys = Array.isArray(chart.y) && chart.y.length > 0 ? chart.y : [];

  if (type === 'metric' && yKeys.length > 0) {
    const val = rows[0]?.[yKeys[0]];
    return (
      <div>
        <div className='metric-label'>{yKeys[0]}</div>
        <div className='big-metric mono'>{String(val ?? '')}</div>
      </div>
    );
  }

  if (type === 'line' && xKey && yKeys.length > 0) {
    return (
      <div style={{ width: '100%', height: 280 }}>
        <ResponsiveContainer>
          <LineChart data={rows}>
            <CartesianGrid strokeDasharray='3 3' stroke='#243046' />
            <XAxis dataKey={xKey} stroke='#94a3b8' tick={{ fontSize: 12 }} />
            <YAxis stroke='#94a3b8' tick={{ fontSize: 12 }} />
            <Tooltip contentStyle={{ background: '#0b0f17', border: '1px solid #243046' }} />
            {yKeys.map((yk, idx) => (
              <Line
                key={yk}
                type='monotone'
                dataKey={yk}
                stroke={PIE_COLORS[idx % PIE_COLORS.length]}
                strokeWidth={2}
                dot={{ r: 3 }}
              />
            ))}
          </LineChart>
        </ResponsiveContainer>
      </div>
    );
  }

  if (type === 'pie' && xKey && yKeys.length > 0) {
    const yKey = yKeys[0];
    return (
      <div style={{ width: '100%', height: 280 }}>
        <ResponsiveContainer>
          <PieChart>
            <Pie data={rows} dataKey={yKey} nameKey={xKey} outerRadius={100} label>
              {rows.map((_, i) => (
                <Cell key={i} fill={PIE_COLORS[i % PIE_COLORS.length]} />
              ))}
            </Pie>
            <Tooltip contentStyle={{ background: '#0b0f17', border: '1px solid #243046' }} />
          </PieChart>
        </ResponsiveContainer>
      </div>
    );
  }

  if (type === 'bar' && xKey && yKeys.length > 0) {
    return (
      <div style={{ width: '100%', height: 280 }}>
        <ResponsiveContainer>
          <BarChart data={rows}>
            <CartesianGrid strokeDasharray='3 3' stroke='#243046' />
            <XAxis dataKey={xKey} stroke='#94a3b8' tick={{ fontSize: 12 }} />
            <YAxis stroke='#94a3b8' tick={{ fontSize: 12 }} />
            <Tooltip contentStyle={{ background: '#0b0f17', border: '1px solid #243046' }} />
            {yKeys.map((yk, idx) => (
              <Bar key={yk} dataKey={yk} fill={PIE_COLORS[idx % PIE_COLORS.length]} radius={[4, 4, 0, 0]} />
            ))}
          </BarChart>
        </ResponsiveContainer>
      </div>
    );
  }

  return <div className='mono' style={{ color: 'var(--muted)', fontSize: 13 }}>Tabular view selected</div>;
}

export default function App() {
  const [tab, setTab] = useState('ask');
  const [question, setQuestion] = useState('Top 5 product categories by revenue');
  const [mode, setMode] = useState('full');
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState(null);
  const [tracesData, setTracesData] = useState({ traces: [], metrics: null });
  const [evalsData, setEvalsData] = useState({ runs: [] });

  async function runAsk(qText = question, qMode = mode) {
    const trimmed = qText.trim();
    if (!trimmed) return;
    setLoading(true);
    setResult(null);
    try {
      const res = await fetch(API_BASE + '/ask', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ question: trimmed, mode: qMode }),
      });
      const data = await res.json();
      setResult(data);
    } catch (err) {
      setResult({ success: false, message: 'Network error: ' + err.message });
    } finally {
      setLoading(false);
    }
  }

  async function loadTraces() {
    try {
      const res = await fetch(API_BASE + '/traces?limit=50');
      const data = await res.json();
      setTracesData(data);
    } catch (err) {
      console.error(err);
    }
  }

  async function loadEvals() {
    try {
      const res = await fetch(API_BASE + '/evals');
      const data = await res.json();
      setEvalsData(data);
    } catch (err) {
      console.error(err);
    }
  }

  useEffect(() => {
    if (tab === 'traces') loadTraces();
    if (tab === 'evals') loadEvals();
  }, [tab]);

  return (
    <div className='app-shell'>
      <header className='topbar'>
        <div className='brand'>
          <div className='brand-badge'>DP</div>
          <div>
            <h1>DataPilot Analytics</h1>
            <p>Read-only natural language SQL &amp; self-healing telemetry over Northwind</p>
          </div>
        </div>
        <nav className='nav-tabs'>
          <button className={tab === 'ask' ? 'tab-btn active' : 'tab-btn'} onClick={() => setTab('ask')}>
            <Sparkles size={15} /> Ask SQL
          </button>
          <button className={tab === 'traces' ? 'tab-btn active' : 'tab-btn'} onClick={() => setTab('traces')}>
            <Activity size={15} /> Traces
          </button>
          <button className={tab === 'evals' ? 'tab-btn active' : 'tab-btn'} onClick={() => setTab('evals')}>
            <BarChart3 size={15} /> Evals
          </button>
        </nav>
      </header>

      {tab === 'ask' && (
        <>
          <section className='card'>
            <form
              className='ask-form'
              onSubmit={(e) => {
                e.preventDefault();
                runAsk();
              }}
            >
              <input
                className='ask-input'
                value={question}
                onChange={(e) => setQuestion(e.target.value)}
                placeholder='Ask a question about Northwind orders, products, customers, employees...'
              />
              <select className='select-box' value={mode} onChange={(e) => setMode(e.target.value)}>
                <option value='full'>Mode: full</option>
                <option value='retrieval'>Mode: retrieval</option>
                <option value='baseline'>Mode: baseline</option>
              </select>
              <button className='btn-primary' type='submit' disabled={loading}>
                <Play size={15} /> {loading ? 'Running...' : 'Run Query'}
              </button>
            </form>

            <div className='samples'>
              {SAMPLE_QUESTIONS.map((sq) => (
                <button
                  key={sq}
                  type='button'
                  className='chip'
                  onClick={() => {
                    setQuestion(sq);
                    runAsk(sq, mode);
                  }}
                >
                  {sq}
                </button>
              ))}
            </div>
          </section>

          {result && (
            <>
              <div className='metrics-row'>
                <div className='metric-box'>
                  <div className='metric-label'>Status</div>
                  <div className='metric-val'>
                    {result.success ? (
                      <span className='badge badge-ok'>
                        <CheckCircle2 size={12} style={{ verticalAlign: '-2px' }} /> Success
                      </span>
                    ) : (
                      <span className='badge badge-err'>
                        <XCircle size={12} style={{ verticalAlign: '-2px' }} /> Failed / Refused
                      </span>
                    )}
                  </div>
                </div>
                <div className='metric-box'>
                  <div className='metric-label'>Rows</div>
                  <div className='metric-val mono'>{result.row_count ?? 0}</div>
                </div>
                <div className='metric-box'>
                  <div className='metric-label'>Latency</div>
                  <div className='metric-val mono'>{result.metrics?.latency_ms ?? 0} ms</div>
                </div>
                <div className='metric-box'>
                  <div className='metric-label'>Tokens</div>
                  <div className='metric-val mono'>
                    {(result.metrics?.prompt_tokens ?? 0) + (result.metrics?.output_tokens ?? 0)}
                  </div>
                </div>
                <div className='metric-box'>
                  <div className='metric-label'>Retries</div>
                  <div className='metric-val mono'>{result.reasoning?.retries ?? 0}</div>
                </div>
              </div>

              {!result.success && result.message && (
                <div className='card error-box'>{result.message}</div>
              )}

              {result.insight && (
                <section className='card'>
                  <h2 className='section-title'>Analyst Insight</h2>
                  <p className='insight-text'>{result.insight}</p>
                </section>
              )}

              <div className='grid-2'>
                <section className='card'>
                  <h2 className='section-title'>Visualization ({result.chart?.type || 'none'})</h2>
                  <ChartRenderer chart={result.chart} rows={result.rows} />
                </section>

                <section className='card'>
                  <h2 className='section-title'>
                    <Database size={15} style={{ verticalAlign: '-2px' }} /> Generated SQL &amp; Retrieval
                  </h2>
                  {result.plan && (
                    <p style={{ fontSize: 13, color: 'var(--muted)', marginTop: 0 }}>
                      <strong>Plan:</strong> {result.plan}
                    </p>
                  )}
                  <pre className='sql-box'>{result.sql || '-- No SQL generated'}</pre>
                  <p className='mono' style={{ fontSize: 12, color: 'var(--muted)', marginBottom: 0, marginTop: 10 }}>
                    Tables: {(result.reasoning?.retrieved_tables || []).join(', ') || 'none'} (
                    {result.reasoning?.retrieval_method || 'n/a'})
                  </p>
                </section>
              </div>

              {Array.isArray(result.rows) && result.rows.length > 0 && (
                <section className='card'>
                  <h2 className='section-title'>Query Results ({result.rows.length} rows)</h2>
                  <div className='table-wrap'>
                    <table>
                      <thead>
                        <tr>
                          {(result.columns || Object.keys(result.rows[0])).map((col) => (
                            <th key={col}>{col}</th>
                          ))}
                        </tr>
                      </thead>
                      <tbody>
                        {result.rows.map((row, idx) => (
                          <tr key={idx}>
                            {(result.columns || Object.keys(result.rows[0])).map((col) => (
                              <td key={col} className='mono'>
                                {String(row[col] ?? '')}
                              </td>
                            ))}
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </section>
              )}
            </>
          )}
        </>
      )}

      {tab === 'traces' && (
        <>
          {tracesData.metrics && (
            <div className='metrics-row'>
              <div className='metric-box'>
                <div className='metric-label'>Total Queries</div>
                <div className='metric-val mono'>{tracesData.metrics.total_queries ?? 0}</div>
              </div>
              <div className='metric-box'>
                <div className='metric-label'>Success Rate</div>
                <div className='metric-val mono'>{tracesData.metrics.success_rate ?? 'N/A'}</div>
              </div>
              <div className='metric-box'>
                <div className='metric-label'>Self-Healed</div>
                <div className='metric-val mono'>{tracesData.metrics.self_healed ?? 0}</div>
              </div>
              <div className='metric-box'>
                <div className='metric-label'>p50 Latency</div>
                <div className='metric-val mono'>{tracesData.metrics.p50_latency_ms ?? 0} ms</div>
              </div>
              <div className='metric-box'>
                <div className='metric-label'>p95 Latency</div>
                <div className='metric-val mono'>{tracesData.metrics.p95_latency_ms ?? 0} ms</div>
              </div>
            </div>
          )}

          <section className='card'>
            <h2 className='section-title'>Recent Query Traces</h2>
            <div className='table-wrap'>
              <table>
                <thead>
                  <tr>
                    <th>ID</th>
                    <th>Question</th>
                    <th>Mode</th>
                    <th>Status</th>
                    <th>Retries</th>
                    <th>Rows</th>
                    <th>Latency</th>
                  </tr>
                </thead>
                <tbody>
                  {(tracesData.traces || []).map((t) => (
                    <tr key={t.id}>
                      <td className='mono'>{t.id}</td>
                      <td>{t.question}</td>
                      <td className='mono'>{t.mode}</td>
                      <td>
                        <span className={t.success ? 'badge badge-ok' : 'badge badge-err'}>
                          {t.success ? 'OK' : 'FAIL'}
                        </span>
                      </td>
                      <td className='mono'>{t.retries}</td>
                      <td className='mono'>{t.row_count}</td>
                      <td className='mono'>{t.latency_ms} ms</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>
        </>
      )}

      {tab === 'evals' && (
        <section className='card'>
          <h2 className='section-title'>Evaluation Runs</h2>
          {(evalsData.runs || []).length === 0 ? (
            <p style={{ color: 'var(--muted)', fontSize: 14 }}>
              No eval runs saved yet. Run <code className='mono'>python -m scripts.eval_suite --mode full</code> in backend.
            </p>
          ) : (
            <div className='table-wrap'>
              <table>
                <thead>
                  <tr>
                    <th>Run ID</th>
                    <th>Git SHA</th>
                    <th>Questions</th>
                    <th>Pass Rate</th>
                    <th>Created At</th>
                  </tr>
                </thead>
                <tbody>
                  {evalsData.runs.map((run) => (
                    <tr key={run.id}>
                      <td className='mono'>{run.id}</td>
                      <td className='mono'>{run.git_sha || 'N/A'}</td>
                      <td className='mono'>{run.n_questions}</td>
                      <td className='mono'>{run.results?.pass_rate ?? 'N/A'}</td>
                      <td className='mono'>{String(run.created_at)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </section>
      )}
    </div>
  );
}
