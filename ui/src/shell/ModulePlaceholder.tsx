import { Result } from 'antd'
import { Link, useParams } from 'react-router'
import { moduleBySlug, studyRoute } from '../kit/modules'

/** A module's route before the module is built. */
export function ModulePlaceholder() {
  const { id = '', module: slug } = useParams()
  const m = moduleBySlug(slug)
  if (!m) {
    return (
      <Result
        status="404"
        title="There is no such page"
        subTitle={`This study has no page called "${slug ?? ''}".`}
        extra={<Link to={studyRoute(id)}>Back to the study</Link>}
      />
    )
  }
  return <Result status="info" title={m.title} subTitle={`${m.purpose} This page is not built yet.`} />
}
