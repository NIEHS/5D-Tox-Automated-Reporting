import { CheckCircleFilled, ExportOutlined } from '@ant-design/icons'
import { Alert, Card, Checkbox, Descriptions, Image, Space, Typography } from 'antd'
import { useState } from 'react'
import { m1Paths } from '../../api/m1'
import type { ChemicalLookup } from '../../api/types'
import { IdField } from '../../kit/IdField'
import { Pending } from '../../kit/Pending'
import type { IdentityNeed } from './identityGap'

/**
 * "The chemical" (M1 spec §3 S2 step 2): what the lookup found, shown for a
 * person to confirm. Used in S2 and in S3's "Look up the chemical". Nothing
 * here is filled in by the front-end: a value the lookup did not give is
 * shown as pending.
 */

function Structure({ lookup }: { lookup: ChemicalLookup }) {
  const [failed, setFailed] = useState(false)
  const src = lookup.structure_url ?? m1Paths.structure(lookup.dtxsid)
  if (failed || !lookup.structure_url) {
    return <Pending label="structure picture unavailable" cause="PubChem did not return a structure picture." />
  }
  return (
    <Image
      src={src}
      alt={`Structure of ${lookup.identity.name || lookup.dtxsid}`}
      width={180}
      height={180}
      preview={false}
      onError={() => setFailed(true)}
      style={{ objectFit: 'contain', background: '#fff' }}
    />
  )
}

export function ChemicalCard({ lookup }: { lookup: ChemicalLookup }) {
  const id = lookup.identity
  return (
    <Card title="The chemical" size="small" data-testid="chemical-card">
      <Space orientation="vertical" size="middle" style={{ width: '100%' }}>
        <Space align="start" size="large" wrap>
          <Descriptions size="small" column={1} style={{ minWidth: 280 }}>
            <Descriptions.Item label="Name">
              {id.name?.trim() ? (
                <Typography.Text strong>{id.name}</Typography.Text>
              ) : (
                <Pending label="name" cause={`${lookup.service} gave no name for this compound.`} />
              )}
            </Descriptions.Item>
            <Descriptions.Item label="CASRN">
              {id.casrn ?? <Pending label="CASRN" cause="The lookup gave no CAS number. You may type it below, from a source you trust, or leave it pending." />}
            </Descriptions.Item>
            <Descriptions.Item label="DTXSID">
              <Space size={6} wrap>
                <Typography.Text style={{ fontFamily: 'monospace' }}>{lookup.dtxsid}</Typography.Text>
                {lookup.dtxsid_matched && (
                  <Typography.Text type="success">
                    <CheckCircleFilled aria-hidden /> {lookup.service} lists this DTXSID for this compound
                  </Typography.Text>
                )}
              </Space>
            </Descriptions.Item>
            <Descriptions.Item label="Formula">
              {id.molecular_formula ?? <Pending label="formula" cause="The lookup gave no molecular formula." />}
            </Descriptions.Item>
            <Descriptions.Item label="Molecular weight">
              {id.molecular_weight !== null ? `${id.molecular_weight} g/mol` : <Pending label="molecular weight" cause="The lookup gave none." />}
            </Descriptions.Item>
            <Descriptions.Item label="PubChem number (CID)">
              {id.pubchem_cid !== null ? (
                <a href={`https://pubchem.ncbi.nlm.nih.gov/compound/${id.pubchem_cid}`} target="_blank" rel="noopener noreferrer">
                  {id.pubchem_cid} <ExportOutlined aria-label="opens in a new tab" />
                </a>
              ) : (
                <Pending label="PubChem number" cause="The lookup gave none." />
              )}
            </Descriptions.Item>
          </Descriptions>
          <Structure lookup={lookup} />
        </Space>
        {!lookup.dtxsid_matched && (
          <Alert
            type="warning"
            showIcon
            title={`${lookup.service} found a compound, but does not list ${lookup.dtxsid} for it. Check the id on the CompTox dashboard before you go on.`}
          />
        )}
        <Typography.Text type="secondary" data-testid="lookup-source">
          {lookup.say_source}
        </Typography.Text>
      </Space>
    </Card>
  )
}

