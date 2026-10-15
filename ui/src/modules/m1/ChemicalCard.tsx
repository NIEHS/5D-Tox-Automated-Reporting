import { CheckCircleFilled, ExportOutlined } from '@ant-design/icons'
import { Alert, Card, Checkbox, Descriptions, Image, Space, Typography } from 'antd'
import { useState } from 'react'
import { m1Paths } from '../../api/m1'
import type { ChemicalLookup, IdPattern } from '../../api/types'
import { checkId } from '../../kit/checkId'
import { Pending } from '../../kit/Pending'

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
      alt={`Structure of ${lookup.identity.name}`}
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
              <Typography.Text strong>{id.name}</Typography.Text>
            </Descriptions.Item>
            <Descriptions.Item label="CASRN">{id.casrn ?? <Pending label="CASRN" cause="The lookup gave no CAS number." />}</Descriptions.Item>
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
 * Why a looked-up identity can't be used, or null when it can. The backend
 * refuses a study or an identity without a name and a CAS number
 * (`identity_incomplete`), or with a CAS number whose check digit fails
 * (`invalid_casrn`); the screen never offers what it would refuse. No CAS
 * number is typed in instead: a stated identity is ruled out (Q-M1-3).
 * `outcome` finishes the sentence: "a study can't be created", "this
 * identity can't be saved".
 */
export function identityGap(lookup: ChemicalLookup, outcome: string, casrnPattern?: IdPattern): string | null {
  const { name, casrn } = lookup.identity
  const svc = lookup.service
  const missing = [!name?.trim() && 'name', !casrn?.trim() && 'CAS number'].filter(Boolean) as string[]
  if (missing.length > 0) {
    const what = missing.length === 2 ? 'no name and no CAS number' : `no ${missing[0]}`
    return (
      `${svc} gives ${what} for this chemical, so ${outcome} from this lookup yet. ` +
      "A study needs the chemical's name and CAS number. Ask the maintainer how to go on."
    )
  }
  // the pattern is the backend's; when it has not loaded, the backend decides
  const c = casrnPattern ? checkId('casrn', (casrn ?? '').trim(), casrnPattern) : null
  if (c && c.ok === false) {
    return (
      `The CAS number ${svc} gives for this chemical (${casrn}) is not a valid one, so ${outcome} ` +
      'from this lookup yet. Ask the maintainer how to go on.'
    )
  }
  return null
}

/**
 * The confirm tick(s) under the chemical. When the lookup could not match the
 * DTXSID, a second tick ("I checked…") must come first; the first stays
 * disabled until it does.
 */
export function ConfirmChemical({
  lookup,
  label,
  confirmed,
  checked,
  onConfirmed,
  onChecked,
  blocked,
}: {
  lookup: ChemicalLookup
  label: React.ReactNode
  confirmed: boolean
  checked: boolean
  onConfirmed: (v: boolean) => void
  onChecked: (v: boolean) => void
  /** why the identity can't be used (identityGap); the ticks are then closed and this is said instead */
  blocked?: string | null
}) {
  const needsCheck = !lookup.dtxsid_matched
  if (blocked) {
    return (
      <Space orientation="vertical" size="small" style={{ width: '100%' }}>
        <Alert type="error" showIcon data-testid="identity-incomplete" title={blocked} />
        <Checkbox checked={false} disabled>
          {label}
        </Checkbox>
      </Space>
    )
  }
  return (
    <Space orientation="vertical" size="small">
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
      <Checkbox checked={confirmed} disabled={needsCheck && !checked} onChange={(e) => onConfirmed(e.target.checked)}>
        {label}
      </Checkbox>
    </Space>
  )
}
