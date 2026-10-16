import { screen, waitFor, within } from '@testing-library/react'
import { expect } from 'vitest'
import { renderApp } from '../../test/render'

/** Helpers for M1's tests. */

export function row(key: string): HTMLElement {
  const el = document.querySelector(`tr[data-row-key="${CSS.escape(key)}"]`)
  if (!el) throw new Error(`no row ${key}`)
  return el as HTMLElement
}

export function queryRow(key: string): HTMLElement | null {
  return document.querySelector(`tr[data-row-key="${CSS.escape(key)}"]`)
}

export async function openList() {
  const r = renderApp('/studies')
  await screen.findByRole('table')
  return r
}

export async function expand(key: string, user: ReturnType<typeof renderApp>['user']) {
  const btn = within(row(key)).getByRole('button', { name: /expand row/i })
  await user.click(btn)
  await waitFor(() => expect(within(row(key)).getByRole('button', { name: /collapse row/i })).toBeInTheDocument())
}

export async function openStudyPage(id: string) {
  const r = renderApp(`/studies/${id}`)
  await screen.findByTestId('where-it-stands')
  return r
}

/** The note the backend serves for a damaged file (workflow/refusals.py `damaged_session_file`). */
export function DAMAGED_NOTE(id: string, file = 'document_definition.json') {
  return {
    level: 'error',
    code: 'damaged_session_file',
    say:
      `One of this study's saved files is damaged and can't be read (${id}/${file}). Nothing was changed. ` +
      'Tell the maintainer: the file must be repaired or restored before work on this study can go on.',
  }
}
