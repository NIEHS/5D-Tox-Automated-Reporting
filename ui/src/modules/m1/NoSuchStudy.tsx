import { Button, Result, Space, Typography } from 'antd'
import { Link } from 'react-router'
import { useQueryClient } from '@tanstack/react-query'
import type { Vocabularies } from '../../api/types'

/**
 * S5 No such study (M1 spec §3): in place of a study's page when the id
 * names no session, is not a study id, or was deleted while open. Opening it
 * creates nothing (C4).
 */
export function NoSuchStudy({ id, reason, say }: { id: string; reason: 'not_found' | 'invalid' | 'deleted'; say?: string }) {
  // Read the id rule if it is already loaded; never fetch it from here. (Subscribing would refetch a
  // failed rule on mount, and the study frame shows a spinner while the rule is loading: a loop.)
  const vocab = useQueryClient().getQueryData<Vocabularies>(['vocabularies'])
  const strict = vocab?.patterns.study_id
  const canCreate = reason !== 'invalid' && strict ? new RegExp(strict.pattern).test(id) : false
  const back = (
    <Link key="back" to="/studies">
      <Button>Back to studies</Button>
    </Link>
  )
  if (reason === 'invalid') {
    return (
      <Result
        status="warning"
        title={`'${id}' is not a study id.`}
        subTitle={say || strict ? <Typography.Text>{say ?? strict?.say}</Typography.Text> : undefined}
        extra={[back]}
      />
    )
  }
  return (
    <Result
      status="404"
      title={reason === 'deleted' ? 'This study was deleted.' : `There is no study ${id}. It may have been deleted.`}
      subTitle={
        <Space orientation="vertical" size={2}>
          <Typography.Text style={{ fontFamily: 'monospace' }}>{id}</Typography.Text>
        </Space>
      }
      extra={[
        canCreate ? (
          <Link key="create" to={`/studies/new?dtxsid=${encodeURIComponent(id)}`}>
            <Button type="primary">Create a study of this chemical</Button>
          </Link>
        ) : null,
        back,
      ]}
    />
  )
}
