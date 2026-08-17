import { useState } from 'react'

type Step = 'idle' | 'loading' | 'editing' | 'diffing' | 'injecting' | 'stamping' | 'exporting' | 'verifying' | 'done' | 'error'

function App() {
  const [step, setStep] = useState<Step>('idle')
  const [error, setError] = useState('')
  const [opsUsed, setOpsUsed] = useState(0)
  const [pdfUrl, setPdfUrl] = useState<string | null>(null)
  const [editInstructions, setEditInstructions] = useState('')

  const steps: { key: Step; label: string }[] = [
    { key: 'loading', label: '1. Load document' },
    { key: 'editing', label: '2. Apply edits' },
    { key: 'diffing', label: '3. Diff' },
    { key: 'injecting', label: '4. Inject revision apparatus' },
    { key: 'stamping', label: '5. Stamp headers/footers' },
    { key: 'exporting', label: '6. Export PDF' },
    { key: 'verifying', label: '7. Verify PDF' },
    { key: 'done', label: 'Done' },
  ]

  const handleRun = async () => {
    setStep('loading')
    setError('')
    setOpsUsed(0)
    try {
      // TODO: implement actual API calls when Ticket 2 lands
      await new Promise(r => setTimeout(r, 500))
      setStep('done')
    } catch (e) {
      setError(String(e))
      setStep('error')
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
            {i < currentIdx ? '✅' : i === currentIdx ? '🔄' : '⬜'} {s.label}
          </div>
        ))}
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

      {pdfUrl && (
        <div style={{ marginTop: 16 }}>
          <h3>Exported PDF</h3>
          <iframe src={pdfUrl} style={{ width: '100%', height: 600, border: '1px solid #ccc', borderRadius: 4 }} />
        </div>
      )}
    </div>
  )
}

export default App
