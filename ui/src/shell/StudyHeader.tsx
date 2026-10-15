import { ArrowRightOutlined } from '@ant-design/icons'
import { Alert, Button, Card, Descriptions, Space, Tag, Typography } from 'antd'
import { Link } from 'react-router'
import type { ExistingStudyState, ModuleId } from '../api/types'
import { nextStepOf } from './nextStep'
import { moduleById, moduleRoute, studyRoute } from '../kit/modules'
import { Pending } from '../kit/Pending'
import { PhaseTag } from '../kit/PhaseTag'
import { phaseWords } from '../kit/words'

/**
 * The top of every study page: which study, what kind of session it is, its
 * stage in plain words, and the next step. Everything here is read from the
 * state; the "next step" is ranked in nextStep.ts until the backend serves it.
 */

function MissingOr({ value, label, fix, studyId }: { value?: string | null; label: string; fix: ModuleId; studyId: string }) {
  if (value) return <>{value}</>
  return <Pending label={label} cause={`The ${label} is not known yet.`} fix={fix} studyId={studyId} />
}

/** What the session is, in plain words, with the links to the sessions it belongs with. */
function KindNote({ state }: { state: ExistingStudyState }) {
  if (state.kind === 'companion') {
    return (
      <Alert
        type="info"
        showIcon
        data-testid="kind-note"
        title="This is the published book's content, kept for comparison. It is read-only: nothing here is processed or approved."
        description={
          state.relations.twin ? (
            <span>
              The study generated beside it: <Link to={studyRoute(state.relations.twin)}>{state.relations.twin}</Link>
            </span>
          ) : undefined
        }
      />
    )
  }
  if (state.kind === 'member') {
    return (
      <Alert
        type="info"
        showIcon
        data-testid="kind-note"
        title={
          <span>
            This study is part of a report over several studies
            {state.relations.parent ? (
              <>
                : <Link to={studyRoute(state.relations.parent)}>{state.relations.parent}</Link>
              </>
            ) : null}
            . Its sections are approved here; the report is put together there.
          </span>
        }
      />
    )
  }
  if (state.kind === 'report') {
    const members = state.members ?? []
    return (
      <div aria-label="Studies in this report" data-testid="kind-note">
        <Typography.Text strong>
          This report covers {members.length} {members.length === 1 ? 'study' : 'studies'}; it has no data files of its own:{' '}
        </Typography.Text>
        <Space wrap size="small">
          {members.map((m) => (
            <Link key={m.id} to={studyRoute(m.id)}>
              {m.key} ({m.id})
              {!m.exists ? ': missing' : `: ${phaseWords(m.phase ?? '').label}${m.processed ? '' : ', not processed'}`}
            </Link>
          ))}
        </Space>
      </div>
    )
  }
  return null
}

export function StudyHeader({ state }: { state: ExistingStudyState }) {
  const id = state.id
  const words = phaseWords(state.phase)
  const step = nextStepOf(state)
  const stepModule = step?.module ? moduleById(step.module) : undefined
  const stepPath = step?.module ? moduleRoute(step.module, id) : undefined
  const identity = state.identity
  // A report or a companion has no stage of its own: its files are elsewhere.
  const showStage = state.kind !== 'report' && state.kind !== 'companion'

  return (
    <Card style={{ marginBottom: 16 }}>
      <Space orientation="vertical" size="middle" style={{ width: '100%' }}>
        <Space wrap align="baseline" size="middle">
          <Typography.Title level={3} style={{ margin: 0 }}>
            {identity?.name ?? 'Unnamed study'}
          </Typography.Title>
          <Typography.Text code copyable aria-label="Study id">
            {id}
          </Typography.Text>
        </Space>

        <Descriptions size="small" column={{ xs: 1, sm: 2, lg: 3 }}>
          <Descriptions.Item label="Chemical">
            <MissingOr value={identity?.name} label="chemical name" fix="M3" studyId={id} />
          </Descriptions.Item>
          <Descriptions.Item label="CAS number">
            <span style={{ whiteSpace: 'nowrap' }}>
              <MissingOr value={identity?.casrn} label="CAS number" fix="M3" studyId={id} />
            </span>
          </Descriptions.Item>
          <Descriptions.Item label="Short name">
            <MissingOr value={identity?.short_name} label="short name" fix="M4" studyId={id} />
          </Descriptions.Item>
          {showStage && (
            <Descriptions.Item label="Stage" span="filled">
              <Space size={4} wrap>
                {state.stands ? (
                  <PhaseTag phase={state.stands.phase} say={state.stands.say} />
                ) : (
                  <Tag color={words.known ? 'blue' : 'red'} data-testid="phase">
                    {words.label}
                  </Tag>
                )}
                <Typography.Text type="secondary">{words.explain}</Typography.Text>
              </Space>
            </Descriptions.Item>
          )}
        </Descriptions>

        <KindNote state={state} />

        {showStage && !words.known ? (
          <Alert type="error" showIcon title="This page cannot offer any step" description={words.explain} />
        ) : step ? (
          <Alert
            type="info"
            showIcon
            title={
              <span>
                <Typography.Text strong>Next step: </Typography.Text>
                {step.label}
              </span>
            }
            description={
              <Space orientation="vertical" size="small">
                {step.why && <Typography.Text>{step.why}</Typography.Text>}
                {stepPath && stepModule && (
                  <Link to={stepPath}>
                    <Button type="primary" icon={<ArrowRightOutlined />} iconPlacement="end">
                      Go to {stepModule.title}
                    </Button>
                  </Link>
                )}
              </Space>
            }
          />
        ) : state.kind === 'companion' ? null : (
          <Alert type="warning" showIcon title="No step is available now." description={words.explain} />
        )}
      </Space>
    </Card>
  )
}
