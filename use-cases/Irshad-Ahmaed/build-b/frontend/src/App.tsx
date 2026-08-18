import { useState, useMemo } from 'react'

function App() {
  const [volume, setVolume] = useState(100)
  const [hours, setHours] = useState(200)
  const [hourlyCost, setHourlyCost] = useState(75)
  const [infra, setInfra] = useState(100)
  const [horizon, setHorizon] = useState(3)
  const [downloading, setDownloading] = useState(false)
  const [pdfUrl, setPdfUrl] = useState<string | null>(null)

  const results = useMemo(() => {
    const buildOneTime = hours * hourlyCost
    const buildMaintPerYear = hours * 0.2 * hourlyCost
    const buildInfraPerYear = infra * 12
    const buildTotal = buildOneTime + (buildMaintPerYear + buildInfraPerYear) * horizon

    let buyTier = 'Free'
    let buyAnnual = 0
    if (volume > 500 && volume <= 2000) { buyTier = 'Plus'; buyAnnual = 240 }
    else if (volume > 2000) { buyTier = 'Pro'; buyAnnual = 1188 }
    const buyTotal = buyAnnual * horizon

    const savings = buildTotal - buyTotal
    const breakevenMonths = buyAnnual > 0 ? Math.round((buildOneTime / buyAnnual) * 12) : Infinity

    return {
      buildOneTime, buildMaintPerYear, buildInfraPerYear, buildTotal,
      buyTier, buyAnnual, buyTotal, savings, breakevenMonths,
    }
  }, [volume, hours, hourlyCost, infra, horizon])

  const handleDownload = async () => {
    setDownloading(true)
    try {
      const res = await fetch('/api/export-report', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          session_id: `roi-${Date.now()}`,
          volume, hours, hourly_cost: hourlyCost,
          infrastructure_monthly: infra, horizon_years: horizon,
        }),
      })
      if (!res.ok) throw new Error(`Export failed: ${res.statusText}`)
      const data = await res.json()
      if (data.download_url) {
        window.open(data.download_url, '_blank')
      }
      setPdfUrl(data.pdf_path || null)
    } catch (e) {
      alert(String(e))
    } finally {
      setDownloading(false)
    }
  }

  const fmt = (n: number) => n.toLocaleString('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: 0 })

  return (
    <div style={{ maxWidth: 800, margin: '0 auto', padding: 24, fontFamily: 'system-ui, sans-serif' }}>
      <h1>Build B — Build vs Buy ROI Calculator</h1>
      <p style={{ color: '#666' }}>
        Compare the cost of building an in-house AI document pipeline vs using SuperDocs.
      </p>

      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16, marginBottom: 24 }}>
        <div>
          <label style={{ display: 'block', marginBottom: 4, fontWeight: 600 }}>Documents / month</label>
          <input type="number" value={volume} onChange={e => setVolume(+e.target.value)}
            style={{ width: '100%', padding: 8, borderRadius: 4, border: '1px solid #ccc' }} />
        </div>
        <div>
          <label style={{ display: 'block', marginBottom: 4, fontWeight: 600 }}>Engineering hours to build</label>
          <input type="number" value={hours} onChange={e => setHours(+e.target.value)}
            style={{ width: '100%', padding: 8, borderRadius: 4, border: '1px solid #ccc' }} />
        </div>
        <div>
          <label style={{ display: 'block', marginBottom: 4, fontWeight: 600 }}>Loaded hourly cost ($)</label>
          <input type="number" value={hourlyCost} onChange={e => setHourlyCost(+e.target.value)}
            style={{ width: '100%', padding: 8, borderRadius: 4, border: '1px solid #ccc' }} />
        </div>
        <div>
          <label style={{ display: 'block', marginBottom: 4, fontWeight: 600 }}>Infrastructure ($/month)</label>
          <input type="number" value={infra} onChange={e => setInfra(+e.target.value)}
            style={{ width: '100%', padding: 8, borderRadius: 4, border: '1px solid #ccc' }} />
        </div>
        <div>
          <label style={{ display: 'block', marginBottom: 4, fontWeight: 600 }}>Horizon (years)</label>
          <input type="number" value={horizon} onChange={e => setHorizon(+e.target.value)}
            style={{ width: '100%', padding: 8, borderRadius: 4, border: '1px solid #ccc' }} />
        </div>
      </div>

      <div style={{ background: '#f5f5f5', borderRadius: 8, padding: 16, marginBottom: 16 }}>
        <h3>Results</h3>
        <table style={{ width: '100%', borderCollapse: 'collapse' }}>
          <tbody>
            <tr><td style={{ padding: '4px 8px' }}>Build (one-time)</td><td style={{ padding: '4px 8px', fontWeight: 600 }}>{fmt(results.buildOneTime)}</td></tr>
            <tr><td style={{ padding: '4px 8px' }}>Build maintenance / year</td><td style={{ padding: '4px 8px' }}>{fmt(results.buildMaintPerYear)}</td></tr>
            <tr><td style={{ padding: '4px 8px' }}>Build infrastructure / year</td><td style={{ padding: '4px 8px' }}>{fmt(results.buildInfraPerYear)}</td></tr>
            <tr><td style={{ padding: '4px 8px' }}>Build total ({horizon}yr)</td><td style={{ padding: '4px 8px', fontWeight: 600 }}>{fmt(results.buildTotal)}</td></tr>
            <tr><td colSpan={2} style={{ padding: '4px 8px' }}><hr /></td></tr>
            <tr><td style={{ padding: '4px 8px' }}>Buy (SuperDocs {results.buyTier})</td><td style={{ padding: '4px 8px', fontWeight: 600 }}>{fmt(results.buyAnnual)}/yr</td></tr>
            <tr><td style={{ padding: '4px 8px' }}>Buy total ({horizon}yr)</td><td style={{ padding: '4px 8px', fontWeight: 600 }}>{fmt(results.buyTotal)}</td></tr>
            <tr><td colSpan={2} style={{ padding: '4px 8px' }}><hr /></td></tr>
            <tr><td style={{ padding: '4px 8px' }}>Savings</td><td style={{ padding: '4px 8px', fontWeight: 600, color: results.savings > 0 ? 'green' : 'red' }}>{fmt(results.savings)}</td></tr>
            <tr><td style={{ padding: '4px 8px' }}>Breakeven</td><td style={{ padding: '4px 8px' }}>{results.breakevenMonths === Infinity ? 'N/A' : `${results.breakevenMonths} months`}</td></tr>
          </tbody>
        </table>
      </div>

      <button
        onClick={handleDownload}
        disabled={downloading}
        style={{ padding: '8px 24px', borderRadius: 4, border: 'none', background: '#0066ff', color: '#fff', cursor: 'pointer', fontSize: 14 }}
      >
        {downloading ? 'Generating...' : 'Download PDF Report'}
      </button>

      {pdfUrl && (
        <div style={{ marginTop: 16 }}>
          <h3>Report PDF</h3>
          <iframe src={pdfUrl} style={{ width: '100%', height: 600, border: '1px solid #ccc', borderRadius: 4 }} />
        </div>
      )}
    </div>
  )
}

export default App
