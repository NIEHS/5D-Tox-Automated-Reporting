import { HttpResponse, http } from 'msw'
import { API_V2 } from '../client'
import type { FilesView } from '../files'
import type { ErrorEnvelope } from '../types'
import FILES_CHECKED from './fixtures/m2/files.checked.json'
import FILES_EMPTY from './fixtures/m2/files.empty.json'
import FILES_REPORT from './fixtures/m2/files.report.json'

/**
 * The Study files page (M2). The answers are real ones, taken from the backend
 * on a real study: a checked study, a report over several studies (whose data
 * is its studies', so it takes no files), and a study with nothing in it yet.
 */

const SESSION_ID = /^DTXSID[A-Za-z0-9_-]{1,64}$/

export const FILES_BY_ID: Record<string, FilesView> = {
  DTXSID6020430_rat: FILES_CHECKED,
  DTXSID6020430: FILES_REPORT,
  DTXSID9000001: FILES_EMPTY,
}

function envelope(code: string, status: number, say: string, message: string): Response {
  const body: ErrorEnvelope = { error: { code, status, message, say, fix: 'M2', details: {} } }
  return HttpResponse.json(body, { status })
}

export function createM2Handlers() {
  return [
    http.get(`${API_V2}/studies/:id/files`, ({ params }) => {
      const id = String(params.id)
      if (!SESSION_ID.test(id)) {
        return envelope(
          'invalid_study_id',
          400,
          'That is not a valid study id. A study is named by its chemical’s DTXSID.',
          `invalid dtxsid: ${id}`,
        )
      }
      const view = FILES_BY_ID[id]
      if (!view) {
        return envelope(
          'study_not_found',
          404,
          `There is no study ${id}. It may have been deleted.`,
          `no session ${id}`,
        )
      }
      return HttpResponse.json(view)
    }),
  ]
}
