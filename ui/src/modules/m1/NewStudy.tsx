import { ArrowRightOutlined } from '@ant-design/icons'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { Alert, Button, Card, Form, Result, Space, Spin, Steps, Typography } from 'antd'
import { useEffect, useState } from 'react'
import { Link, useLocation, useNavigate, useSearchParams } from 'react-router'
import { createStudy } from '../../api/m1'
import type { ApiError } from '../../api/errors'
import type { ChemicalLookup, CreationCheck, StudyDetail, StudyRow } from '../../api/types'
import { IdField } from '../../kit/IdField'
import { moduleById, moduleRoute, studyRoute } from '../../kit/modules'
import { Refusal } from '../../kit/Refusal'
import { useVocabularies } from '../../kit/useVocabularies'
import { ChemicalCard, ConfirmChemical } from './ChemicalCard'
import { identityGap } from './identityGap'
import { FormatNotice } from './FormatNotice'
import { STUDIES_KEY, useChemicalLookup, useCreationCheck, useStudyDetail } from './queries'
import { kindLabel } from './words'

/**
 * S2 New study (M1 spec §3): 1 the chemical's DTXSID → 2 confirm the chemical
 * and the format → 3 created. Nothing is written before step 3; reloading
 * returns to step 1 (the steps live only in this page). Whether the id may be
 * used, which chemical it is and which format it brings are the backend's
 * answers; the page only refuses to go on until they are in and confirmed.
 */

const CHECK_DEBOUNCE_MS = 350

function existingIdOf(err: ApiError): string | null {
  const v = err.details.existing_id
  return typeof v === 'string' ? v : null
}

function useDebounced<T>(value: T, ms: number): T {
  const [v, setV] = useState(value)
  useEffect(() => {
    const t = setTimeout(() => setV(value), ms)
    return () => clearTimeout(t)
  }, [value, ms])
  return v
}

function ExistsAlert({ check }: { check: CreationCheck }) {
  const id = check.existing?.id ?? check.dtxsid
  const { data } = useStudyDetail(id)
  const name = data?.identity.name
  return (
    <Alert
      type="warning"
      showIcon
      data-testid="study-exists"
      title={`A study of this chemical already exists: ${id}${name ? `, ${name}` : ''}.`}
      action={
        <Link to={studyRoute(id)}>
          <Button size="small">Open it</Button>
        </Link>
      }
    />
  )
}

function RelatedAlert({ check }: { check: CreationCheck }) {
  if (check.related_sessions.length === 0) return null
  return (
    <Alert
      type="info"
      showIcon
      data-testid="related-sessions"
      title="Already here for this chemical:"
      description={
        <ul style={{ margin: 0, paddingInlineStart: 20 }}>
          {check.related_sessions.map((r) => (
            <li key={r.id}>
              <Typography.Text style={{ fontFamily: 'monospace' }}>{r.id}</Typography.Text> ({r.say})
            </li>
          ))}
        </ul>
      }
    />
  )
}

/** Step 1: the id, checked as typed, then by the backend. */
function StepId({
  value,
  onChange,
  onNext,
}: {
  value: string
  onChange: (v: string) => void
  onNext: (id: string) => void
}) {
  const [ok, setOk] = useState(false)
  const [nexting, setNexting] = useState(false)
  const settled = useDebounced(ok ? value : null, CHECK_DEBOUNCE_MS)
  const checkId = ok && settled === value ? value : null
  const check = useCreationCheck(checkId)
  const canNext = ok && checkId !== null && check.data?.dtxsid === value && !check.data.exists && !check.isFetching

  const next = async () => {
    if (!canNext) return
    setNexting(true)
    // the check runs again at Next: the id must still be free
    const r = await check.refetch()
    setNexting(false)
    if (r.data && !r.data.exists) onNext(value)
  }

  return (
    <Form layout="vertical" onFinish={() => void next()} style={{ maxWidth: 560 }}>
      <Form.Item
        label="The chemical's DTXSID"
        htmlFor="m1-dtxsid"
        extra="Find it on the CompTox Chemicals Dashboard. The study's id is this DTXSID, and it can't be changed later."
      >
        <IdField
          kind="dtxsid"
          id="m1-dtxsid"
          label="The chemical's DTXSID"
          value={value}
          onChange={onChange}
          onCheck={setOk}
        />
      </Form.Item>
      <Space orientation="vertical" size="small" style={{ width: '100%', marginBottom: 16 }}>
        {checkId && check.isFetching && !check.data && <Typography.Text type="secondary">Checking the id…</Typography.Text>}
        {checkId && check.error && <Refusal error={check.error} title="This id cannot be used" />}
        {checkId && check.data?.dtxsid === value && check.data.exists && <ExistsAlert check={check.data} />}
        {checkId && check.data?.dtxsid === value && <RelatedAlert check={check.data} />}
      </Space>
      <Button type="primary" htmlType="submit" disabled={!canNext} loading={nexting} icon={<ArrowRightOutlined />} iconPlacement="end">
        Next
      </Button>
    </Form>
  )
}

