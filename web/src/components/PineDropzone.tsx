import { useCallback, useRef, useState } from 'react'

interface PineDropzoneProps {
  pineScript: string
  fileName: string | null
  onScriptChange: (script: string, fileName: string | null) => void
  disabled?: boolean
}

export function PineDropzone({
  pineScript,
  fileName,
  onScriptChange,
  disabled,
}: PineDropzoneProps) {
  const [dragOver, setDragOver] = useState(false)
  const inputRef = useRef<HTMLInputElement>(null)

  const readFile = useCallback(
    async (file: File) => {
      const text = await file.text()
      onScriptChange(text, file.name)
    },
    [onScriptChange],
  )

  const onDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault()
      setDragOver(false)
      if (disabled) return
      const file = e.dataTransfer.files[0]
      if (file) readFile(file)
    },
    [disabled, readFile],
  )

  return (
    <div className="rounded-lg border border-[var(--tv-border)] bg-[var(--tv-panel)]">
      <div
        onDragOver={(e) => {
          e.preventDefault()
          if (!disabled) setDragOver(true)
        }}
        onDragLeave={() => setDragOver(false)}
        onDrop={onDrop}
        onClick={() => !disabled && inputRef.current?.click()}
        className={[
          'cursor-pointer rounded-t-lg border-b border-[var(--tv-border)] px-4 py-6 text-center transition-colors',
          dragOver ? 'bg-[#2962ff22]' : 'hover:bg-[#ffffff08]',
          disabled ? 'pointer-events-none opacity-50' : '',
        ].join(' ')}
      >
        <input
          ref={inputRef}
          type="file"
          accept=".pine,.txt,.pinescript"
          className="hidden"
          onChange={(e) => {
            const file = e.target.files?.[0]
            if (file) readFile(file)
          }}
        />
        <div className="text-sm text-[var(--tv-muted)]">
          Drop Pine Script here or click to browse
        </div>
        <div className="mt-1 text-xs text-[var(--tv-muted)]">
          .pine · .txt · TradingView export
        </div>
        {fileName && (
          <div className="mt-3 text-sm font-medium text-[var(--tv-green)]">
            {fileName}
          </div>
        )}
      </div>

      <div className="p-3">
        <label className="mb-1 block text-xs uppercase tracking-wide text-[var(--tv-muted)]">
          Pine Script
        </label>
        <textarea
          value={pineScript}
          onChange={(e) => onScriptChange(e.target.value, fileName)}
          disabled={disabled}
          placeholder="// Paste your //@version=5 strategy(...) script here"
          className="h-36 w-full resize-y rounded border border-[var(--tv-border)] bg-[var(--tv-bg)] p-3 font-mono text-xs leading-relaxed text-[var(--tv-text)] outline-none focus:border-[var(--tv-accent)] disabled:opacity-50"
        />
      </div>
    </div>
  )
}
