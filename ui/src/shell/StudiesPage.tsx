import { Button, Card, Space, Typography } from 'antd'
import { useState } from 'react'
import { useNavigate } from 'react-router'
import { IdField } from '../kit/IdField'
import { studyRoute } from '../kit/modules'

/**
 * Placeholder for the Studies module (M1), which will list, create and delete
 * studies. Until then: open a study by its DTXSID.
 */
export function StudiesPage() {
  const navigate = useNavigate()
  const [id, setId] = useState('')
  const [ok, setOk] = useState(false)
  return (
    <Space orientation="vertical" size="large" style={{ width: '100%', maxWidth: 720 }}>
      <Typography.Title level={2}>Studies</Typography.Title>
      <Typography.Paragraph type="secondary">The list of studies is not built yet.</Typography.Paragraph>
      <Card title="Open a study">
        <form
          onSubmit={(e) => {
            e.preventDefault()
            if (ok) void navigate(studyRoute(id))
          }}
        >
          <Space orientation="vertical" style={{ width: '100%' }}>
            <Typography.Text>The chemical's DTXSID</Typography.Text>
            <IdField kind="dtxsid" value={id} onChange={setId} onCheck={setOk} />
            <Button type="primary" htmlType="submit" disabled={!ok}>
              Open
            </Button>
          </Space>
        </form>
      </Card>
    </Space>
  )
}