/** Step 2: the lookup, the format, the confirmation, and the create. */
function StepConfirm({
  dtxsid,
  onBack,
  onCreated,
}: {
  dtxsid: string
  onBack: () => void
  onCreated: (row: StudyRow, format: CreationCheck['format']) => void
}) {
  const queryClient = useQueryClient()
  const navigate = useNavigate()
  const lookup = useChemicalLookup(dtxsid)
  const check = useCreationCheck(dtxsid)
  const [confirmed, setConfirmed] = useState(false)
  const [checked, setChecked] = useState(false)
  const [formatChanged, setFormatChanged] = useState(false)
  const casrnRule = useVocabularies().data?.patterns.casrn

  const create = useMutation<StudyRow, ApiError, { lookup: ChemicalLookup; check: CreationCheck }>({
    mutationFn: ({ lookup: l, check: c }) =>
      createStudy({
        dtxsid,
        identity: {
          name: l.identity.name,
          casrn: l.identity.casrn,
          pubchem_cid: l.identity.pubchem_cid,
          source: { kind: 'lookup', service: l.service, looked_up_at: l.looked_up_at },
        },
        confirmed: true,
        dtxsid_checked_by_person: checked,
        format_seen: { definition: c.format.definition, hash: c.format.hash ?? null },
      }),
    onSettled: () => queryClient.invalidateQueries({ queryKey: STUDIES_KEY }),
    onSuccess: (row) => onCreated(row, check.data!.format),
    onError: (err) => {
      if (err.code === 'format_changed') {
        setConfirmed(false)
        setFormatChanged(true)
        void check.refetch()
      }
      if (err.code === 'identity_changed') {
        setConfirmed(false)
        setChecked(false)
        void lookup.refetch()
      }
    },
  })

  if (lookup.isPending || (lookup.isFetching && !lookup.data)) {
    return (
      <Spin size="large" description={`Looking up ${dtxsid} in PubChem…`} data-testid="lookup-wait">
        <div style={{ minHeight: 160 }} />
      </Spin>
    )
  }

  const backButton = (
    <Button onClick={onBack} disabled={create.isPending}>
      Back to the id
    </Button>
  )

  if (lookup.error) {
    const e = lookup.error
    if (e.code === 'identity_lookup_unreachable') {
      return (
        <Alert
          type="warning"
          showIcon
          data-testid="lookup-unreachable"
          title={e.say}
          action={
            <Space orientation="vertical">
              <Button onClick={() => void lookup.refetch()} loading={lookup.isFetching}>
                Try again
              </Button>
              {backButton}
            </Space>
          }
        />
      )
    }
    if (e.code === 'identity_not_found') {
      return <Alert type="error" showIcon data-testid="lookup-not-found" title={e.say} action={backButton} />
    }
    return <Refusal error={e} title="The chemical could not be looked up" action={backButton} />
  }

  const l = lookup.data
  const c = check.data
  const formatWords = c ? c.format.title : null
  const confirmNeeds = !l.dtxsid_matched && !checked
  // never offer a create the backend would refuse (identity_incomplete, invalid_casrn)
  const gap = identityGap(l, "a study can't be created", casrnRule)
  const canCreate = !gap && Boolean(c) && confirmed && !confirmNeeds && !check.isFetching && !create.isPending

  return (
    <Space orientation="vertical" size="middle" style={{ width: '100%', maxWidth: 880 }}>
      <ChemicalCard lookup={l} />
      <Card title="The report format" size="small">
        {check.error ? (
          <Refusal error={check.error} title="The format could not be read" />
        ) : !c ? (
          <Spin description="Reading the format" />
        ) : (
          <Space orientation="vertical" size="small" style={{ width: '100%' }}>
            {formatChanged && (
              <Alert type="warning" showIcon title="The format this id brings changed since you looked. It is shown again below; review it." />
            )}
            <FormatNotice format={c.format} />
          </Space>
        )}
      </Card>
      {c && formatWords && (
        <ConfirmChemical
          lookup={l}
          confirmed={confirmed}
          checked={checked}
          onConfirmed={setConfirmed}
          onChecked={setChecked}
          blocked={gap}
          label={
            <span data-testid="confirm-label">
              This is the chemical I am studying, and the study will be written in <em>{formatWords}</em>.
            </span>
          }
        />
      )}
      {create.error && create.error.code !== 'format_changed' && (
        <Refusal
          error={create.error}
          title="The study was not created"
          action={
            create.error.code === 'study_exists' ? (
              <Button onClick={() => void navigate(studyRoute(existingIdOf(create.error) ?? dtxsid))}>Open it</Button>
            ) : undefined
          }
        />
      )}
      <Space>
        <Button onClick={onBack} disabled={create.isPending}>
          Back
        </Button>
        <Button type="primary" disabled={!canCreate} loading={create.isPending} onClick={() => c && create.mutate({ lookup: l, check: c })}>
          Create study
        </Button>
      </Space>
    </Space>
  )
}

