import { Button, Card, Skeleton, Space, Tabs, Typography } from 'antd'
import { useParams, useSearchParams } from 'react-router'
import { Refusal } from '../../kit/Refusal'
import { useStudyState } from '../../kit/useStudyState'
import { Citations } from './Citations'
import { Outside } from './marks'
import { PartView } from './PartView'
import { useWriting } from './queries'
import { API_PAGE_LEAD, PAGE_PURPOSE, PAGE_TITLE, TAB_CITATIONS, TAB_SECTIONS } from './words'
import { WrittenSections } from './WrittenSections'

/**
 * Written sections (the demo path, spec §4 S3) with its Citations tab (S4).
 * The address keeps what is open (`?tab=citations`, `?part=<key>&of=<study>`),
 * so the switch between a finished report and its live copy, and a link from
 * another page, land on the same view. Everything about who wrote a part,
 * what is recorded and which act is offered comes from the backend.
 */
export function WritingPage() {
  const { id = '' } = useParams()
  const [params, setParams] = useSearchParams()
  const tab = params.get('tab') === 'citations' ? 'citations' : 'sections'
  const part = params.get('part')
  const owner = params.get('of') ?? id
  const { data: state } = useStudyState(id)
  const { data: overview, error, isPending, refetch, isFetching } = useWriting(id)

  const openPart = (studyId: string, key: string) =>
    setParams(studyId === id ? { part: key } : { part: key, of: studyId })
  const closePart = () => setParams({})

  return (
    <Space orientation="vertical" size="middle" style={{ width: '100%' }}>
      <Card size="small">
        <Space orientation="vertical" size={4} style={{ width: '100%' }}>
          <Typography.Title level={3} style={{ margin: 0 }}>
            {PAGE_TITLE}
          </Typography.Title>
          <Typography.Text>{PAGE_PURPOSE}</Typography.Text>
          {overview && overview.api_page.length > 0 && (
            <Space wrap size="small" data-testid="api-page">
              <Typography.Text type="secondary">{API_PAGE_LEAD}</Typography.Text>
              {overview.api_page.map((l) => (
                <Outside key={l.group} href={l.href}>
                  {l.title}
                </Outside>
              ))}
            </Space>
          )}
        </Space>
      </Card>

      {isPending ? (
        <Skeleton active paragraph={{ rows: 8 }} />
      ) : !overview ? (
        <Refusal
          error={error}
          studyId={id}
          title="The written sections could not be read"
          action={
            <Button onClick={() => void refetch()} loading={isFetching}>
              Try again
            </Button>
          }
        />
      ) : (
        <Tabs
          activeKey={tab}
          onChange={(key) => setParams(key === 'citations' ? { tab: 'citations' } : {})}
          items={[
            {
              key: 'sections',
              label: TAB_SECTIONS,
              children: part ? (
                <PartView
                  studyId={owner}
                  part={part}
                  checkSays={overview.check_says}
                  canTake={owner === id && overview.acts.summary.allowed}
                  onBack={closePart}
                />
              ) : (
                <WrittenSections studyId={id} state={state?.exists ? state : undefined} overview={overview} onOpen={openPart} />
              ),
            },
            { key: 'citations', label: TAB_CITATIONS, children: <Citations studyId={id} /> },
          ]}
        />
      )}
    </Space>
  )
}
