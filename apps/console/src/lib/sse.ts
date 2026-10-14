/** Incremental Server-Sent Events parser. Feed it text chunks as they arrive; it returns complete frames
 *  and keeps any trailing partial frame for the next call (a network chunk can split a frame anywhere). */
export interface SseFrame { event: string; data: string; id?: string }

export function createSseParser() {
  let buf = ''
  return {
    push(chunk: string): SseFrame[] {
      buf += chunk.replace(/\r\n/g, '\n')
      const frames: SseFrame[] = []
      let i: number
      while ((i = buf.indexOf('\n\n')) !== -1) {
        const block = buf.slice(0, i)
        buf = buf.slice(i + 2)
        let event = 'message'
        let id: string | undefined
        const data: string[] = []
        for (const line of block.split('\n')) {
          if (line.startsWith(':') || !line) continue           // comment / keep-alive
          const c = line.indexOf(':')
          const field = c === -1 ? line : line.slice(0, c)
          const value = c === -1 ? '' : line.slice(c + 1).replace(/^ /, '')
          if (field === 'event') event = value
          else if (field === 'data') data.push(value)
          else if (field === 'id') id = value
        }
        if (data.length) frames.push({ event, data: data.join('\n'), id })
      }
      return frames
    },
  }
}
