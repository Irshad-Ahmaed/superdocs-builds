import { useState, useRef } from 'react'
import DOMPurify from 'dompurify'

type Step = 'idle' | 'running' | 'done' | 'error'
type PipelineStep = 'idle' | 'load-edit' | 'apparatus' | 'stamp' | 'done'

interface DiffEntry {
  position: number
  change_type: string
  old_text: string
  new_text: string
}

interface LoadEditResult {
  success: boolean
  ops_used: number
  pre_edit_html: string
  post_edit_html: string
  response_text: string
  errors: string[]
}

interface ApparatusResult {
  success: boolean
  ops_used: number
  changes_count: number
  apparatus_instructions: string[]
  diff_entries: DiffEntry[]
  total_paragraphs_old: number
  total_paragraphs_new: number
  errors: string[]
}

interface StampResult {
  header_text: string
  footer_text: string
  ops_used: number
  verified_header: boolean
  verified_footer: boolean
}

const API = '/api'

const SAMPLE_HTML = `<html><body>
<h1>Flight Crew Operating Manual — Rev 0043</h1>
<p>Section 4.1: Normal Procedures</p>
<p>The aircraft must be inspected before every flight per the checklist in Appendix B.</p>
<p>Minimum crew complement: 2 pilots for domestic operations.</p>
<p>Both pilots must hold valid first-class medical certificates.</p>
<p>Section 4.2: Emergency Procedures</p>
<p>In case of engine failure, follow the single-engine approach procedure in 4.2.1.</p>
<p>Declare emergency on frequency 121.5 and divert to nearest suitable airport.</p>
<p>The pilot-in-command must brief all passengers before emergency landing.</p>
<p>Section 4.3: Communication Protocol</p>
<p>All crew members must monitor VHF Channel 121.5 during flight.</p>
<p>Standard phraseology must be used at all times per ICAO Annex 10.</p>
<p>Section 4.4: Documentation Requirements</p>
<p>Flight logs must be completed within 24 hours of landing.</p>
<p>Maintenance reports filed in the central system before end of shift.</p>
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
        dangerouslySetInnerHTML={{ __html: DOMPurify.sanitize(html) }}
      />
    </div>
  )
}

interface LogEntry {
  msg: string
}

function App() {
  const [step, setStep] = useState<Step>('idle')
  const [pipelineStep, setPipelineStep] = useState<PipelineStep>('idle')
  const [error, setError] = useState('')
  const [totalOps, setTotalOps] = useState(0)
  const [editInstructions, setEditInstructions] = useState('')
  const [revisionNumber, setRevisionNumber] = useState('0042')
  const [date, setDate] = useState('2025-01-15')
  const [preEditHtml, setPreEditHtml] = useState('')
  const [postEditHtml, setPostEditHtml] = useState('')
  const [diffEntries, setDiffEntries] = useState<DiffEntry[]>([])
  const [apparatusInstructions, setApparatusInstructions] = useState<string[]>([])
  const [stampResult, setStampResult] = useState<StampResult | null>(null)
  const [log, setLog] = useState<LogEntry[]>([])
  const [stepTimers, setStepTimers] = useState<Record<string, number>>({})
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null)
  const [elapsed, setElapsed] = useState(0)

  const addLog = (msg: string) => setLog(prev => [...prev, { msg }])

  const startTimer = () => {
    setElapsed(0)
    timerRef.current = setInterval(() => setElapsed(prev => prev + 100), 100)
  }

  const stopTimer = () => {
    if (timerRef.current) {
      clearInterval(timerRef.current)
      timerRef.current = null
    }
  }

  const timeSince = (start: number) => `${((Date.now() - start) / 1000).toFixed(1)}s`

  const handleRun = async () => {
    setStep('running')
    setPipelineStep('load-edit')
    setError('')
    setTotalOps(0)
    setPreEditHtml('')
    setPostEditHtml('')
    setDiffEntries([])
    setApparatusInstructions([])
    setStampResult(null)
    setLog([])
    setStepTimers({})
    startTimer()

    const sid = `revision-${revisionNumber}-${Date.now()}`
    const instructions = editInstructions || `Update section 4.1: change minimum crew complement from 2 pilots to 3 pilots for long-haul flights. Add a note that both pilots must hold type ratings.`
    const changes = [editInstructions || 'Updated crew complement from 2 to 3 pilots for long-haul flights; added type rating requirement']

    try {
      let runningOps = 0

      // ── Step 1: Load + Edit ──
      const t1 = Date.now()
      addLog('Step 1/3: Loading document + applying edits via SuperDocs API...')

      const loadEditRes = await fetch(`${API}/step/load-edit`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          session_id: sid,
          document_html: SAMPLE_HTML,
          edit_instructions: instructions,
        }),
      })
      if (!loadEditRes.ok) throw new Error(`Load+Edit failed: ${loadEditRes.statusText}`)
      const loadEdit = await loadEditRes.json() as LoadEditResult
      if (!loadEdit.success) throw new Error(loadEdit.errors.join(', '))

      // Use pre-edit HTML from session (actual current state), not hardcoded SAMPLE_HTML
      const actualPreEdit = loadEdit.pre_edit_html || SAMPLE_HTML
      setPreEditHtml(actualPreEdit)

      const t1Done = Date.now()
      setStepTimers(prev => ({ ...prev, 'load-edit': t1Done - t1 }))
      addLog(`Step 1 complete in ${timeSince(t1)} — ${loadEdit.ops_used} op(s). Response: "${loadEdit.response_text.slice(0, 80)}..."`)
      setPostEditHtml(loadEdit.post_edit_html)
      runningOps += loadEdit.ops_used
      setTotalOps(runningOps)

      // ── Step 2+3: Apparatus + Stamp in parallel (only if changes detected) ──
      setPipelineStep('apparatus')
      const t2 = Date.now()

      // Run apparatus first to check for changes
      addLog('Step 2/3: Running local diff + generating apparatus instructions...')
      const appRes = await fetch(`${API}/step/apparatus`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          session_id: sid,
          pre_edit_html: actualPreEdit,
          post_edit_html: loadEdit.post_edit_html,
          revision_number: revisionNumber,
          date: date,
          changes: changes,
          highlights_summary: 'Crew requirement increased from 2 to 3 for long-haul flights; type rating mandate added',
        }),
      })
      if (!appRes.ok) throw new Error(`Apparatus failed: ${appRes.statusText}`)
      const apparatus = await appRes.json() as ApparatusResult
      if (!apparatus.success) throw new Error(apparatus.errors.join(', '))

      setDiffEntries(apparatus.diff_entries)
      setApparatusInstructions(apparatus.apparatus_instructions)
      runningOps += apparatus.ops_used

      const t2Done = Date.now()
      setStepTimers(prev => ({ ...prev, 'apparatus': t2Done - t2 }))
      addLog(`Apparatus: ${apparatus.changes_count} changes, ${apparatus.ops_used} op(s)`)

      // Only stamp if there are actual changes (avoids wasting 1 op on no-op stamp)
      let stamp: StampResult | null = null
      if (apparatus.changes_count > 0) {
        addLog('Step 3/3: Stamping headers and footers...')
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
        stamp = await stampRes.json() as StampResult
        addLog(`Stamp: ${stamp.header_text} — ${stamp.footer_text}`)
        addLog(`  Header verified: ${stamp.verified_header ? '✓' : '✗'}`)
        addLog(`  Footer verified: ${stamp.verified_footer ? '✓' : '✗ — check document manually'}`)
        setStampResult(stamp)
        runningOps += stamp.ops_used
      } else {
        addLog('No changes detected — skipping stamp (already applied)')
      }

      setTotalOps(runningOps)

      setPipelineStep('done')
      stopTimer()
      const totalTime = ((t2Done - t1) / 1000).toFixed(1)
      addLog(`All done in ${totalTime}s — ${runningOps} total ops`)
      setStep('done')
    } catch (e) {
      stopTimer()
      setError(String(e))
      setStep('error')
      setPipelineStep('idle')
      addLog(`Error: ${e}`)
    }
  }

  const formatMs = (ms: number) => ms >= 1000 ? `${(ms / 1000).toFixed(1)}s` : `${ms}ms`

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
        <div style={{ display: 'flex', alignItems: 'center', gap: 16 }}>
          <button onClick={handleRun} disabled={step === 'running'}
            style={{ padding: '10px 28px', borderRadius: 4, border: 'none', background: step === 'running' ? '#93c5fd' : '#2563eb', color: '#fff', cursor: step === 'running' ? 'wait' : 'pointer', fontSize: 14, fontWeight: 600 }}>
            {step === 'running' ? `Running ${pipelineStep}...` : 'Run Pipeline'}
          </button>
          {step === 'running' && (
            <span style={{ color: '#666', fontSize: 13, fontVariantNumeric: 'tabular-nums' }}>
              {formatMs(elapsed)} elapsed
            </span>
          )}
          {step === 'done' && (
            <span style={{ color: '#16a34a', fontSize: 13, fontWeight: 600 }}>
              Total: {totalOps} ops in {formatMs(elapsed)}
            </span>
          )}
        </div>
      </div>

      {error && (
        <div style={{ marginBottom: 16, color: '#991b1b', padding: 12, background: '#fef2f2', borderRadius: 6, border: '1px solid #fecaca' }}>
          Error: {error}
        </div>
      )}

      {/* Live log */}
      {log.length > 0 && (
        <div style={{ marginBottom: 16, background: '#1e293b', color: '#a5f3fc', padding: 12, borderRadius: 8, fontFamily: 'monospace', fontSize: 12, maxHeight: 200, overflow: 'auto' }}>
          {log.map((entry, i) => (
            <div key={i} style={{ display: 'flex', gap: 8 }}>
              <span style={{ color: '#475569' }}>{String(i + 1).padStart(2, ' ')}</span>
              <span>{`> ${entry.msg}`}</span>
            </div>
          ))}
          {step === 'running' && <div style={{ color: '#fbbf24' }}>{'> '}{pipelineStep === 'load-edit' ? 'Waiting for SuperDocs API...' : pipelineStep === 'apparatus' ? 'Processing...' : 'Stamping...'}</div>}
        </div>
      )}

      {/* Progress steps */}
      {step === 'running' && (
        <div style={{ marginBottom: 20, display: 'flex', gap: 8 }}>
          {(['load-edit', 'apparatus', 'stamp'] as const).map((s, i) => {
            const isDone = ['apparatus', 'stamp', 'done'].includes(pipelineStep) && i === 0
              || ['stamp', 'done'].includes(pipelineStep) && i === 1
              || pipelineStep === 'done' && i === 2
            const isCurrent = (pipelineStep === 'load-edit' && i === 0)
              || (pipelineStep === 'apparatus' && i === 1)
              || (pipelineStep === 'stamp' && i === 2)
            return (
              <div key={s} style={{
                flex: 1, padding: '8px 12px', borderRadius: 6, fontSize: 12, fontWeight: 600, textAlign: 'center',
                background: isDone ? '#f0fdf4' : isCurrent ? '#eff6ff' : '#f8f9fa',
                border: `1px solid ${isDone ? '#bbf7d0' : isCurrent ? '#bfdbfe' : '#e9ecef'}`,
                color: isDone ? '#166534' : isCurrent ? '#1e40af' : '#999',
              }}>
                {isDone ? '✓' : isCurrent ? '●' : '○'} {i + 1}. {s === 'load-edit' ? 'Load + Edit' : s === 'apparatus' ? 'Diff + Apparatus' : 'Stamp'}
                {isDone && stepTimers[s] ? ` (${formatMs(stepTimers[s])})` : ''}
              </div>
            )
          })}
        </div>
      )}

      {/* Results — appear progressively */}
      {(postEditHtml || diffEntries.length > 0 || apparatusInstructions.length > 0 || stampResult) && (
        <div>
          {/* Summary cards */}
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 12, marginBottom: 20 }}>
            <div style={{ background: diffEntries.length > 0 ? '#f0fdf4' : '#f8f9fa', borderRadius: 8, padding: 16, textAlign: 'center', border: `1px solid ${diffEntries.length > 0 ? '#bbf7d0' : '#e9ecef'}` }}>
              <div style={{ fontSize: 28, fontWeight: 700, color: diffEntries.length > 0 ? '#166534' : '#999' }}>{diffEntries.length}</div>
              <div style={{ fontSize: 12, color: '#666' }}>Changes Detected</div>
            </div>
            <div style={{ background: '#eff6ff', borderRadius: 8, padding: 16, textAlign: 'center', border: '1px solid #bfdbfe' }}>
              <div style={{ fontSize: 28, fontWeight: 700, color: '#1e40af' }}>{totalOps}</div>
              <div style={{ fontSize: 12, color: '#666' }}>Total Operations</div>
            </div>
            <div style={{ background: '#f5f3ff', borderRadius: 8, padding: 16, textAlign: 'center', border: '1px solid #ddd6fe' }}>
              <div style={{ fontSize: 28, fontWeight: 700, color: '#6d28d9' }}>{apparatusInstructions.length}</div>
              <div style={{ fontSize: 12, color: '#666' }}>Apparatus Batches</div>
            </div>
          </div>

          {/* Document before/after */}
          {postEditHtml && (
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16, marginBottom: 20 }}>
              <DocumentPreview html={preEditHtml || SAMPLE_HTML} label="BEFORE (Original)" />
              <DocumentPreview html={postEditHtml} label="AFTER (With Revisions)" />
            </div>
          )}

          {/* Diff */}
          {diffEntries.length > 0 && (
            <div style={{ marginBottom: 20 }}>
              <h3 style={{ marginTop: 0 }}>Document Diff</h3>
              <DiffView entries={diffEntries} />
            </div>
          )}

          {/* Apparatus instructions */}
          {apparatusInstructions.length > 0 && (
            <div style={{ marginBottom: 20 }}>
              <h3 style={{ marginTop: 0 }}>Apparatus Instructions Sent to SuperDocs</h3>
              {apparatusInstructions.map((instr, i) => (
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
                  <div style={{ fontSize: 12, color: '#666' }}>Header {stampResult.verified_header ? '✓ verified' : '— unverified'}</div>
                  <div style={{ fontWeight: 600 }}>{stampResult.header_text}</div>
                </div>
                <div>
                  <div style={{ fontSize: 12, color: stampResult.verified_footer ? '#666' : '#d97706' }}>
                    Footer {stampResult.verified_footer ? '✓ verified' : '⚠ not rendered (SuperDocs may not support dynamic page numbering)'}
                  </div>
                  <div style={{ fontWeight: 600 }}>{stampResult.footer_text}</div>
                </div>
              </div>
            </div>
          )}
        </div>
      )}

      {/* How it works */}
      <div style={{ marginTop: 32, background: '#f8f9fa', borderRadius: 8, padding: 20, border: '1px solid #e9ecef' }}>
        <h2 style={{ marginTop: 0, fontSize: 18 }}>How It Works</h2>
        <div style={{ fontSize: 13, lineHeight: 1.7, color: '#444' }}>
          <p><strong>Architecture:</strong> React Frontend → REST API → Python FastAPI Sidecar → SuperDocs REST API</p>
          <p><strong>Pipeline steps (3 sequential API calls):</strong></p>
          <ol style={{ paddingLeft: 20, marginTop: 4 }}>
            <li><strong>Load + Edit (1 op, ~5-15s):</strong> Document HTML is loaded into a SuperDocs session and edit instructions are applied in a single API call. This is the slow step — SuperDocs processes the document on their servers.</li>
            <li><strong>Diff + Apparatus (1+ ops, ~1s):</strong> The sidecar compares pre-edit vs post-edit HTML locally (fast). Then sends change bars, revision-record table, and highlights as chat instructions.</li>
            <li><strong>Stamp (1 op, ~3-5s):</strong> Revision number + date stamped on headers/footers via a single chat instruction.</li>
          </ol>
          <p style={{ marginTop: 12 }}><strong>Typical result:</strong></p>
          <ul style={{ paddingLeft: 20, marginTop: 4 }}>
            <li>Input: 13-paragraph FCOM document + edit "change crew from 2 to 3 pilots"</li>
            <li>Output: 1 modified paragraph, 1 apparatus batch (change bars + record table + highlights)</li>
            <li>Total: 3 ops, ~10-20s (mostly SuperDocs API latency)</li>
          </ul>
        </div>
      </div>
    </div>
  )
}

export default App
