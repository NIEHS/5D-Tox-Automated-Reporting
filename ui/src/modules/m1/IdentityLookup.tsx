import { useMutation, useQueryClient } from '@tanstack/react-query'
import { Alert, Button, Modal, Space, Spin } from 'antd'
import { useState } from 'react'
import { recordIdentity } from '../../api/m1'
import type { ApiError } from '../../api/errors'
import type { ChemicalLookup, StudyRow } from '../../api/types'
import { Refusal } from '../../kit/Refusal'
import { invalidateStudy } from '../../kit/useStudyState'
import { useVocabularies } from '../../kit/useVocabularies'
import { ChemicalCard, ConfirmChemical } from './ChemicalCard'
import { identityNeed, identityToSend, type IdentityNeed } from './identityGap'
import { STUDIES_KEY, useChemicalLookup } from './queries'

/**
 * "Look up the chemical" on a study with no identity (M1 spec §3 S3): the
 * lookup's chemical card, the same confirm tick as S2, then
 * PUT …/identity. Changing an identity that exists is not offered (Q-M1-11).
 *
 * Never a dead end (maintainer, 2026-10-16, revised): a missing CAS number is
 * asked for, not required; when the lookup does not know the DTXSID, cannot
 * be reached or gives no name, the dialog says the chemical stays pending and
 * can be looked up again later, and closes with nothing changed.
 */
const STAYS_PENDING =
  'Nothing is changed: the study keeps its name and CAS number pending, and the chemical can be looked up again later from this page.'

export function IdentityLookup({ studyId, dtxsid }: { studyId: string; dtxsid: string }) {
  const [open, setOpen] = useState(false)
  return (
    <>
      <Button type="primary" onClick={() => setOpen(true)}>
        Look up the chemical
      </Button>
      {open && <LookupModal studyId={studyId} dtxsid={dtxsid} onClose={() => setOpen(false)} />}
    </>
  )
}

function LookupModal({ studyId, dtxsid, onClose }: { studyId: string; dtxsid: string; onClose: () => void }) {
  const qc = useQueryClient()
  const lookup = useChemicalLookup(dtxsid)
  const [confirmed, setConfirmed] = useState(false)
  const [checked, setChecked] = useState(false)
  const [casrn, setCasrn] = useState('')
  const [casrnOk, setCasrnOk] = useState(false)
  const save = useMutation<StudyRow, ApiError, { lookup: ChemicalLookup; need: IdentityNeed }>({
    mutationFn: ({ lookup: l, need: n }) =>
      recordIdentity(studyId, {
        identity: identityToSend(l, n, casrn),
        confirmed: true,
        dtxsid_checked_by_person: checked,
      }),
    onSettled: async () => {
      await invalidateStudy(qc, studyId)
      await qc.invalidateQueries({ queryKey: STUDIES_KEY })
    },
    onSuccess: () => onClose(),
  })
  const l = lookup.data
  const casrnRule = useVocabularies().data?.patterns.casrn
  // never send what the backend would refuse (identity_incomplete, invalid_casrn); a missing CAS number is allowed
  const need = l ? identityNeed(l, casrnRule) : null
  const canSave =
    Boolean(l) &&
    need !== null &&
    need.kind !== 'no_name' &&
    (need.kind !== 'casrn' || casrnOk) &&
    confirmed &&
    (l?.dtxsid_matched || checked)
  return (
    <Modal
      open
      title={`Look up the chemical ${dtxsid}`}
      width={760}
      mask={{ closable: false }}
      onCancel={() => !save.isPending && onClose()}
      okText="Save this identity"
      okButtonProps={{ disabled: !canSave, loading: save.isPending }}
      onOk={() => l && need && canSave && save.mutate({ lookup: l, need })}
      cancelText={lookup.error || need?.kind === 'no_name' ? 'Close; keep it pending' : 'Cancel'}
      destroyOnHidden
    >
      {lookup.isPending ? (
        <Spin description={`Looking up ${dtxsid} in PubChem…`}>
          <div style={{ minHeight: 120 }} />
        </Spin>
      ) : lookup.error ? (
        lookup.error.code === 'identity_lookup_unreachable' ? (
          <Alert
            type="warning"
            showIcon
            data-testid="lookup-unreachable"
            title={lookup.error.say}
            description={STAYS_PENDING}
            action={
              <Button onClick={() => void lookup.refetch()} loading={lookup.isFetching}>
                Try again
              </Button>
            }
          />
        ) : lookup.error.code === 'identity_not_found' ? (
          <Alert type="error" showIcon data-testid="lookup-not-found" title={lookup.error.say} description={STAYS_PENDING} />
        ) : (
          <Refusal error={lookup.error} title="The chemical could not be looked up" />
        )
      ) : (
        l && (
          <Space orientation="vertical" size="middle" style={{ width: '100%' }}>
            <ChemicalCard lookup={l} />
            <ConfirmChemical
              lookup={l}
              confirmed={confirmed}
              checked={checked}
              onConfirmed={setConfirmed}
              onChecked={setChecked}
              need={need ?? { kind: 'ok' }}
              casrn={casrn}
              casrnOk={casrnOk}
              onCasrn={setCasrn}
              onCasrnOk={setCasrnOk}
              noName={STAYS_PENDING}
              label={`This is the chemical studied under ${studyId}.`}
            />
            {save.error && <Refusal error={save.error} studyId={studyId} title="The identity was not saved" />}
          </Space>
        )
      )}
    </Modal>
  )
}
