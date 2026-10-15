import { Alert, Button, Card, Space, Tag, Typography } from 'antd'
import { Link } from 'react-router'
import type { Action, ExistingStudyState, Readiness } from '../api/types'
import { ItemList } from '../kit/ItemList'
import { PublishReadiness } from '../kit/PublishReadiness'
import { moduleById, moduleRoute } from '../kit/modules'
import { ACTION_ORDER, ACTION_WORDS, phaseWords } from '../kit/words'
import { nextStepOf } from './nextStep'

/**
 * The workflow panels of a study's landing page (M1's S3 shows them under
 * its own cards): every step of the data workflow, the ones the backend
 * allows now as links, every other one visibly unavailable with the reason;
 * then what needs attention, as the backend's readiness lists it, and the
 * analysis method.
 */

function actionLabel(a: Action, state: ExistingStudyState): string {
  if (a === 'REPROCESS' && state.processed) return 'Process the study again'
  return ACTION_WORDS[a].label
}

function Steps({ state }: { state: ExistingStudyState }) {
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

export function StudyWorkflowPanels({ state: data, showDefinition = true }: { state: ExistingStudyState; showDefinition?: boolean }) {
  const id = data.id
  return (
    <Space orientation="vertical" size="middle" style={{ width: '100%' }}>
      {data.kind === 'companion' ? null : data.kind === 'report' ? (
        <Card title="Steps" size="small">
          <Typography.Text>
            A report over several studies has no files of its own: each study it covers is brought in, checked and processed on its
            own page (the links above).
          </Typography.Text>
        </Card>
      ) : (
        <Steps state={data} />
      )}
      <ReadinessCard
        title="The data: what to look at"
        readiness={data.readiness.data_approval}
        studyId={id}
        emptySay="Nothing to look at in the data."
      />
      {data.kind !== 'companion' && (
        <Card title="What stops the report being published" size="small">
          <PublishReadiness readiness={data.readiness.publish} studyId={id} />
        </Card>
      )}
      {/* Published content is never processed: no method or definition to choose. */}
      {data.kind !== 'companion' && <PinsCard state={data} showDefinition={showDefinition} />}
    </Space>
  )
}

/** The method and the report definition, as the backend reports them: never a silent default. */
function PinsCard({ state, showDefinition }: { state: ExistingStudyState; showDefinition: boolean }) {
  const method = state.pins.method
  const definition = showDefinition ? state.pins.definition : undefined
  if (!method && !definition) return null
  const m5 = moduleById('M5')
  const to = moduleRoute('M5', state.id)
  return (
    <Card title={definition ? 'Method and report definition' : 'Analysis method'} size="small" extra={m5 && to ? <Link to={to}>Go to {m5.title}</Link> : null}>
      <Space orientation="vertical" size="small" style={{ width: '100%' }}>
        {method && (
          <div data-testid="pin-method">
            <Typography.Text strong>Analysis method: </Typography.Text>
            {method.error ? (
              <Typography.Text type="danger">{method.error.say}</Typography.Text>
            ) : method.pinned ? (
              <>
                <Typography.Text code>{method.name}</Typography.Text>{' '}
                <Tag>{method.mode === 'fixed' ? 'fixed' : method.mode === 'track' ? 'follows the newest' : (method.mode ?? 'mode not recorded')}</Tag>
                {method.pinned_by === 'default' ? <Tag color="gold">chosen by default, not by a person</Tag> : null}
              </>
            ) : (
              <Tag color="gold">not chosen</Tag>
            )}
            {[...(method.deviations ?? []), ...(method.unchecked ?? [])].length > 0 && (
              <ul style={{ margin: '4px 0 0', paddingInlineStart: 20 }}>
                {(method.deviations ?? []).map((d) => (
                  <li key={d}>
                    <Typography.Text>{d}</Typography.Text>
                  </li>
                ))}
                {(method.unchecked ?? []).map((d) => (
                  <li key={d}>
                    <Typography.Text type="secondary">{d}</Typography.Text>
                  </li>
                ))}
              </ul>
            )}
            {(method.mismatches ?? []).length > 0 && (
              <Alert
                style={{ marginTop: 4 }}
                type="warning"
                showIcon
                title="The analyses recorded in the data disagree with this method"
                description={
                  <ul style={{ margin: 0, paddingInlineStart: 20 }}>
                    {(method.mismatches ?? []).map((x) => (
                      <li key={`${x.analysis}-${x.setting}`}>{x.message}</li>
                    ))}
                  </ul>
                }
              />
            )}
          </div>
        )}
        {definition && (
          <div data-testid="pin-definition">
            <Typography.Text strong>Report definition: </Typography.Text>
            {definition.error ? (
              <Typography.Text type="danger">{definition.error.say}</Typography.Text>
            ) : (
              <>
                <Typography.Text code>{definition.name ?? 'not known'}</Typography.Text>{' '}
                <Tag>{DEFINITION_SOURCE[definition.source] ?? definition.source}</Tag>
                {definition.pinned ? (
                  <Tag>{definition.mode === 'fixed' ? 'fixed' : 'follows the newest'}</Tag>
                ) : (
                  <Tag color="gold">not pinned: follows the files</Tag>
                )}
              </>
            )}
            {definition.drift && <Alert style={{ marginTop: 4 }} type="warning" showIcon title={definition.drift} />}
          </div>
        )}
      </Space>
    </Card>
  )
}

const DEFINITION_SOURCE: Record<string, string> = {
  session: "this study's own definition",
  study: "the study's definition",
  era: 'the standard definition for its period',
  template: 'a template',
}
