import { InboxOutlined } from '@ant-design/icons'
import { Alert, Button, Card, Checkbox, Space, Table, Tag, Typography, Upload } from 'antd'
import type { UploadFile } from 'antd'
import { useState } from 'react'
import type { IntakeAnswers, IntakePlan, IntakeRow, Verdict } from '../../api/files'
import { bringInFiles } from '../../api/files'
import { ApiError } from '../../api/errors'
import { Refusal } from '../../kit/Refusal'
import {
  ANSWERS,
  BRING_IN_BUTTON,
  BRING_IN_EXPLAIN,
  BRING_IN_TITLE,
  CHOSEN,
  DROP_EXPLAIN,
  DROP_HINT,
  acceptedWords,
  broughtInWords,
  planWords,
  verdictMark,
} from './words'

/**
 * Bringing a study's data files in (M2, act 1). Files are chosen from a
 * dialog or dropped on the page; nothing is sent until "Bring them in".
 *
 * The browser checks nothing: every file is planned by the backend
 * (pipeline.intake), which says in its own words what each one would do. The
 * batch is one act — while any file waits on an answer the backend brings
 * none of them in and answers with the plan, which is what is shown here with
 * a box to tick per question. Ticking and sending again is the same batch,
 * from the files the browser still holds.
 */

type Answered = Record<string, boolean>

function answersOf(rows: IntakeRow[], ticked: Answered): IntakeAnswers {
  const of = (question: IntakeRow['needs_answer']) =>
    rows.filter((row) => row.needs_answer === question && ticked[row.name]).map((row) => row.name)
  return { replace: of('replace'), copy_anyway: of('copy'), without_units: of('without_units') }
}

export function BringIn({ id, act, filesToken }: { id: string; act: Verdict; filesToken: string | null }) {
  const [chosen, setChosen] = useState<UploadFile[]>([])
  const [plan, setPlan] = useState<IntakePlan | null>(null)
  const [waiting, setWaiting] = useState<IntakeRow[]>([])
  const [ticked, setTicked] = useState<Answered>({})
  const [error, setError] = useState<ApiError | null>(null)
  const [sending, setSending] = useState(false)

  // antd hands back its own RcFile, which is a File with an id added.
  const files: File[] = chosen.flatMap((one) => (one.originFileObj ? [one.originFileObj as File] : []))

  function forget() {
    setPlan(null)
    setWaiting([])
    setTicked({})
    setError(null)
  }

  async function send() {
    setSending(true)
    setError(null)
    try {
      const done = await bringInFiles(id, files, {
        answers: answersOf(waiting, ticked),
        filesToken,
      })
      setPlan(done)
      setWaiting([])
      setTicked({})
      setChosen([])
    } catch (err) {
      if (!(err instanceof ApiError)) throw err
      const rows = (err.body.details?.rows as IntakeRow[] | undefined) ?? []
      setWaiting(err.code === 'answer_required' ? rows.filter((row) => row.needs_answer) : [])
      setPlan(rows.length ? { ...EMPTY_PLAN, id, rows } : null)
      setError(err)
    } finally {
      setSending(false)
    }
  }

  if (!act.allowed) {
    return (
      <Card size="small" title={BRING_IN_TITLE} data-testid="bring-in">
        <Alert type="info" showIcon message={act.say} data-testid="bring-in-not-allowed" />
      </Card>
    )
  }

  return (
    <Card size="small" title={BRING_IN_TITLE} data-testid="bring-in">
      <Space orientation="vertical" size="small" style={{ display: 'flex' }}>
        <Typography.Text type="secondary">{BRING_IN_EXPLAIN}</Typography.Text>
        <div data-testid="dropzone">
          <Upload.Dragger
            multiple
            fileList={chosen}
            beforeUpload={() => false}
            onChange={({ fileList }) => {
              setChosen(fileList)
              forget()
            }}
          >
            <p className="ant-upload-drag-icon">
              <InboxOutlined aria-hidden />
            </p>
            <p className="ant-upload-text">{DROP_EXPLAIN}</p>
            <p className="ant-upload-hint">{DROP_HINT}</p>
          </Upload.Dragger>
        </div>

        {waiting.length > 0 && <Answers rows={waiting} ticked={ticked} onTick={setTicked} />}
        {error && error.code !== 'answer_required' && (
          <Refusal error={error} studyId={id} title="Nothing was brought in" />
        )}
        {error?.code === 'answer_required' && (
          <Alert type="warning" showIcon message={error.say} data-testid="answer-required" />
        )}

        {plan && <Plan plan={plan} />}

        <Space>
          <Button
            type="primary"
            disabled={!files.length}
            loading={sending}
            onClick={() => void send()}
            data-testid="bring-in-send"
          >
            {BRING_IN_BUTTON}
          </Button>
          {files.length > 0 && <Typography.Text type="secondary">{CHOSEN(files.length)}</Typography.Text>}
        </Space>
        <Typography.Text type="secondary">{acceptedWords()}</Typography.Text>
      </Space>
    </Card>
  )
}

const EMPTY_PLAN: IntakePlan = {
  id: '',
  applied: false,
  dry_run: false,
  rows: [],
  counts: { add: 0, unchanged: 0, refused: 0, left_out: 0, needs_answer: 0 },
  brought_in: [],
  replaced: [],
  files_token: '',
}

function Answers({
  rows,
  ticked,
  onTick,
}: {
  rows: IntakeRow[]
  ticked: Answered
  onTick: (next: Answered) => void
}) {
  return (
    <Card size="small" type="inner" title={ANSWERS.title} data-testid="answers">
      <Space orientation="vertical" size="small" style={{ display: 'flex' }}>
        <Typography.Text type="secondary">{ANSWERS.explain}</Typography.Text>
        {rows.map((row) => (
          <div key={row.name} data-testid={`answer-${row.name}`}>
            <Checkbox
              checked={Boolean(ticked[row.name])}
              onChange={(e) => onTick({ ...ticked, [row.name]: e.target.checked })}
            >
              <Space orientation="vertical" size={0}>
                <Typography.Text>{ANSWERS.question[row.needs_answer ?? 'replace']}</Typography.Text>
                <Typography.Text type="secondary">{row.say}</Typography.Text>
              </Space>
            </Checkbox>
          </div>
        ))}
      </Space>
    </Card>
  )
}

function Plan({ plan }: { plan: IntakePlan }) {
  return (
    <Space orientation="vertical" size="small" style={{ display: 'flex' }}>
      {plan.applied && (
        <Alert type="success" showIcon message={broughtInWords(plan)} data-testid="brought-in" />
      )}
      <Table<IntakeRow>
        aria-label={planWords.title}
        size="small"
        rowKey="name"
        dataSource={plan.rows}
        pagination={false}
        scroll={{ x: true }}
        data-testid="plan"
        columns={[
          {
            title: planWords.file,
            dataIndex: 'name',
            render: (name: string, row) => (
              <Space orientation="vertical" size={0}>
                <Typography.Text code>{name}</Typography.Text>
                {row.from_zip && (
                  <Typography.Text type="secondary">{planWords.fromZip(row.from_zip)}</Typography.Text>
                )}
              </Space>
            ),
          },
          {
            title: planWords.what,
            key: 'verdict',
            render: (_: unknown, row) => {
              const mark = verdictMark(row.verdict)
              return <Tag color={mark.tone}>{mark.label}</Tag>
            },
          },
          {
            title: planWords.say,
            dataIndex: 'say',
            render: (say: string) => <Typography.Text>{say}</Typography.Text>,
          },
        ]}
      />
    </Space>
  )
}
