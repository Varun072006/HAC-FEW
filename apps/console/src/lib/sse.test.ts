import { describe, expect, it } from 'vitest'
import { createSseParser } from './sse'

describe('createSseParser', () => {
  it('parses complete frames and ignores keep-alives and the retry preamble', () => {
    const p = createSseParser()
    const out = p.push('retry: 1500\n\n: keepalive\n\nid: 3\nevent: run_event\ndata: {"seq":3}\n\n')
    expect(out).toEqual([{ event: 'run_event', data: '{"seq":3}', id: '3' }])
  })

  it('reassembles a frame split across chunks at any byte boundary', () => {
    const whole = 'id: 7\nevent: run_event\ndata: {"seq":7,"type":"node.completed"}\n\nid: 8\nevent: end\ndata: {"run_status":"completed"}\n\n'
    for (let cut = 1; cut < whole.length; cut++) {
      const p = createSseParser()
      const got = [...p.push(whole.slice(0, cut)), ...p.push(whole.slice(cut))]
      expect(got.map((f) => f.event)).toEqual(['run_event', 'end'])
      expect(JSON.parse(got[0].data).seq).toBe(7)
    }
  })

  it('handles CRLF line endings and multi-line data', () => {
    const out = createSseParser().push('event: x\r\ndata: a\r\ndata: b\r\n\r\n')
    expect(out).toEqual([{ event: 'x', data: 'a\nb', id: undefined }])
  })

  it('never emits a frame without data', () => {
    expect(createSseParser().push('event: ping\n\n')).toEqual([])
  })
})
