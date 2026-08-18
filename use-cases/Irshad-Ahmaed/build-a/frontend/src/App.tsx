import { useState } from 'react'

type Step = 'idle' | 'running' | 'done' | 'error'

interface DiffEntry {
  position: number
  change_type: string
  old_text: string
  new_text: string
}

interface PipelineResult {
  success: boolean
  ops_used: number
  changes_count: number
  apparatus_instructions: string[]
  errors: string[]
  diff_entries: DiffEntry[]
  total_paragraphs_old: number
  total_paragraphs_new: number
  pre_edit_html: string
  post_edit_html: string
}

const API = '/api'

const SAMPLE_HTML = `<html><body>
<h1>Flight Crew Operating Manual</h1>
<p>Section 4.1: Normal Procedures</p>
<p>The aircraft must be inspected before every flight.</p>
<p>Minimum crew complement: 2 pilots.</p>
<p>Section 4.2: Emergency Procedures</p>
<p>In case of engine failure, follow the single-engine approach procedure.</p>
<p>Declare emergency on frequency 121.5 and divert to nearest suitable airport.</p>
<p>Section 4.3: Communication Protocol</p>
<p>All crew members must monitor VHF Channel 121.5 during flight.</p>
<p>Standard phraseology must be used at all times.</p>
</body></html>`

function DiffView({ entries }: { entries: DiffEntry[] }) {
  if (entries.length === 0) return <p style={{ color: '#888' }}>No changes detected.</p>
  return (
    <div>
      {entries.map((e, i) => (
        <div key={i} style={{ marginBottom: 12, borderRadius: 6, overflow: 'hidden', border: '1px solid #e0e0e0' }}>
          <div style={{ background: '#f0f0f0', padding: '4px 12px', fontSize: 12, fontWeight: 600, color: '#555' }}>
            Paragraph {e.position} — <span style={{ color: e.change_type === 'modified' ? '#d97706' : e.change_type === 'added' ? '#16a34a' : '#dc2626' }}>{e.change_type}</span>
          </div>
          {e.old_text && (
            <div style={{ padding: '8px 12px', background: '#fef2f2', borderLeft: '3px solid #dc2626', fontFamily: 'monospace', fontSize: 13 }}>
              <span style={{ color: '#991b1b', marginRight: 8 }}>-</span>
              {e.old_text}
            </div>
          )}
          {e.new_text && (
            <div style={{ padding: '8px 12px', background: '#f0fdf4', borderLeft: '3px solid #16a34a', fontFamily: 'monospace', fontSize: 13 }}>
              <span style={{ color: '#166534', marginRight: 8 }}>+</span>
              {e.new_text}
            </div>
          )}
        </div>
      ))}
    </div>
  )
}

function DocumentPreview({ html, label }: { html: string; label: string }) {
  return (
    <div>
      <div style={{ fontSize: 12, fontWeight: 600, color: '#666', marginBottom: 4 }}>{label}</div>
      <div
        style={{ border: '1px solid #ddd', borderRadius: 6, padding: 16, background: '#fff', fontFamily: 'serif', fontSize: 14, lineHeight: 1.6, maxHeight: 250, overflow: 'auto' }}
        dangerouslySetInnerHTML={{ __html: html }}
      />
    </div>
  )
}