/**
 * The confirm tick(s) under the chemical. When the lookup could not match the
 * DTXSID, a second tick ("I checked…") must come first; the first stays
 * disabled until it does.
 *
 * When the lookup gave no usable CAS number (`need.kind === 'casrn'`: none,
 * or one that fails its check digit), the person is asked for one but may go
 * on without it (maintainer, 2026-10-16, revised). Empty is allowed; a typed
 * value must pass the served pattern and its check digit before the tick
 * opens. Changing it unticks the confirmation (what was confirmed changed).
 *
 * When the lookup gave no name (`no_name`), there is nothing to confirm here:
 * the tick is closed, why is said, and `noName` (the screen's way on) is
 * shown under it. A person never types a name (Q-M1-3).
 */
export function ConfirmChemical({
  lookup,
  label,
  confirmed,
  checked,
  onConfirmed,
  onChecked,
  need,
  casrn,
  casrnOk,
  onCasrn,
  onCasrnOk,
  noName,
}: {
  lookup: ChemicalLookup
  label: React.ReactNode
  confirmed: boolean
  checked: boolean
  onConfirmed: (v: boolean) => void
  onChecked: (v: boolean) => void
  need: IdentityNeed
  /** the CAS number the person typed (only when `need.kind === 'casrn'`), and whether it may be sent (empty, or passing the served rule) */
  casrn: string
  casrnOk: boolean
  onCasrn: (value: string) => void
  onCasrnOk: (ok: boolean) => void
  /** what the screen offers when the lookup gave no name */
  noName?: React.ReactNode
}) {
  const needsCheck = !lookup.dtxsid_matched
  if (need.kind === 'no_name') {
    return (
      <Space orientation="vertical" size="small" style={{ width: '100%' }}>
        <Alert type="warning" showIcon data-testid="identity-no-name" title={need.say} description={noName} />
        <Checkbox checked={false} disabled>
          {label}
        </Checkbox>
      </Space>
    )
  }
  const askCasrn = need.kind === 'casrn'
  // the field reports an empty value as acceptable (optional), a typed one only when it passes the rule
  const casrnBad = askCasrn && !casrnOk
  return (
    <Space orientation="vertical" size="small" style={{ width: '100%' }}>
      {askCasrn && (
        <Card size="small" title="The CAS number (optional)" data-testid="casrn-ask">
          <Space orientation="vertical" size="small" style={{ width: '100%', maxWidth: 420 }}>
            <Typography.Text>{need.say}</Typography.Text>
            <IdField
              kind="casrn"
              id="m1-casrn"
              label="CAS number (optional)"
              optional
              value={casrn}
              onChange={(v) => {
                // what was confirmed changed: confirm again
                onConfirmed(false)
                onCasrn(v)
              }}
              onCheck={onCasrnOk}
            />
            <Typography.Text type="secondary" data-testid="casrn-optional">
              {casrn.trim() === ''
                ? 'Left empty, the study shows "[CASRN pending]" until the CAS number is added.'
                : 'It will be recorded as stated by you.'}
            </Typography.Text>
          </Space>
        </Card>
      )}
      {needsCheck && (
        <Checkbox
          checked={checked}
          onChange={(e) => {
            onChecked(e.target.checked)
            if (!e.target.checked) onConfirmed(false)
          }}
        >
          I checked the DTXSID {lookup.dtxsid} on the CompTox dashboard
        </Checkbox>
      )}
      <Checkbox
        checked={confirmed}
        disabled={(needsCheck && !checked) || casrnBad}
        onChange={(e) => onConfirmed(e.target.checked)}
      >
        {label}
      </Checkbox>
      {casrnBad && (
        <Typography.Text type="secondary" data-testid="casrn-wait">
          Correct the CAS number above, or empty the field to leave it pending.
        </Typography.Text>
      )}
    </Space>
  )
}
