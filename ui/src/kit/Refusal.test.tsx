import { screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { ApiError } from '../api/errors'
import { NOOP_SUMMARY_NOT_REWRITTEN, REFUSAL_PHASE_NOT_ALLOWED } from '../api/mocks/fixtures'
import { renderWithApp } from '../test/render'
import { Refusal } from './Refusal'

describe('<Refusal>', () => {
  it('says the plain words first, and keeps the technical message out of sight', () => {
    renderWithApp(<Refusal error={new ApiError(REFUSAL_PHASE_NOT_ALLOWED.error)} studyId="DTXSID1021952" />)
    expect(screen.getByRole('alert')).toHaveTextContent(REFUSAL_PHASE_NOT_ALLOWED.error.say)
    expect(screen.queryByText(/StepError/)).not.toBeInTheDocument()
  })

  it('links to the module that fixes it, for this study', () => {
    renderWithApp(<Refusal error={REFUSAL_PHASE_NOT_ALLOWED.error} studyId="DTXSID1021952" />)
    const link = screen.getByRole('link', { name: /Study files/ })
    expect(link).toHaveAttribute('href', '/studies/DTXSID1021952/files')
  })

  it('shows the message, code and details behind a toggle', async () => {
    const { user } = renderWithApp(<Refusal error={REFUSAL_PHASE_NOT_ALLOWED.error} studyId="DTXSID1021952" />)
    const toggle = screen.getByRole('button', { name: /Show the technical details/ })
    expect(toggle).toHaveAttribute('aria-expanded', 'false')
    await user.click(toggle)
    const details = screen.getByTestId('refusal-details')
    expect(details).toHaveTextContent('phase_not_allowed')
    expect(details).toHaveTextContent('INTEGRATE refused for DTXSID1021952')
    expect(details).toHaveTextContent('"legal_actions"')
    await user.click(screen.getByRole('button', { name: /Hide the technical details/ }))
    expect(screen.queryByTestId('refusal-details')).not.toBeInTheDocument()
  })

  it('has no link when nothing names the fix, and still offers the details', () => {
    renderWithApp(<Refusal error={{ ...REFUSAL_PHASE_NOT_ALLOWED.error, fix: null }} />)
    expect(screen.queryByRole('link')).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: /technical details/ })).toBeInTheDocument()
  })

  it('names the fixing module even without a study to link into', () => {
    renderWithApp(<Refusal error={REFUSAL_PHASE_NOT_ALLOWED.error} />)
    expect(screen.getByText(/It is fixed in Study files/)).toBeInTheDocument()
  })

  it('renders a success that did nothing as information, not as an error', () => {
    renderWithApp(<Refusal noop={NOOP_SUMMARY_NOT_REWRITTEN} />)
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
    const status = screen.getByRole('status')
    expect(status).toHaveTextContent('Nothing was changed')
    expect(status).toHaveTextContent(NOOP_SUMMARY_NOT_REWRITTEN.say)
  })
})
