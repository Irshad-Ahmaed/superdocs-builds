import { useState, useMemo } from 'react'
import DOMPurify from 'dompurify'

const TIERS = [
  { name: 'Free', max: 500, monthly: 0 },
  { name: 'Plus', max: 2000, monthly: 20 },
  { name: 'Pro', max: 10000, monthly: 99 },
]

function BarChart({ buildTotal, buyTotal, horizon }: { buildTotal: number; buyTotal: number; horizon: number }) {
  const maxVal = Math.max(buildTotal, buyTotal, 1)
  const buildPct = (buildTotal / maxVal) * 100
  const buyPct = (buyTotal / maxVal) * 100
  const fmt = (n: number) => n.toLocaleString('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: 0 })

  return (
    <div>
      <div style={{ display: 'flex', alignItems: 'center', marginBottom: 8 }}>
        <div style={{ width: 80, fontSize: 13, fontWeight: 600, color: '#666' }}>Build</div>
        <div style={{ flex: 1, background: '#f1f5f9', borderRadius: 4, height: 32, overflow: 'hidden' }}>
          <div style={{ width: `${buildPct}%`, background: 'linear-gradient(90deg, #f97316, #ea580c)', height: '100%', borderRadius: 4, display: 'flex', alignItems: 'center', paddingLeft: 8, minWidth: 60 }}>
            <span style={{ color: '#fff', fontSize: 12, fontWeight: 700 }}>{fmt(buildTotal)}</span>
          </div>
        </div>
      </div>
      <div style={{ display: 'flex', alignItems: 'center' }}>
        <div style={{ width: 80, fontSize: 13, fontWeight: 600, color: '#666' }}>Buy</div>
        <div style={{ flex: 1, background: '#f1f5f9', borderRadius: 4, height: 32, overflow: 'hidden' }}>
          <div style={{ width: `${buyPct}%`, background: 'linear-gradient(90deg, #22c55e, #16a34a)', height: '100%', borderRadius: 4, display: 'flex', alignItems: 'center', paddingLeft: 8, minWidth: 60 }}>
            <span style={{ color: '#fff', fontSize: 12, fontWeight: 700 }}>{fmt(buyTotal)}</span>
          </div>
        </div>
      </div>
      <div style={{ fontSize: 11, color: '#999', marginTop: 4 }}>Total cost over {horizon} years</div>
    </div>
  )
}

function ResultRow({ label, value, bold, color }: { label: string; value: string; bold?: boolean; color?: string }) {
  return (
    <tr>
      <td style={{ padding: '6px 12px', fontSize: 14 }}>{label}</td>
      <td style={{ padding: '6px 12px', fontSize: 14, fontWeight: bold ? 700 : 400, color: color || '#111', textAlign: 'right' }}>{value}</td>
    </tr>
  )
}

function App() {
  const [volume, setVolume] = useState(100)
  const [hours, setHours] = useState(200)
  const [hourlyCost, setHourlyCost] = useState(75)
  const [infra, setInfra] = useState(100)
  const [horizon, setHorizon] = useState(3)
  const [downloading, setDownloading] = useState(false)
  const [pdfDataUrl, setPdfDataUrl] = useState<string | null>(null)
  const [pdfHtml, setPdfHtml] = useState<string | null>(null)
  const [pdfPath, setPdfPath] = useState<string | null>(null)
  const [copiedPath, setCopiedPath] = useState(false)

  const results = useMemo(() => {
    const buildOneTime = hours * hourlyCost
    const buildMaintPerYear = hours * 0.2 * hourlyCost
    const buildInfraPerYear = infra * 12
    const buildTotal = buildOneTime + (buildMaintPerYear + buildInfraPerYear) * horizon

    const tier = volume <= 500 ? TIERS[0] : volume <= 2000 ? TIERS[1] : TIERS[2]
    const buyAnnual = tier.monthly * 12
    const buyTotal = buyAnnual * horizon

    const savings = buildTotal - buyTotal
    const savingsPct = buildTotal > 0 ? Math.round((savings / buildTotal) * 100) : 0
    const buildAnnualOp = buildMaintPerYear + buildInfraPerYear
    const annualOpSavings = buildAnnualOp - buyAnnual
    const buildBreakevenMonths = tier.monthly > 0 && annualOpSavings > 0 ? (buildOneTime / annualOpSavings) * 12 : null

    return {
      buildOneTime, buildMaintPerYear, buildInfraPerYear, buildTotal,
      buyTier: tier.name, buyAnnual, buyTotal, savings, savingsPct,
      buildBreakevenMonths,
    }
  }, [volume, hours, hourlyCost, infra, horizon])

  const fmt = (n: number) => n.toLocaleString('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: 0 })

  const handleDownload = async () => {
    setDownloading(true)
    setPdfDataUrl(null)
    setPdfHtml(null)
    setPdfPath(null)
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
      if (data.pdf_data_url) {
        setPdfDataUrl(data.pdf_data_url)
        // Automatically trigger browser download
        const link = document.createElement('a')
        link.href = data.pdf_data_url
        link.download = `superdocs-roi-report-${Date.now()}.pdf`
        document.body.appendChild(link)
        link.click()
        document.body.removeChild(link)
      }
      if (data.pdf_path) setPdfPath(data.pdf_path)
      if (data.html) setPdfHtml(data.html)
    } catch (e) {
      alert(String(e))
    } finally {
      setDownloading(false)
    }
  }

  return (
    <div style={{ maxWidth: 900, margin: '0 auto', padding: 24, fontFamily: 'system-ui, sans-serif' }}>
      <h1 style={{ marginBottom: 4 }}>Build B — Build vs Buy ROI Calculator</h1>
      <p style={{ color: '#666', marginTop: 0 }}>Compare the cost of building an in-house AI document pipeline vs using SuperDocs.</p>

      {/* Input grid */}
      <div style={{ background: '#f8f9fa', borderRadius: 8, padding: 16, marginBottom: 20, border: '1px solid #e9ecef' }}>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(5, 1fr)', gap: 12 }}>
          {[
            { label: 'Docs / month', value: volume, set: setVolume },
            { label: 'Eng. hours', value: hours, set: setHours },
            { label: 'Hourly cost ($)', value: hourlyCost, set: setHourlyCost },
            { label: 'Infra ($/mo)', value: infra, set: setInfra },
            { label: 'Horizon (yr)', value: horizon, set: setHorizon },
          ].map(f => (
            <div key={f.label}>
              <label style={{ display: 'block', marginBottom: 4, fontWeight: 600, fontSize: 12 }}>{f.label}</label>
              <input type="number" value={f.value} onChange={e => f.set(e.target.value === '' ? 0 : +e.target.value)}
                style={{ width: '100%', padding: 8, borderRadius: 4, border: '1px solid #ccc', fontSize: 14, boxSizing: 'border-box' }} />
            </div>
          ))}
        </div>
      </div>

      {/* Visual chart */}
      <div style={{ background: '#fff', borderRadius: 8, padding: 20, marginBottom: 20, border: '1px solid #e9ecef' }}>
        <h3 style={{ marginTop: 0, marginBottom: 16 }}>Cost Comparison — {horizon}-Year Horizon</h3>
        <BarChart buildTotal={results.buildTotal} buyTotal={results.buyTotal} horizon={horizon} />
      </div>

      {/* Detailed breakdown */}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16, marginBottom: 20 }}>
        {/* Build side */}
        <div style={{ background: '#fff7ed', borderRadius: 8, padding: 16, border: '1px solid #fed7aa' }}>
          <h3 style={{ marginTop: 0, color: '#c2410c', fontSize: 16 }}>Build In-House</h3>
          <table style={{ width: '100%', borderCollapse: 'collapse' }}>
            <tbody>
              <ResultRow label="One-time build" value={fmt(results.buildOneTime)} bold />
              <ResultRow label="Maintenance / yr" value={fmt(results.buildMaintPerYear)} />
              <ResultRow label="Infrastructure / yr" value={fmt(results.buildInfraPerYear)} />
              <tr><td colSpan={2}><hr style={{ border: 'none', borderTop: '1px solid #fed7aa', margin: '4px 0' }} /></td></tr>
              <ResultRow label={`Total (${horizon}yr)`} value={fmt(results.buildTotal)} bold color="#c2410c" />
            </tbody>
          </table>
        </div>

        {/* Buy side */}
        <div style={{ background: '#f0fdf4', borderRadius: 8, padding: 16, border: '1px solid #bbf7d0' }}>
          <h3 style={{ marginTop: 0, color: '#15803d', fontSize: 16 }}>Buy SuperDocs ({results.buyTier})</h3>
          <table style={{ width: '100%', borderCollapse: 'collapse' }}>
            <tbody>
              <ResultRow label="Monthly cost" value={fmt(results.buyAnnual / 12)} />
              <ResultRow label="Annual cost" value={fmt(results.buyAnnual)} />
              <tr><td colSpan={2}><hr style={{ border: 'none', borderTop: '1px solid #bbf7d0', margin: '4px 0' }} /></td></tr>
              <ResultRow label={`Total (${horizon}yr)`} value={fmt(results.buyTotal)} bold color="#15803d" />
            </tbody>
          </table>
        </div>
      </div>

      {/* Savings & ROI Metrics Callout */}
      <div style={{
        borderRadius: 8, padding: 20, marginBottom: 20, textAlign: 'center',
        background: results.savings > 0 ? 'linear-gradient(135deg, #f0fdf4, #dcfce7)' : 'linear-gradient(135deg, #fef2f2, #fecaca)',
        border: `2px solid ${results.savings > 0 ? '#86efac' : '#fca5a5'}`,
      }}>
        <div style={{ fontSize: 13, color: '#666', marginBottom: 4 }}>
          {results.savings > 0 ? 'You save with SuperDocs' : 'Building in-house is cheaper'}
        </div>
        <div style={{ fontSize: 36, fontWeight: 800, color: results.savings > 0 ? '#15803d' : '#dc2626' }}>
          {fmt(Math.abs(results.savings))}
        </div>
        <div style={{ fontSize: 14, color: '#666', marginBottom: 12 }}>
          {results.savings > 0 ? `${results.savingsPct}% net savings over ${horizon} years` : `building costs less over ${horizon} years`}
        </div>
        {results.savings > 0 && (
          <div style={{ display: 'flex', justifyContent: 'center', gap: 24, fontSize: 12, color: '#047857', borderTop: '1px solid #bbf7d0', paddingTop: 10 }}>
            <div><strong>SuperDocs Payback:</strong> Immediate (Day 1 — $0 CapEx)</div>
            {results.buildBreakevenMonths && (
              <div><strong>In-House Break-Even:</strong> {results.buildBreakevenMonths.toFixed(1)} months</div>
            )}
          </div>
        )}
      </div>

      {/* Export button */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 20 }}>
        <button onClick={handleDownload} disabled={downloading}
          style={{ padding: '10px 28px', borderRadius: 4, border: 'none', background: downloading ? '#93c5fd' : '#2563eb', color: '#fff', cursor: downloading ? 'wait' : 'pointer', fontSize: 14, fontWeight: 600 }}>
          {downloading ? 'Generating PDF Report...' : 'Generate PDF Report via SuperDocs'}
        </button>
        {pdfDataUrl && (
          <a
            href={pdfDataUrl}
            download={`superdocs-roi-report-${Date.now()}.pdf`}
            style={{
              padding: '10px 20px', borderRadius: 4,
              background: '#16a34a', color: '#fff',
              textDecoration: 'none', fontSize: 14, fontWeight: 600,
            }}
          >
            Download PDF Again
          </a>
        )}
      </div>

      {pdfPath && (
        <div style={{
          marginBottom: 20,
          background: '#ecfdf5',
          border: '1px solid #6ee7b7',
          borderRadius: 6,
          padding: 14,
        }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, color: '#065f46', fontWeight: 600, fontSize: 14 }}>
            <span>✅ ROI Report PDF Generated &amp; Downloaded Successfully!</span>
          </div>
          <div style={{ marginTop: 8, fontSize: 13, color: '#374151' }}>
            <strong>Saved Location (Local Sidecar):</strong>
            <div style={{
              display: 'flex', alignItems: 'center', gap: 8, marginTop: 4,
              background: '#ffffff', padding: '6px 10px', borderRadius: 4,
              border: '1px solid #d1d5db', fontFamily: 'monospace', fontSize: 12,
              wordBreak: 'break-all',
            }}>
              <span style={{ flex: 1 }}>{pdfPath}</span>
              <button
                onClick={() => {
                  navigator.clipboard.writeText(pdfPath)
                  setCopiedPath(true)
                  setTimeout(() => setCopiedPath(false), 2000)
                }}
                style={{
                  padding: '3px 8px', fontSize: 11, background: '#f3f4f6',
                  border: '1px solid #d1d5db', borderRadius: 3, cursor: 'pointer',
                }}
              >
                {copiedPath ? '✓ Copied' : 'Copy Path'}
              </button>
            </div>
            <div style={{ marginTop: 6, fontSize: 12, color: '#047857' }}>
              📥 The PDF has also been sent to your browser's <strong>Downloads</strong> folder.
            </div>
          </div>
        </div>
      )}

      {/* PDF preview */}
      {pdfDataUrl && (
        <div style={{ marginTop: 8 }}>
          <h3>Generated PDF Report</h3>
          <iframe src={pdfDataUrl} style={{ width: '100%', height: 600, border: '1px solid #ddd', borderRadius: 6 }} title="PDF Report" />
        </div>
      )}

      {/* HTML fallback preview */}
      {pdfHtml && !pdfDataUrl && (
        <div style={{ marginTop: 8 }}>
          <h3>Generated Report (HTML Preview)</h3>
          <div style={{ border: '1px solid #ddd', borderRadius: 6, padding: 16, background: '#fff', maxHeight: 400, overflow: 'auto' }}
            dangerouslySetInnerHTML={{ __html: DOMPurify.sanitize(pdfHtml) }} />
        </div>
      )}
    </div>
  )
}

export default App
