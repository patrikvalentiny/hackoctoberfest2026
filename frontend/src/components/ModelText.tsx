import type { ReactNode } from 'react'

// Renders the small Markdown subset local models emit (headings, bullet and
// numbered lists, **bold**, *italic*) as React elements, never as raw HTML.

type Block =
  | { kind: 'heading'; text: string }
  | { kind: 'paragraph'; text: string; label?: string }
  | { kind: 'list'; ordered: boolean; items: string[] }

const BULLET = /^[-*•]\s+(.*)$/
const NUMBERED = /^\d+[.)]\s+(.*)$/
const HEADING = /^#{1,6}\s+(.*)$/
const BOLD_LINE = /^\*\*([^*]+?)\*\*:?$/
// Small models sometimes put a whole list on one line: "as follows: * 16:00 … * 17:00 …".
const INLINE_BULLET = /\s[*•]\s+(?=\S)/
// …and run a bold title into the text around it: "**Summary** The forecast…", "… 6.2 s **Weather Factors** * …".
const LEADING_TITLE = /(^|[.:!?]\s+)(\*\*[A-Z][^*\n]{1,48}\*\*):?[ \t]+/gm
const TRAILING_TITLE = /[ \t]+(\*\*[A-Z][^*\n]{1,48}\*\*):?(?=[ \t]+[*•-][ \t]|[ \t]*$)/gm
// "Overview: …", "Changes:" — the section labels the summary prompt asks for.
const LABEL = /^([A-Z][A-Za-z ]{1,20}):\s*(.*)$/

function splitInlineList(line: string): string[] {
  const parts = line.split(INLINE_BULLET)
  return parts.length >= 3 ? parts : [line]
}

function parse(text: string): Block[] {
  const blocks: Block[] = []
  let paragraph: string[] = []

  const flush = () => {
    if (paragraph.length) blocks.push({ kind: 'paragraph', text: paragraph.join(' ') })
    paragraph = []
  }
  const addItem = (ordered: boolean, item: string) => {
    const last = blocks.at(-1)
    if (last?.kind === 'list' && last.ordered === ordered) last.items.push(item)
    else blocks.push({ kind: 'list', ordered, items: [item] })
  }

  const lines = text.replace(LEADING_TITLE, '$1\n$2\n').replace(TRAILING_TITLE, '\n$1\n').split('\n')
  for (const raw of lines) {
    const [lead, ...inlineItems] = splitInlineList(raw.trim())
    const line = lead.trim()
    if (!line) {
      flush()
    } else if (HEADING.test(line) || BOLD_LINE.test(line)) {
      flush()
      blocks.push({ kind: 'heading', text: (line.match(HEADING) ?? line.match(BOLD_LINE))![1].trim() })
    } else if (BULLET.test(line) || NUMBERED.test(line)) {
      flush()
      const ordered = !BULLET.test(line)
      addItem(ordered, (line.match(BULLET) ?? line.match(NUMBERED))![1])
    } else if (LABEL.test(line)) {
      flush()
      const [, label, rest] = line.match(LABEL)!
      blocks.push(rest ? { kind: 'paragraph', label, text: rest } : { kind: 'heading', text: label })
    } else {
      paragraph.push(line)
    }
    if (inlineItems.length) {
      flush()
      inlineItems.forEach((item) => addItem(false, item.trim()))
    }
  }
  flush()
  return blocks
}

function inline(text: string): ReactNode[] {
  return text.split(/(\*\*[^*]+\*\*|\*[^*\s][^*]*\*|_[^_\s][^_]*_)/g).map((part, index) => {
    if (part.startsWith('**') && part.endsWith('**') && part.length > 4) {
      return <strong key={index} className="font-semibold">{part.slice(2, -2)}</strong>
    }
    if (/^([*_]).+\1$/.test(part)) {
      return <em key={index} className="text-muted-foreground">{part.slice(1, -1)}</em>
    }
    return part
  })
}

export function ModelText({ text, className = '' }: { text: string; className?: string }) {
  return (
    <div className={`space-y-2 text-sm leading-relaxed ${className}`}>
      {parse(text).map((block, index) => {
        if (block.kind === 'heading') {
          return <p key={index} className="font-semibold">{inline(block.text)}</p>
        }
        if (block.kind === 'paragraph') {
          return (
            <p key={index}>
              {block.label && <strong className="font-semibold">{block.label}: </strong>}
              {inline(block.text)}
            </p>
          )
        }
        const List = block.ordered ? 'ol' : 'ul'
        return (
          <List key={index} className={`space-y-1 pl-5 ${block.ordered ? 'list-decimal' : 'list-disc'}`}>
            {block.items.map((item, itemIndex) => (
              <li key={itemIndex} className="tabular-nums">{inline(item)}</li>
            ))}
          </List>
        )
      })}
    </div>
  )
}
