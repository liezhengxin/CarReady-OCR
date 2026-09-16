# Pelindungan Data Pribadi — UU No. 27 Tahun 2022

Data protection design for the Caready inspection system. The machine-readable
half of this document is [`config/pdp.yaml`](../config/pdp.yaml); this file
carries the reasoning and the legal-basis mapping.

> **Retention periods and their legal bases are unconfirmed placeholders.**
> The purge job runs with `dry_run: true` — it reports what it *would* delete
> and deletes nothing. See [OPEN_ITEMS #7](OPEN_ITEMS.md). This document must
> be reviewed by Caready's legal counsel before production go-live; it is an
> engineering design record, not legal advice.

---

## What personal data the system processes

The STNK is the only source of personal data in the pipeline. Photographing it
is unavoidable — it is the authoritative record of vehicle identity, and its
tax panel is the sole source of tax status.

| Field | Class | Why collected | Masked as |
|---|---|---|---|
| `nama_pemilik` | general | Owner identity verification | `B**** S******` |
| `alamat` | general | Domicile / registration region | Street redacted, city kept |
| `nik` | **specific** | Identity verification, when present on the document | Fully masked, never partial |
| `nomor_registrasi` | general | Operational unit lookup | `B 1*** XYZ` |
| `nomor_bpkb` | general | Ownership document verification | Last 4 only |
| `photos.gps_lat/lon` | general | Inspection location verification | Rounded to ~1 km |

`nik` is marked optional because it is not always printed on an STNK. **When
absent it is not inferred or sourced elsewhere.**

Under Art. 4(3), NIK is *data pribadi spesifik* and carries stricter handling:
unmasking requires a typed justification, not merely an audit record.

---

## Design principles

### 1. Built in from M2, not retrofitted

PII classification is declared at the schema level — `UnitStnkData.nama_pemilik`
is an `EncryptedText` column, not a `String` someone remembered to protect.
The classification in `config/pdp.yaml` drives masking, access logging, and
purge without each consumer re-deciding.

### 2. Masked by default, everywhere

List views and detail views return masked values. Unmasking is an explicit
action requiring the `pii:unmask` capability, and it writes a
`pii_access_log` row **before** the plaintext reaches the response.

**Denied attempts are logged too.** An attempt to unmask is itself worth
recording.

### 3. The audit log never contains PII

`audit_log` records *that* a PII field changed, by whom, and when — never the
value. Copying plaintext into an append-only table would create a second,
unerasable copy of exactly the data the retention policy exists to remove.

The redaction is enforced centrally in `app/services/audit.py`, matched on
field-name suffix, so a future caller cannot forget.

### 4. Logs never contain PII

The structlog pipeline carries a redaction processor keyed on the same
suffixes. It runs *after* the enrichment processors, so it also covers keys
added downstream.

### 5. One deliberate exception, recorded

`nomor_registrasi` is **not encrypted at rest**. It is the primary operational
lookup key, and an encrypted column cannot be indexed or searched.

The mitigation is masking plus access logging. The trade-off is recorded in
`config/pdp.yaml` (`encrypt_at_rest: false`) rather than being an unexamined
omission. Every other PII field is only ever read back per-unit, never queried
across, so encryption costs nothing there.

---

## Encryption

Fernet (AES-128-CBC + HMAC-SHA256) via `cryptography`. Authenticated and
misuse-resistant; the threat model is database disclosure, not an attacker with
application memory access.

**Key management.** Keys come from `PII_ENCRYPTION_KEYS` — comma-separated,
where the first entry encrypts and every entry is tried on decrypt. That makes
rotation possible without downtime: prepend the new key, run the re-encryption
job, remove the old key.

In production, keys must come from a secrets manager. The API refuses to start
in `prod` with the development default.

**Decryption failure is not fatal.** A failed decrypt returns a redaction
marker rather than raising, because raising would make an entire unit
unreadable — including its non-PII fields — after a botched rotation. The
failure is logged at error level and is visible in the UI.

---

## Third-party processing

**Default posture: raw PII does not leave our infrastructure.**

`config/pdp.yaml` → `third_party.allow_raw_pii_to_external_providers: false`,
and a DPA reference must be recorded before it can be enabled.

For STNK OCR, full redaction before extraction is impossible — the provider
must see the document to read it. The mitigations are:

1. **Provider choice.** The local PaddleOCR adapter keeps the image on our
   infrastructure entirely. It is the PDP-preferred option and the reason two
   implementations ship rather than one.
2. **Region masking.** For external providers, the STNK template matcher
   locates and masks `nama_pemilik`, `alamat`, and `nik` before upload.
3. **Fail closed.** If the template does not match, the external call is
   **refused** rather than sent unmasked.

---

## Legal-basis mapping

> **Placeholder. Requires legal review.**

| Processing purpose | Data | Proposed basis | Status |
|---|---|---|---|
| Vehicle identity verification for auction | `nama_pemilik`, `nomor_registrasi`, `nomor_rangka` | Contract performance (Art. 20(2)(b)) — the consignor's auction agreement | 🔴 unconfirmed |
| Fraud prevention (VIN/engine cross-check) | `nomor_rangka`, `nomor_mesin` | Legitimate interest (Art. 20(2)(f)) | 🔴 unconfirmed |
| Ownership document verification | `nomor_bpkb`, `nik` | Legal obligation (Art. 20(2)(c)) if required by vehicle transfer regulation | 🔴 unconfirmed |
| Inspection location verification | GPS | Legitimate interest — inspection integrity | 🔴 unconfirmed |
| Pricing model training | **de-identified only** | Not personal data once de-identified | 🟠 reasoning needs confirmation |

The last row matters: the deletion posture
(`pii_erasure_retain_deidentified`) rests on the retained pricing record no
longer being personal data. If that reasoning does not hold, deletion must
remove the auction record too — which has consequences for model integrity that
should be understood before, not after, the first deletion request.

---

## Retention

> **All periods below are placeholders.** `retention.dry_run: true`.

| Entity | Retained | Clock starts | Basis |
|---|---|---|---|
| `unit_stnk_data` (PII columns only) | 1,095 days | Unit terminal status | 🔴 placeholder |
| `photos` (STNK captures) | 1,095 days | Unit terminal status | 🔴 placeholder |
| `ocr_extractions` (raw responses) | 1,095 days | Unit terminal status | 🔴 placeholder |
| `pii_access_log` | 1,825 days | Row creation | Processing accountability |

The access log deliberately **outlives** the data it describes. Being able to
answer "who looked at this person's data, and when" after the data itself is
gone is the point of an access log.

Purging writes an audit record per entity. Records under `legal_hold` are never
purged regardless of age.

The purge deletes from append-only tables via the transactional
`caready.allow_append_only_purge` escape hatch — the single legitimate reason
to bypass the audit triggers.

---

## Data subject rights

| Right | Endpoint | Notes |
|---|---|---|
| Access / portability | `GET /api/pdp/subject-export` | Resolved by plate, VIN, or unit code |
| Erasure | `POST /api/pdp/subject-delete` | PII erased, de-identified record retained |
| Rectification | Standard unit edit with audit | — |

SLA: 30 days. Both operations require `pii:unmask` plus a typed justification,
and both write audit records.

**Lookup keys are `nomor_registrasi`, `nomor_rangka`, and `unit_code`** — never
name, because name is not unique and resolving a request by name risks
disclosing one person's record to another.

---

## Security controls supporting PDP

| Control | Implementation |
|---|---|
| Encryption in transit | TLS terminated at the ingress (deployment concern) |
| Encryption at rest | Fernet on PII columns; disk encryption is infrastructure |
| Access control | Capability-based RBAC, enforced server-side |
| Photo access | Short-lived signed URLs (300s); buckets private |
| Password storage | argon2id, parameters upgraded transparently on login |
| Session invalidation | `token_version` bump revokes outstanding access tokens |
| Refresh token theft | Family revocation on reuse detection |
| Audit integrity | Database triggers, not application discipline |

---

## Outstanding actions before go-live

1. Legal review of the basis mapping above — [OPEN_ITEMS #7](OPEN_ITEMS.md)
2. Confirm retention periods, then set `retention.dry_run: false`
3. Record a DPA reference if any external OCR provider is used
4. Move `PII_ENCRYPTION_KEYS` to a secrets manager and define a rotation cadence
5. Confirm whether NIK appears on the STNK variants Caready actually handles —
   if never, remove the field rather than carry specific personal data unused
6. Appoint a data protection contact and document the breach notification path