function StepCreated({ row, formatTitle }: { row: StudyRow; formatTitle: string | null }) {
  const next = row.stands.next
  const m = moduleById(next?.fix)
  const to = m ? (m.id === 'M1' ? studyRoute(row.id) : moduleRoute(m.id, row.id)) : undefined
  return (
    <Result
      status="success"
      title={`Study ${row.id} created: ${row.identity.name ?? ''}${row.identity.casrn ? ` (${row.identity.casrn})` : ''}`}
      subTitle={
        <Space orientation="vertical" size={2}>
          {formatTitle && <span>It will be written in {formatTitle}.</span>}
          <span>
            Where it stands: {row.stands.say} ({kindLabel(row)}).
          </span>
        </Space>
      }
      extra={[
        next && to ? (
          <Link key="next" to={to}>
            <Button type="primary" icon={<ArrowRightOutlined />} iconPlacement="end">
              {next.say}
            </Button>
          </Link>
        ) : (
          <Link key="open" to={studyRoute(row.id)}>
            <Button type="primary">Open the study</Button>
          </Link>
        ),
        <Link key="list" to="/studies">
          <Button>Back to studies</Button>
        </Link>,
      ]}
    />
  )
}

/** What the create hands the success view, so it shows at once (the address alone is enough: it re-reads). */
interface CreatedState {
  created?: { row: StudyRow; formatTitle: string }
}

/**
 * Step 3, at its own address (`/studies/new?created=<id>`): the study as the
 * backend now serves it. Reached only by a create, which replaced the form's
 * place in the history with the list: Back goes to the studies, and neither
 * Back, Forward nor a reload brings the filled-in form back.
 */
function CreatedView({ id }: { id: string }) {
  const handed = (useLocation().state as CreatedState | null)?.created
  const detail = useStudyDetail(id)
  const d: StudyDetail | undefined = detail.data
  if (d) return <StepCreated row={d} formatTitle={d.detail.format?.title ?? d.format?.title ?? null} />
  if (handed && handed.row.id === id) return <StepCreated row={handed.row} formatTitle={handed.formatTitle} />
  if (detail.error) {
    return (
      <Refusal
        error={detail.error}
        title="The new study could not be read"
        action={
          <Link to="/studies">
            <Button>Back to studies</Button>
          </Link>
        }
      />
    )
  }
  return <Spin description="Reading the new study" />
}

export function NewStudy() {
  const [params] = useSearchParams()
  const navigate = useNavigate()
  const created = params.get('created')
  const [value, setValue] = useState(() => (params.get('dtxsid') ?? '').trim().toUpperCase())
  const [step, setStep] = useState<{ at: 0 } | { at: 1; dtxsid: string }>({ at: 0 })

  const onCreated = async (row: StudyRow, format: CreationCheck['format']) => {
    // The form's place in the history becomes the list, and the success view gets its own
    // address: Back from it goes to the studies, and the filled-in form can't be reached again.
    await navigate('/studies', { replace: true })
    const state: CreatedState = { created: { row, formatTitle: format.title } }
    await navigate(`/studies/new?created=${encodeURIComponent(row.id)}`, { state })
  }

  return (
    <Space orientation="vertical" size="large" style={{ width: '100%' }}>
      <Space orientation="vertical" size={0}>
        <Link to="/studies">← Studies</Link>
        <Typography.Title level={2} style={{ margin: 0 }}>
          New study
        </Typography.Title>
      </Space>
      <Steps
        current={created ? 2 : step.at}
        items={[{ title: "The chemical's DTXSID" }, { title: 'Confirm the chemical and the format' }, { title: 'Created' }]}
        style={{ maxWidth: 880 }}
      />
      {created ? (
        <CreatedView id={created} />
      ) : (
        <>
          {step.at === 0 && <StepId value={value} onChange={setValue} onNext={(dtxsid) => setStep({ at: 1, dtxsid })} />}
          {step.at === 1 && (
            <StepConfirm
              key={step.dtxsid}
              dtxsid={step.dtxsid}
              onBack={() => setStep({ at: 0 })}
              onCreated={(row, format) => void onCreated(row, format)}
            />
          )}
        </>
      )}
    </Space>
  )
}
