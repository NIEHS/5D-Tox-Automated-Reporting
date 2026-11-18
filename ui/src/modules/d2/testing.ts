import { screen, within } from '@testing-library/react'
import { renderApp } from '../../test/render'

/** Helpers for the Written sections page's tests. */

export async function openWriting(id: string, query = '') {
  const r = renderApp(`/studies/${id}/writing${query}`)
  await screen.findByTestId('api-page')
  return r
}

export function partRow(key: string, within_?: HTMLElement): HTMLElement {
  const el = (within_ ?? document.body).querySelector(`tr[data-part="${CSS.escape(key)}"]`)
  if (!el) throw new Error(`no part row ${key}`)
  return el as HTMLElement
}

export function entryRow(n: number): HTMLElement {
  const el = document.querySelector(`tr[data-entry="${n}"]`)
  if (!el) throw new Error(`no reference entry ${n}`)
  return el as HTMLElement
}

/** Open a part from the list and wait for its view. */
export async function openPart(key: string, user: ReturnType<typeof renderApp>['user'], group?: HTMLElement) {
  await user.click(within(partRow(key, group)).getByRole('button', { name: /^Open / }))
  return screen.findByTestId('part-view')
}

/** The refusal (or notice) whose title is `title`: the whole alert. */
export async function alertTitled(title: string | RegExp): Promise<HTMLElement> {
  const el = (await screen.findByText(title)).closest('.ant-alert')
  if (!el) throw new Error(`no alert titled ${String(title)}`)
  return el as HTMLElement
}