function App() {
  const [step, setStep] = useState<Step>('idle')
  const [error, setError] = useState('')
  const [opsUsed, setOpsUsed] = useState(0)
  const [editInstructions, setEditInstructions] = useState('')
  const [revisionNumber, setRevisionNumber] = useState('0042')
  const [date, setDate] = useState('2025-01-15')
  const [result, setResult] = useState<PipelineResult | null>(null)
  const [stampResult, setStampResult] = useState<{ header_text: string; footer_text: string; ops_used: number } | null>(null)
  const [log, setLog] = useState<string[]>([])

  const addLog = (msg: string) => setLog(prev => [...prev, msg])

  const handleRun = async () => {
    setStep('running')
    setError('')
    setOpsUsed(0)
    setResult(null)
    setStampResult(null)
    setLog([])
    const sid = `revision-${revisionNumber}-${Date.now()}`
    try {
      addLog('Starting revision pipeline...')
      const pipelineRes = await fetch(`${API}/pipeline`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          session_id: sid,
          document_html: SAMPLE_HTML,
          edit_instructions: editInstructions || `Update section 4.1: change minimum crew complement from 2 pilots to 3 pilots for long-haul flights. Add a note that both pilots must hold type ratings.`,
          revision_number: revisionNumber,
          date: date,
          changes: [editInstructions || 'Updated crew complement from 2 to 3 pilots for long-haul flights; added type rating requirement'],
          highlights_summary: 'Crew requirement increased from 2 to 3 for long-haul flights; type rating mandate added',
        }),
      })
      if (!pipelineRes.ok) throw new Error(`Pipeline failed: ${pipelineRes.statusText}`)
      const pipeline = await pipelineRes.json() as PipelineResult
      addLog(`Pipeline complete: ${pipeline.changes_count} changes detected, ${pipeline.ops_used} ops used`)
      setOpsUsed(pipeline.ops_used)
      setResult(pipeline)

      addLog('Stamping headers and footers...')
      const stampRes = await fetch(`${API}/stamp`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          session_id: sid,
          revision_number: revisionNumber,
          date: date,
        }),
      })
      if (!stampRes.ok) throw new Error(`Stamp failed: ${stampRes.statusText}`)
      const stamp = await stampRes.json()
      addLog(`Headers: ${stamp.header_text} | Footer: ${stamp.footer_text}`)
      setStampResult(stamp)
      setOpsUsed(prev => prev + stamp.ops_used)
      setStep('done')
      addLog('Done!')
    } catch (e) {
      setError(String(e))
      setStep('error')
      addLog(`Error: ${e}`)
    }
  }

  return (
    <div style={{ maxWidth: 900, margin: '0 auto', padding: 24, fontFamily: 'system-ui, sans-serif' }}>
      <h1 style={{ marginBottom: 4 }}>Build A — Revision Bars &amp; Controlled Document Generator</h1>
      <p style={{ color: '#666', marginTop: 0 }}>Aviation-grade revision apparatus: change bars, record table, highlights — all via SuperDocs chat.</p>

      {/* Input controls */}
      <div style={{ background: '#f8f9fa', borderRadius: 8, padding: 16, marginBottom: 16, border: '1px solid #e9ecef' }}>
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12, marginBottom: 12 }}>
          <div>
            <label style={{ display: 'block', marginBottom: 4, fontWeight: 600, fontSize: 13 }}>Revision Number</label>
            <input value={revisionNumber} onChange={e => setRevisionNumber(e.target.value)}
              style={{ width: '100%', padding: 8, borderRadius: 4, border: '1px solid #ccc', fontSize: 14 }} />
          </div>
          <div>
            <label style={{ display: 'block', marginBottom: 4, fontWeight: 600, fontSize: 13 }}>Date</label>
            <input value={date} onChange={e => setDate(e.target.value)}
              style={{ width: '100%', padding: 8, borderRadius: 4, border: '1px solid #ccc', fontSize: 14 }} />
          </div>
        </div>
        <div style={{ marginBottom: 12 }}>
          <label style={{ display: 'block', marginBottom: 4, fontWeight: 600, fontSize: 13 }}>Edit instructions</label>
          <textarea value={editInstructions} onChange={e => setEditInstructions(e.target.value)}
            placeholder="e.g. Update crew complement from 2 to 3 pilots for long-haul"
            style={{ width: '100%', minHeight: 60, padding: 8, borderRadius: 4, border: '1px solid #ccc', fontSize: 14, resize: 'vertical' }} />
        </div>
        <button onClick={handleRun} disabled={step === 'running'}
          style={{ padding: '10px 28px', borderRadius: 4, border: 'none', background: step === 'running' ? '#93c5fd' : '#2563eb', color: '#fff', cursor: step === 'running' ? 'wait' : 'pointer', fontSize: 14, fontWeight: 600 }}>
          {step === 'running' ? 'Running...' : 'Run Pipeline'}
        </button>
        <span style={{ marginLeft: 16, color: '#666', fontSize: 13 }}>Ops used: {opsUsed}</span>
      </div>

      {error && (
        <div style={{ marginBottom: 16, color: '#991b1b', padding: 12, background: '#fef2f2', borderRadius: 6, border: '1px solid #fecaca' }}>
          Error: {error}
        </div>
      )}

      {/* Log */}
      {log.length > 0 && (
        <div style={{ marginBottom: 16, background: '#1e293b', color: '#a5f3fc', padding: 12, borderRadius: 8, fontFamily: 'monospace', fontSize: 12, maxHeight: 120, overflow: 'auto' }}>
          {log.map((line, i) => <div key={i}>{`> ${line}`}</div>)}
        </div>
      )}

      {/* Results */}
      {result && (
        <div>
          {/* Summary cards */}
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 12, marginBottom: 20 }}>
            <div style={{ background: result.success ? '#f0fdf4' : '#fef2f2', borderRadius: 8, padding: 16, textAlign: 'center', border: `1px solid ${result.success ? '#bbf7d0' : '#fecaca'}` }}>
              <div style={{ fontSize: 28, fontWeight: 700, color: result.success ? '#166534' : '#991b1b' }}>{result.changes_count}</div>
              <div style={{ fontSize: 12, color: '#666' }}>Changes Detected</div>
            </div>
            <div style={{ background: '#eff6ff', borderRadius: 8, padding: 16, textAlign: 'center', border: '1px solid #bfdbfe' }}>
              <div style={{ fontSize: 28, fontWeight: 700, color: '#1e40af' }}>{result.ops_used}</div>
              <div style={{ fontSize: 12, color: '#666' }}>Operations Used</div>
            </div>
            <div style={{ background: '#f5f3ff', borderRadius: 8, padding: 16, textAlign: 'center', border: '1px solid #ddd6fe' }}>
              <div style={{ fontSize: 28, fontWeight: 700, color: '#6d28d9' }}>{result.apparatus_instructions.length}</div>
              <div style={{ fontSize: 12, color: '#666' }}>Apparatus Batches</div>
            </div>
          </div>

          {/* Document before/after */}
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16, marginBottom: 20 }}>
            <DocumentPreview html={result.pre_edit_html} label="BEFORE (Original)" />
            <DocumentPreview html={result.post_edit_html || result.pre_edit_html} label="AFTER (With Revisions)" />
          </div>

          {/* Diff */}
          <div style={{ marginBottom: 20 }}>
            <h3 style={{ marginTop: 0 }}>Document Diff</h3>
            <div style={{ fontSize: 13, color: '#666', marginBottom: 8 }}>
              Comparing {result.total_paragraphs_old} old paragraphs vs {result.total_paragraphs_new} new paragraphs
            </div>
            <DiffView entries={result.diff_entries} />
          </div>

          {/* Apparatus instructions */}
          {result.apparatus_instructions.length > 0 && (
            <div style={{ marginBottom: 20 }}>
              <h3 style={{ marginTop: 0 }}>Apparatus Instructions Sent to SuperDocs</h3>
              {result.apparatus_instructions.map((instr, i) => (
                <div key={i} style={{ background: '#fffbeb', border: '1px solid #fde68a', borderRadius: 6, padding: 12, marginBottom: 8, fontSize: 13, lineHeight: 1.5 }}>
                  <div style={{ fontWeight: 600, marginBottom: 4, color: '#92400e' }}>Batch {i + 1}</div>
                  <div style={{ whiteSpace: 'pre-wrap', fontFamily: 'monospace', fontSize: 12 }}>{instr}</div>
                </div>
              ))}
            </div>
          )}

          {/* Stamp result */}
          {stampResult && (
            <div style={{ background: '#f0fdf4', border: '1px solid #bbf7d0', borderRadius: 8, padding: 16 }}>
              <h3 style={{ marginTop: 0, color: '#166534' }}>Header/Footer Stamped</h3>
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
                <div>
                  <div style={{ fontSize: 12, color: '#666' }}>Header</div>
                  <div style={{ fontWeight: 600 }}>{stampResult.header_text}</div>
                </div>
                <div>
                  <div style={{ fontSize: 12, color: '#666' }}>Footer</div>
                  <div style={{ fontWeight: 600 }}>{stampResult.footer_text}</div>
                </div>
              </div>
            </div>
          )}

          {/* Errors */}
          {result.errors.length > 0 && (
            <div style={{ marginTop: 16, background: '#fef2f2', border: '1px solid #fecaca', borderRadius: 6, padding: 12 }}>
              <div style={{ fontWeight: 600, color: '#991b1b', marginBottom: 4 }}>Errors</div>
              {result.errors.map((err, i) => <div key={i} style={{ fontSize: 13, color: '#991b1b' }}>{err}</div>)}
            </div>
          )}
        </div>
      )}
    </div>
  )
}

export default App
