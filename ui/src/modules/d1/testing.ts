import { fireEvent, screen, within } from '@testing-library/react'
import { renderApp } from '../../test/render'

/** Helpers for the review page's tests. */

/** Open the review page of a session and wait for its rail. */
export async function openReview(id: string) {
  const r = renderApp(`/studies/${id}/review`)
  await screen.findByTestId('review')
  return r
}

/** The list of one owner's sections. */
export function groupOf(owner: string): HTMLElement {
  const el = document.querySelector(`ul[data-group="${CSS.escape(owner)}"]`)
  if (!el) throw new Error(`no group of ${owner} (is it opened?)`)
  return el as HTMLElement
}

/** One section's row. */
export function sectionRow(owner: string, key: string): HTMLElement {
  const el = document.querySelector(`li[data-section="${CSS.escape(`${owner}/${key}`)}"]`)
  if (!el) throw new Error(`no row ${owner}/${key}`)
  return el as HTMLElement
}

/** The mark the kit shows for a section ("draft", "approved", …). */
export function markOf(row: HTMLElement): string | null {
  return row.querySelector('[data-mark]')?.getAttribute('data-mark') ?? null
}

export function approveButton(row: HTMLElement): HTMLButtonElement {
  return within(row).getByRole('button', { name: /^Approve / })
}

/** The book's frame, once the report's page was answered. */
export async function bookFrame(): Promise<HTMLIFrameElement> {
  return screen.findByTestId<HTMLIFrameElement>('book-frame')
}

/** Stand in for the browser: the frame has loaded a page that holds these element ids. */
export function loadBook(frame: HTMLIFrameElement, ids: string[]): void {
  const doc = frame.contentDocument
  if (!doc) throw new Error('the frame has no document')
  doc.open()
  doc.write(`<html><body>${ids.map((id) => `<h2 id="${id}">${id}</h2>`).join('')}</body></html>`)
  doc.close()
  for (const el of Array.from(doc.querySelectorAll('h2'))) el.scrollIntoView = () => undefined
  fireEvent.load(frame)
}

/** The whole alert whose title is `title`. */
export async function alertTitled(title: string | RegExp): Promise<HTMLElement> {
  const el = (await screen.findByText(title)).closest('.ant-alert')
  if (!el) throw new Error(`no alert titled ${String(title)}`)
  return el as HTMLElement
}
