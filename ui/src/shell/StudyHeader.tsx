import { ArrowRightOutlined } from '@ant-design/icons'
import { Alert, Button, Card, Descriptions, Space, Tag, Typography } from 'antd'
import { Link } from 'react-router'
import type { ModuleId, StudyState } from '../api/types'
import { nextStepOf } from './nextStep'
import { moduleById, moduleRoute, studyRoute } from '../kit/modules'
import { Pending } from '../kit/Pending'
import { phaseWords } from '../kit/words'

/**
 * The top of every study page: which study, its stage in plain words, and
 * the next step. Everything here is read from the state; the "next step" is
 * one of the backend's legal actions (or, once processed, the first thing
 * that blocks publishing), never worked out in the browser.
 */

function MissingOr({ value, label, fix, studyId }: { value?: string; label: string; fix: ModuleId; studyId: string }) {
  if (value) return <>{value}</>
  return <Pending label={label} cause={`The ${label} is not known yet.`} fix={fix} studyId={studyId} />
}

export function StudyHeader({ state }: { state: StudyState }) {
  const id = state.id
  const words = phaseWords(state.phase)
  const step = nextStepOf(state)
  const stepModule = step?.module ? moduleById(step.module) : undefined
  const stepPath = step?.module ? moduleRoute(step.module, id) : undefined
  const identity = state.identity ?? {}

  return (
    <Card style={{ marginBottom: 16 }}>
      <Space orientation="vertical" size="middle" style={{ width: '100%' }}>
        <Space wrap align="baseline" size="middle">
          <Typography.Title level={3} style={{ margin: 0 }}>
            {identity.name ?? 'Unnamed study'}
          </Typography.Title>
          <Typography.Text code copyable aria-label="Study id">
            {id}
          </Typography.Text>
        </Space>

        <Descriptions size="small" column={{ xs: 1, sm: 2, lg: 3 }}>
          <Descriptions.Item label="Chemical">
            <MissingOr value={identity.name} label="chemical name" fix="M3" studyId={id} />
          </Descriptions.Item>
          <Descriptions.Item label="CAS number">
            <span style={{ whiteSpace: 'nowrap' }}>
              <MissingOr value={identity.casrn} label="CAS number" fix="M3" studyId={id} />
            </span>
          </Descriptions.Item>
          <Descriptions.Item label="Short name">
            <MissingOr value={identity.short_name} label="short name" fix="M4" studyId={id} />
          </Descriptions.Item>
          <Descriptions.Item label="Stage" span="filled">
            <Space size={4} wrap>
              <Tag color={words.known ? 'blue' : 'red'} data-testid="phase">
                {words.label}
              </Tag>
              <Typography.Text type="secondary">{words.explain}</Typography.Text>
            </Space>
          </Descriptions.Item>
        </Descriptions>

        {state.members && state.members.length > 0 && (
          <div aria-label="Studies in this report">
            <Typography.Text strong>This report covers {state.members.length} studies: </Typography.Text>
            <Space wrap size="small">
              {state.members.map((m) => (
                <Link key={m.id} to={studyRoute(m.id)}>
                  {m.role} ({m.id}){m.phase ? `: ${phaseWords(m.phase).label}` : ''}
                  {m.processed === false ? ', not processed' : ''}
                </Link>
              ))}
            </Space>
          </div>
        )}

        {!words.known ? (
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
        ) : (
          <Alert type="warning" showIcon title="No step is available now." description={words.explain} />
        )}
      </Space>
    </Card>
  )
}
