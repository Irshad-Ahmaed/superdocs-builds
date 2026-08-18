import { useState } from 'react'

type Step = 'idle' | 'loading' | 'editing' | 'diffing' | 'injecting' | 'stamping' | 'exporting' | 'verifying' | 'done' | 'error'

const API = '/api'

const SAMPLE_HTML = `<html><body>
<h1>Flight Crew Operating Manual</h1>
<p>Section 4.1: Normal Procedures</p>
<p>The aircraft must be inspected before every flight.</p>
<p>Minimum crew complement: 2 pilots.</p>
</body></html>`

function App() {
  const [step, setStep] = useState<Step>('idle')
  const [error, setError] = useState('')
  const [opsUsed, setOpsUsed] = useState(0)
  const [pdfUrl, setPdfUrl] = useState<string | null>(null)
  const [editInstructions, setEditInstructions] = useState('')
  const [revisionNumber, setRevisionNumber] = useState('0042')
  const [date, setDate] = useState('2025-01-15')
  const [log, setLog] = useState<string[]>([])

  const steps: { key: Step; label: string }[] = [
    { key: 'loading', label: '1. Load document' },
    { key: 'editing', label: '2. Apply edits' },
    { key: 'diffing', label: '3. Diff' },
    { key: 'injecting', label: '4. Inject revision apparatus' },
    { key: 'stamping', label: '5. Stamp headers/footers' },
    { key: 'exporting', label: '6. Export PDF' },
    { key: 'done', label: 'Done' },
  ]

  const addLog = (msg: string) => setLog(prev => [...prev, msg])

  const handleRun = async () => {
    setStep('loading')
    setError('')
    setOpsUsed(0)
    setPdfUrl(null)
    setLog([])
    try {
      // Step 1-4: Full pipeline (load + edit + diff + apparatus)
      addLog('Starting revision pipeline...')
      const pipelineRes = await fetch(`${API}/pipeline`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          session_id: `revision-${revisionNumber}-${Date.now()}`,
          document_html: SAMPLE_HTML,
          edit_instructions: editInstructions || `Update crew complement from 2 to 3 pilots for long-haul`,
          revision_number: revisionNumber,
          date: date,
          changes: [editInstructions || 'Updated crew complement for long-haul'],
          highlights_summary: 'Crew requirement increased from 2 to 3 for long-haul flights',
        }),
      })
      if (!pipelineRes.ok) throw new Error(`Pipeline failed: ${pipelineRes.statusText}`)
      const pipeline = await pipelineRes.json()
      addLog(`Pipeline complete: ${pipeline.changes_count} changes, ${pipeline.ops_used} ops`)
      setOpsUsed(pipeline.ops_used)
      setStep('injecting')

      // Step 5: Stamp headers/footers
      addLog('Stamping headers and footers...')
      const stampRes = await fetch(`${API}/stamp`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          session_id: `revision-${revisionNumber}-${Date.now()}`,
          revision_number: revisionNumber,
          date: date,
        }),
      })
      if (!stampRes.ok) throw new Error(`Stamp failed: ${stampRes.statusText}`)
      const stamp = await stampRes.json()
      addLog(`Headers: ${stamp.header_text}`)
      setOpsUsed(prev => prev + stamp.ops_used)
      setStep('done')
      addLog('Done!')
    } catch (e) {
      setError(String(e))
      setStep('error')
      addLog(`Error: ${e}`)
    }
  }

  const currentIdx = steps.findIndex(s => s.key === step)

  return (
    <div style={{ maxWidth: 800, margin: '0 auto', padding: 24, fontFamily: 'system-ui, sans-serif' }}>
      <h1>Build A — Revision Bars &amp; Controlled Document Generator</h1>
      <p style={{ color: '#666' }}>
        Aviation-grade revision apparatus: change bars, record table, highlights — all via SuperDocs chat.
      </p>

      <div style={{ background: '#f5f5f5', borderRadius: 8, padding: 16, marginBottom: 16 }}>
        <h3>Progress</h3>
        {steps.map((s, i) => (
          <div key={s.key} style={{ padding: '4px 0', color: i <= currentIdx ? '#000' : '#999' }}>
            {i < currentIdx ? '\u2705' : i === currentIdx ? '\U0001f504' : '\u2B1C'} {s.label}
          </div>
        ))}
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12, marginBottom: 16 }}>
        <div>
          <label style={{ display: 'block', marginBottom: 4, fontWeight: 600 }}>Revision Number</label>
          <input
            value={revisionNumber}
            onChange={e => setRevisionNumber(e.target.value)}
            style={{ width: '100%', padding: 8, borderRadius: 4, border: '1px solid #ccc' }}
          />
        </div>
        <div>
          <label style={{ display: 'block', marginBottom: 4, fontWeight: 600 }}>Date</label>
          <input
            value={date}
            onChange={e => setDate(e.target.value)}
            style={{ width: '100%', padding: 8, borderRadius: 4, border: '1px solid #ccc' }}
          />
        </div>
      </div>

      <div style={{ marginBottom: 16 }}>
        <label style={{ display: 'block', marginBottom: 4, fontWeight: 600 }}>Edit instructions</label>
        <textarea
          value={editInstructions}
          onChange={e => setEditInstructions(e.target.value)}
          placeholder="e.g. Update section 4.2 with new safety threshold..."
          style={{ width: '100%', minHeight: 80, padding: 8, borderRadius: 4, border: '1px solid #ccc' }}
        />
      </div>

      <button
        onClick={handleRun}
        disabled={step !== 'idle' && step !== 'done' && step !== 'error'}
        style={{ padding: '8px 24px', borderRadius: 4, border: 'none', background: '#0066ff', color: '#fff', cursor: 'pointer', fontSize: 14 }}
      >
        Run
      </button>

      <div style={{ marginTop: 12, color: '#666' }}>Operations used: {opsUsed}</div>

      {error && <div style={{ marginTop: 12, color: 'red', padding: 8, background: '#fee', borderRadius: 4 }}>Error: {error}</div>}

      {log.length > 0 && (
        <div style={{ marginTop: 16, background: '#1a1a2e', color: '#0f0', padding: 12, borderRadius: 8, fontFamily: 'monospace', fontSize: 13, maxHeight: 200, overflow: 'auto' }}>
          {log.map((line, i) => <div key={i}>{line}</div>)}
        </div>
      )}
    </div>
  )
}

export default App
