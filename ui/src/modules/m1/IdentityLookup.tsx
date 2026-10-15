import { useMutation, useQueryClient } from '@tanstack/react-query'
import { Alert, Button, Modal, Space, Spin } from 'antd'
import { useState } from 'react'
import { recordIdentity } from '../../api/m1'
import type { ApiError } from '../../api/errors'
import type { ChemicalLookup, StudyRow } from '../../api/types'
import { Refusal } from '../../kit/Refusal'
import { invalidateStudy } from '../../kit/useStudyState'
import { ChemicalCard, ConfirmChemical } from './ChemicalCard'
import { STUDIES_KEY, useChemicalLookup } from './queries'

/**
 * "Look up the chemical" on a study with no identity (M1 spec §3 S3): the
 * lookup's chemical card, the same confirm tick as S2, then
 * PUT …/identity. Changing an identity that exists is not offered (Q-M1-11).
 */
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
  const save = useMutation<StudyRow, ApiError, ChemicalLookup>({
    mutationFn: (l) =>
      recordIdentity(studyId, {
        identity: {
          name: l.identity.name,
          casrn: l.identity.casrn,
          pubchem_cid: l.identity.pubchem_cid,
          source: { kind: 'lookup', service: l.service, looked_up_at: l.looked_up_at },
        },
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
  return (
    <Modal
      open
      title={`Look up the chemical ${dtxsid}`}
      width={760}
      mask={{ closable: false }}
      onCancel={() => !save.isPending && onClose()}
      okText="Save this identity"
      okButtonProps={{ disabled: !l || !confirmed || (!l.dtxsid_matched && !checked), loading: save.isPending }}
      onOk={() => l && save.mutate(l)}
      cancelText="Cancel"
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
            title={lookup.error.say}
            action={
              <Button onClick={() => void lookup.refetch()} loading={lookup.isFetching}>
                Try again
              </Button>
            }
          />
        ) : lookup.error.code === 'identity_not_found' ? (
          <Alert type="error" showIcon title={lookup.error.say} />
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
              label={`This is the chemical studied under ${studyId}.`}
            />
            {save.error && <Refusal error={save.error} studyId={studyId} title="The identity was not saved" />}
          </Space>
        )
      )}
    </Modal>
  )
}
