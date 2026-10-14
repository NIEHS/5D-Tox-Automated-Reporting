import { Button, Card, Space, Tag, Typography } from 'antd'
import { Link, useParams } from 'react-router'
import type { Action, Readiness, StudyState } from '../api/types'
import { ItemList } from '../kit/ItemList'
import { moduleById, moduleRoute } from '../kit/modules'
import { useStudyState } from '../kit/useStudyState'
import { ACTION_ORDER, ACTION_WORDS, phaseWords } from '../kit/words'
import { nextStepOf } from './nextStep'

/**
 * A study's first page: every step of the data workflow, the ones the
 * backend allows now as links, every other one visibly unavailable with the
 * reason; then what needs attention, as the backend's readiness lists it.
 */

function actionLabel(a: Action, state: StudyState): string {
  if (a === 'REPROCESS' && state.processed) return 'Process the study again'
  return ACTION_WORDS[a].label
}

function Steps({ state }: { state: StudyState }) {
  const words = phaseWords(state.phase)
  const next = nextStepOf(state)
  const rows = ACTION_ORDER.map((a) => ({
    action: a,
    legal: words.known && state.legal_actions.includes(a),
    words: ACTION_WORDS[a],
  }))
  const reason = words.known
    ? `Not available now: the study is at "${words.label}".`
    : 'Not available: the study is at a stage this page does not know.'

  return (
    <Card title="Steps" size="small">
      <ItemList
        aria-label="Steps"
        items={rows}
        rowKey={(r) => r.action}
        rowProps={(r) => ({ 'data-action': r.action, 'data-available': r.legal ? 'yes' : 'no' })}
        render={({ action, legal, words: w }) => {
          const m = moduleById(w.module)
          const to = moduleRoute(w.module, state.id)
          const label = actionLabel(action, state)
          const isNext = legal && next?.label === w.label
          return (
            <Space orientation="vertical" size={0}>
              <Space>
                {legal && to ? (
                  <Link to={to}>
                    <Button type={isNext ? 'primary' : 'default'} danger={w.destructive}>
                      {label}
                    </Button>
                  </Link>
                ) : (
                  <Button disabled danger={w.destructive} aria-describedby={`why-${action}`}>
                    {label}
                  </Button>
                )}
                {isNext && <Tag color="blue">Next</Tag>}
                {m && (
                  <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                    in {m.title}
                  </Typography.Text>
                )}
              </Space>
              {!legal && (
                <Typography.Text id={`why-${action}`} type="secondary" style={{ fontSize: 12 }}>
                  {reason}
                </Typography.Text>
              )}
            </Space>
          )
        }}
      />
    </Card>
  )
}

function ReadinessCard({ title, readiness, studyId, emptySay }: { title: string; readiness?: Readiness; studyId: string; emptySay: string }) {
  if (!readiness) return null
  return (
    <Card title={title} size="small">
      {readiness.items.length === 0 ? (
        <Typography.Text>{emptySay}</Typography.Text>
      ) : (
        <ItemList
          dense
          items={readiness.items}
          rowKey={(item, i) => `${item.id}-${item.section ?? i}`}
          render={(item) => {
            const m = moduleById(item.fix)
            const to = m ? moduleRoute(m.id, studyId) : undefined
            return (
              <Space orientation="vertical" size={0}>
                <Space>
                  <Tag color={item.level === 'block' ? 'red' : 'gold'}>{item.level === 'block' ? 'Blocks' : 'Check'}</Tag>
                  <Typography.Text>{item.say}</Typography.Text>
                </Space>
                {m && to && <Link to={to}>Go to {m.title}</Link>}
              </Space>
            )
          }}
        />
      )}
    </Card>
  )
}

export function StudyOverview() {
  const { id = '' } = useParams()
  const { data } = useStudyState(id)
  if (!data) return null
  return (
    <Space orientation="vertical" size="middle" style={{ width: '100%' }}>
      <Steps state={data} />
      <ReadinessCard
        title="The data: what to look at"
        readiness={data.readiness?.data_approval}
        studyId={id}
        emptySay="Nothing to look at in the data."
      />
      <ReadinessCard
        title="What stops the report being published"
        readiness={data.readiness?.publish}
        studyId={id}
        emptySay="Nothing stops the report being published."
      />
    </Space>
  )
}
