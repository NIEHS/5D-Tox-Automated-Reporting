import { Result } from 'antd'
import { Link } from 'react-router'

export function NotFound() {
  return <Result status="404" title="There is no such page" extra={<Link to="/studies">Go to the studies</Link>} />
}
